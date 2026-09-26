"""`flyspeare view`: a local web app to watch and run the flies.

Serves the 9:16 page (web/) and a small JSON API over the runs directory. Rooms run as their
own processes (`flyspeare room ...`), so closing the viewer never stops training: rooms keep
going for days, and the viewer can be reopened, or a room loaded again later.

API
  GET  /api/rooms                         list rooms with progress
  POST /api/rooms            {name, flies, speed}   start a new room
  POST /api/rooms/NAME/load  {speed}      resume a saved room
  POST /api/rooms/NAME/stop               checkpoint every fly and stop
  DELETE /api/rooms/NAME                  delete a stopped room and all its saves
  POST /api/rooms/NAME/control {speed?, paused?, watch?, save?, no_rest?}
  GET  /api/rooms/NAME/status             leaderboard (room.json)
  GET  /api/rooms/NAME/fly/ID/live        the watched fly's latest attempts
  GET  /api/rooms/NAME/fly/ID/paper       the text it has typed so far (tail); ?before=N&size=M pages back
  GET  /api/rooms/NAME/fly/ID/feelings    its brain and body state, read out (feelings.py)
  GET  /api/rooms/NAME/fly/ID/brain       its sense -> projection-neuron mapping
  GET  /api/flywire                       real neuron positions for the brain map
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from functools import lru_cache
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .room import fly_dir, read_control, read_status, room_text, set_control
from .text import load

WEB = Path(__file__).parent / "web"
PROJECT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@lru_cache(maxsize=4)
def _text(path: str):
    display, words = load(path)
    return display, words


@lru_cache(maxsize=1)
def _flywire_json() -> bytes:
    from . import flywire
    d = flywire.load()
    r = lambda a: (a / 1000).round(1).tolist()  # nm -> um
    return json.dumps({
        "version": 783, "units": "um",
        "kc_pos": r(d["kc_pos"]), "kc_type": d["kc_type"].tolist(),
        "pn_pos": r(d["pn_pos"]), "dan_pos": r(d["dan_pos"]), "dan_type": d["dan_type"].tolist(),
        "mbon_pos": r(d["mbon_pos"]), "mbon_type": d["mbon_type"].tolist(),
        "brain_pos": r(d["brain_pos"]),
    }).encode()


def _pid_alive(room: Path) -> int | None:
    try:
        pid = int((room / "room.pid").read_text())
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None


def _room_summary(room: Path) -> dict:
    cfg = json.loads((room / "room-config.json").read_text())
    out = {"name": room.name, "flies": cfg["flies"], "created": cfg.get("created"),
           "running": _pid_alive(room) is not None, **{k: read_control(room)[k] for k in ("speed", "paused", "no_rest")}}
    try:
        st = read_status(room)
        n_words = len(_text(cfg["text"])[1])
        words = [f["word"] for f in st["flies"]]
        out.update(updated=st["updated"], leader=st["leader"], winner=st["winner"], n_words=n_words,
                   best_word=max(words, default=0), mean_word=sum(words) / max(len(words), 1),
                   presses_per_s=st["presses_per_s"], run_seconds=st.get("run_seconds", 0))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return out


class Handler(SimpleHTTPRequestHandler):
    runs: Path = PROJECT / "runs"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, fmt, *args):  # quiet
        pass

    # -- helpers ---------------------------------------------------------------------------
    def _json(self, obj, status=HTTPStatus.OK) -> None:
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        try:
            self._json(path.read_bytes())
        except FileNotFoundError:
            self._json({"error": "not yet"}, HTTPStatus.NOT_FOUND)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _room(self, name: str) -> Path:
        if not NAME.match(name):
            raise ValueError("bad room name")
        return self.runs / name

    # -- routes ----------------------------------------------------------------------------
    def do_GET(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            if parts[:1] != ["api"]:
                return super().do_GET()
            if parts == ["api", "flywire"]:
                return self._json(_flywire_json())
            if parts == ["api", "rooms"]:
                rooms = sorted((p for p in self.runs.glob("*/room-config.json")), key=lambda p: p.stat().st_mtime,
                               reverse=True)
                return self._json([_room_summary(p.parent) for p in rooms])
            room = self._room(parts[2])
            if parts[3:] == ["status"]:
                return self._file(room / "room.json")
            if len(parts) == 6 and parts[3] == "fly":
                fly = int(parts[4])
                if parts[5] == "live":
                    return self._file(fly_dir(room, fly) / "live.json")
                if parts[5] == "brain":
                    return self._file(fly_dir(room, fly) / "brain.json")
                if parts[5] == "paper":
                    q = dict(x.split("=", 1) for x in self.path.partition("?")[2].split("&") if "=" in x)
                    return self._json(self._paper(room, fly, before=int(q["before"]) if "before" in q else None,
                                                  size=min(int(q.get("size", 2400)), 200_000)))
                if parts[5] == "feelings":
                    return self._json(self._feelings(room, fly))
            self._json({"error": "no such route"}, HTTPStatus.NOT_FOUND)
        except (ValueError, IndexError) as e:
            self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            body = self._body()
            if parts == ["api", "rooms"]:
                return self._json(self._start(self._room(body["name"]), body, resume=False))
            room = self._room(parts[2])
            action = parts[3]
            if not (room / "room-config.json").exists():   # never create folders for unknown rooms
                return self._json({"error": f"no room called {room.name!r}"}, HTTPStatus.NOT_FOUND)
            if action == "load":
                return self._json(self._start(room, body, resume=True))
            if action == "stop":
                pid = _pid_alive(room)
                if pid:
                    os.kill(pid, signal.SIGTERM)  # the room checkpoints every fly, then exits
                return self._json({"stopping": bool(pid)})
            if action == "control":
                return self._json(set_control(room, speed=body.get("speed"), paused=body.get("paused"),
                                              watch=body.get("watch"), save=bool(body.get("save")),
                                              no_rest=body.get("no_rest")))
            self._json({"error": "no such route"}, HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
            self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            if len(parts) != 3 or parts[:2] != ["api", "rooms"]:
                return self._json({"error": "no such route"}, HTTPStatus.NOT_FOUND)
            room = self._room(parts[2])
            if room.resolve().parent != self.runs.resolve() or not (room / "room-config.json").exists():
                return self._json({"error": "no such room"}, HTTPStatus.NOT_FOUND)
            if _pid_alive(room):
                return self._json({"error": "stop the room before deleting it"}, HTTPStatus.CONFLICT)
            shutil.rmtree(room)
            (self.runs / f"{room.name}.log").unlink(missing_ok=True)
            return self._json({"deleted": room.name})
        except ValueError as e:
            self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

    # -- actions ---------------------------------------------------------------------------
    def _start(self, room: Path, body: dict, resume: bool) -> dict:
        if _pid_alive(room):
            return {"running": True, "name": room.name}
        if not resume and room.exists():
            raise ValueError(f"a room called {room.name!r} already exists; load it instead")
        speed = body.get("speed", "real")
        if speed not in ("real", "max"):
            raise ValueError("speed must be real or max")
        cmd = [sys.executable, "-m", "flyspeare.cli", "room", str(room), "--speed", speed]
        if resume:
            cmd.append("--resume")
        else:
            cmd += ["--flies", str(int(body.get("flies", 1)))]
        self.runs.mkdir(parents=True, exist_ok=True)
        log = open(self.runs / f"{room.name}.log", "ab")
        subprocess.Popen(cmd, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return {"started": True, "name": room.name, "cmd": " ".join(cmd[2:])}

    def _feelings(self, room: Path, fly: int) -> dict:
        from .feelings import read_feelings
        try:
            live = json.loads((fly_dir(room, fly) / "live.json").read_text())
        except FileNotFoundError:
            raise ValueError("start watching this fly first")
        words = [w.text for w in _text(str(room_text(room)))[1]]
        done = max(1, live["word"])
        usual = (live["total_attempts"] - live["attempts"]) / done   # its own average so far
        return read_feelings(live, words, usual)

    def _paper(self, room: Path, fly: int, before: int | None = None, size: int = 2400) -> dict:
        display, words = _text(str(room_text(room)))
        try:
            word = json.loads((fly_dir(room, fly) / "state.json").read_text())["word_idx"]
        except FileNotFoundError:
            word = 0
        try:  # the live feed is fresher than the last checkpoint
            word = max(word, json.loads((fly_dir(room, fly) / "live.json").read_text())["word"])
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        end = words[word - 1].end if word > 0 else 0
        nxt = words[word].start if word < len(words) else len(display)
        upto = end if before is None else max(0, min(before, end))
        start = max(0, upto - size)
        return {"word": word, "n_words": len(words), "start": start, "end": upto, "text": display[start:upto],
                "gap": display[end:nxt] if before is None else "",
                "next_word_display": display[nxt:words[word].end] if word < len(words) else ""}


def main(port: int = 8765, runs: str | None = None, open_browser: bool = True) -> None:
    if runs:
        Handler.runs = Path(runs).resolve()
    if not (WEB / "assets" / "fly.json").exists():
        from .export_fly import export
        print("exporting the NeuroMechFly body for the browser...")
        export()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"flyspeare viewer on {url}  (runs: {Handler.runs})\nCtrl-C closes the viewer; rooms keep running.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
