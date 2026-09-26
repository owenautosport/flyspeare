"""A room full of flies at typewriters: the infinite-monkey race (every fly types everything).

Each fly has its own brain (its own random wiring) and its own run directory, so any fly can
be inspected or resumed on its own. Flies are shared out between worker processes. A small
control file in the room directory is read live, so speed can be switched and the room paused
while it runs:

  control.json  {"speed": "real" | "max", "paused": false, "watch": [fly ids], "save": n}

watch: flies whose recent attempts are streamed to fly-XXXX/live.json for the viewer.
save:  a counter; bumping it makes every worker checkpoint all its flies now.

real: each fly presses one key per `press_seconds` (0.3 s, a fly walking to a key).
max:  every fly types as fast as the CPU allows.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import signal
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .brain import FLY_SECONDS_PER_PRESS, BrainConfig, Compartment
from .run import RunConfig, Runner, _atomic_write
from .rules import Rewards
from .text import load


@dataclass(frozen=True)
class RoomConfig:
    flies: int = 1000
    workers: int = max(1, (os.cpu_count() or 2) - 2)
    speed: str = "real"                     # starting speed; change live with set_control
    press_seconds: float = FLY_SECONDS_PER_PRESS
    seed: int = 0
    resume: bool = False
    rewards: Rewards = field(default_factory=Rewards)
    brain: BrainConfig = field(default_factory=BrainConfig)
    life: bool = False                      # sleep, meals, and states that change behaviour
    status_secs: float = 2.0
    max_slice: int = 200                    # attempts per fly per turn at max speed
    checkpoint_secs: float = 300.0          # every 5 minutes: a crash loses at most that
    recent_len: int = 100
    csv_every: int = 1000
    live_secs: float = 0.25                # how often watched flies' live.json is rewritten
    verbose: bool = False

    def run_config(self, fly: int) -> RunConfig:
        # big rooms write ~1 MB per fly per save: every 15 min for them, 5 min otherwise
        every = self.checkpoint_secs if self.flies <= 50 else max(self.checkpoint_secs, 900.0)
        return RunConfig(seed=self.seed + 2 * fly, rewards=self.rewards, brain=self.brain, life=self.life,
                         checkpoint_words=10**12, checkpoint_secs=every,
                         recent_len=self.recent_len, csv_every=self.csv_every)


# -- control and status files ------------------------------------------------------------------
_CONTROL_DEFAULTS = {"speed": "real", "paused": False, "watch": [], "save": 0}


def read_control(room_dir: Path) -> dict:
    try:
        return {**_CONTROL_DEFAULTS, **json.loads((Path(room_dir) / "control.json").read_text())}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_CONTROL_DEFAULTS)


def set_control(room_dir: Path, *, speed: str | None = None, paused: bool | None = None,
                watch: list[int] | None = None, save: bool = False) -> dict:
    room_dir = Path(room_dir)
    room_dir.mkdir(parents=True, exist_ok=True)
    ctl = read_control(room_dir)
    if speed is not None:
        if speed not in ("real", "max"):
            raise ValueError("speed must be 'real' or 'max'")
        ctl["speed"] = speed
    if paused is not None:
        ctl["paused"] = paused
    if watch is not None:
        ctl["watch"] = [int(i) for i in watch]
    if save:
        ctl["save"] = int(ctl["save"]) + 1
    _atomic_write(room_dir / "control.json", json.dumps(ctl).encode())
    return ctl


def save_room_config(room_dir: Path, cfg: RoomConfig, text_path: Path) -> None:
    data = {"flies": cfg.flies, "seed": cfg.seed, "text": str(text_path),
            "brain": asdict(cfg.brain), "rewards": asdict(cfg.rewards), "life": cfg.life, "created": time.time()}
    _atomic_write(Path(room_dir) / "room-config.json", json.dumps(data, indent=1).encode())


def load_room_config(room_dir: Path, **overrides) -> RoomConfig:
    """The settings a room was created with, so it can be loaded again exactly."""
    d = json.loads((Path(room_dir) / "room-config.json").read_text())
    b = dict(d["brain"])
    b["compartments"] = tuple(Compartment(**c) for c in b["compartments"])
    b["claws"] = tuple(b["claws"])
    return RoomConfig(flies=d["flies"], seed=d["seed"], brain=BrainConfig(**b),
                      rewards=Rewards(**d["rewards"]), life=d.get("life", False), **overrides)


def room_text(room_dir: Path) -> Path:
    return Path(json.loads((Path(room_dir) / "room-config.json").read_text())["text"])


def read_status(room_dir: Path) -> dict:
    return json.loads((Path(room_dir) / "room.json").read_text())


def fly_dir(room_dir: Path, fly: int) -> Path:
    return Path(room_dir) / f"fly-{fly:04d}"


def _fly_status(i: int, r: Runner) -> dict:
    t = r.totals
    return {"id": i, "word": r.word_idx, "target": r.words[r.word_idx] if not r.finished else None,
            "attempts": r.attempts, "presses": t["presses"],
            "wrong_rate": round(t["wrong_presses"] / max(t["presses"], 1), 4),
            "fly_days": round(t["presses"] * FLY_SECONDS_PER_PRESS / 86400, 3),
            "done": r.finished, "finished_at": t.get("finished_at")}


# -- a worker: owns some flies, schedules their keypresses -------------------------------------
def _work(text_path, room_dir, ids, cfg: RoomConfig, stop, k: int) -> None:
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # the room process handles Ctrl-C
    room_dir = Path(room_dir)
    words = [w.text for w in load(text_path)[1]]
    flies = {i: Runner(words, fly_dir(room_dir, i), cfg.run_config(i), resume=cfg.resume, quiet=True)
             for i in ids}
    rnd = random.Random(cfg.seed + k)
    now = time.monotonic()
    ready = {i: now + rnd.random() * cfg.press_seconds for i in ids}  # not all in lockstep
    status_path = room_dir / "status" / f"worker-{k:03d}.json"
    status_path.parent.mkdir(exist_ok=True)
    last_status = last_ctl = last_live = 0.0
    ctl = read_control(room_dir)
    saved_seq = ctl["save"]

    def write_status():
        _atomic_write(status_path, json.dumps([_fly_status(i, r) for i, r in flies.items()]).encode())

    def write_live():
        for i in ctl["watch"]:
            if i in flies:
                _atomic_write(fly_dir(room_dir, i) / "live.json",
                              json.dumps({"id": i, "time": time.time(), **flies[i].live_snapshot()}).encode())

    def mark_finished(r: Runner):
        if r.finished and "finished_at" not in r.totals:
            r.totals["finished_at"] = time.time()
            r.checkpoint()

    while not stop.is_set():
        now = time.monotonic()
        if now - last_ctl >= 0.2:
            ctl, last_ctl = read_control(room_dir), now
            if ctl["save"] != saved_seq:
                for r in flies.values():
                    r.checkpoint()
                saved_seq = ctl["save"]
                write_status()
        if ctl["watch"] and now - last_live >= cfg.live_secs:
            write_live()
            last_live = now
        if now - last_status >= cfg.status_secs:
            write_status()
            last_status = now
        active = [i for i, r in flies.items() if not r.finished]
        if not active:
            break
        if ctl["paused"]:
            time.sleep(0.05)
            for i in active:
                ready[i] = time.monotonic()
            continue
        if ctl["speed"] == "max":
            for i in active:
                if stop.is_set():
                    break
                flies[i].run(max_attempts=cfg.max_slice)
                mark_finished(flies[i])
                ready[i] = time.monotonic()
            continue
        # real speed: a fly that has finished its last attempt is busy for L presses of fly time
        for i in active:
            if ready[i] <= now:
                r = flies[i]
                # pace by fly time: tired presses take longer, a night takes the whole night
                before = r.totals.get("fly_s", r.totals["presses"] * FLY_SECONDS_PER_PRESS)
                slept = r.slept_s
                r.run(max_attempts=1)
                mark_finished(r)
                spent = r.totals.get("fly_s", r.totals["presses"] * FLY_SECONDS_PER_PRESS) - before
                wall = spent * cfg.press_seconds / FLY_SECONDS_PER_PRESS
                ready[i] = max(ready[i], now - cfg.press_seconds) + wall
                if r.slept_s > slept:
                    r.asleep_until = time.time() + (r.slept_s - slept) * cfg.press_seconds / FLY_SECONDS_PER_PRESS
        soonest = min((ready[i] for i in active), default=now)
        time.sleep(min(max(soonest - time.monotonic(), 0.0), 0.05))

    for r in flies.values():
        r.checkpoint()
    write_status()
    write_live()


# -- the room ----------------------------------------------------------------------------------
class Room:
    def __init__(self, text_path, room_dir, cfg: RoomConfig = RoomConfig()):
        self.text_path, self.dir, self.cfg = Path(text_path), Path(room_dir), cfg
        self.dir.mkdir(parents=True, exist_ok=True)
        self._stop = None
        self._history: list[tuple[float, int]] = []  # (time, total presses) for a smoothed rate
        # training time, counting only while running and not paused; carried over on resume
        self._run_seconds = 0.0
        self._run_mark = None
        if cfg.resume:
            try:
                st = read_status(self.dir)
                self._run_seconds = float(st["run_seconds"]) if "run_seconds" in st else self._estimate_run_time(st)
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                pass

    def _estimate_run_time(self, st: dict) -> float:
        """Rooms saved before training time was tracked: estimate it from what was recorded.
        Flies run side by side, so it is the longest any one fly has been typing: the wall time
        in its words.csv, or, for a room that ran at real fly speed, its keypresses x 0.3 s."""
        import csv
        best = 0.0
        for f in st.get("flies", []):
            try:
                with open(fly_dir(self.dir, f["id"]) / "words.csv", newline="") as fh:
                    wall = sum(float(r["wall_s"]) for r in csv.DictReader(fh))
            except (FileNotFoundError, KeyError, ValueError):
                wall = 0.0
            if st.get("speed") == "real":
                wall = max(wall, f["presses"] * FLY_SECONDS_PER_PRESS)
            best = max(best, wall)
        return best

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def run(self) -> None:
        cfg = self.cfg
        set_control(self.dir, speed=cfg.speed)
        save_room_config(self.dir, cfg, self.text_path)
        n_workers = max(1, min(cfg.workers, cfg.flies))
        groups = [list(range(k, cfg.flies, n_workers)) for k in range(n_workers)]
        if n_workers == 1:
            self._stop = threading.Event()
            # explicitly not a daemon: it must finish checkpointing even if its parent is one
            procs = [threading.Thread(target=_work, args=(self.text_path, self.dir, groups[0], cfg, self._stop, 0),
                                      daemon=False)]
        else:
            ctx = mp.get_context("spawn")
            self._stop = ctx.Event()
            procs = [ctx.Process(target=_work, args=(self.text_path, self.dir, g, cfg, self._stop, k))
                     for k, g in enumerate(groups)]
        for p in procs:
            p.start()
        try:
            while any(p.is_alive() for p in procs):
                time.sleep(cfg.status_secs)
                self._aggregate()
        except KeyboardInterrupt:
            print("\nstopping: checkpointing every fly...")
            self._stop.set()
        for p in procs:
            while p.is_alive():  # a second Ctrl-C must not abandon the save
                try:
                    p.join()
                except KeyboardInterrupt:
                    self._stop.set()
        self._aggregate()

    def _aggregate(self) -> dict:
        flies = []
        for f in sorted((self.dir / "status").glob("worker-*.json")):
            try:
                flies += json.loads(f.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                continue
        flies.sort(key=lambda f: f["id"])
        total = sum(f["presses"] for f in flies)
        now = time.monotonic()
        self._history = [(t, p) for t, p in self._history if now - t <= 30] + [(now, total)]
        t0, p0 = self._history[0]
        rate = (total - p0) / (now - t0) if now - t0 > 1 else 0.0  # keys/s over the last 30 s
        done = [f for f in flies if f["done"] and f.get("finished_at")]
        ctl = read_control(self.dir)
        if self._run_mark is not None and not ctl["paused"]:
            self._run_seconds += now - self._run_mark
        self._run_mark = now
        status = {
            "updated": time.time(), "speed": ctl["speed"], "paused": ctl["paused"],
            "total_presses": total, "presses_per_s": round(rate, 1),
            "run_seconds": round(self._run_seconds, 1),
            "leader": max(flies, key=lambda f: (f["word"], -f["presses"]))["id"] if flies else None,
            # fewest keypresses = first to finish in fly time, fair at either speed
            "winner": min(done, key=lambda f: f["presses"])["id"] if done else None,
            "flies": flies,
        }
        _atomic_write(self.dir / "room.json", json.dumps(status).encode())
        if self.cfg.verbose and flies:
            print(leaderboard(status, n_words=None), flush=True)
        return status


def leaderboard(status: dict, n_words: int | None, top: int = 5) -> str:
    flies = status["flies"]
    ranked = sorted(flies, key=lambda f: (-f["word"], f["presses"]))[:top]
    mean = sum(f["word"] for f in flies) / max(len(flies), 1)
    of = f"/{n_words:,}" if n_words else ""
    lines = [f"[{status['speed']}{' PAUSED' if status['paused'] else ''}] {len(flies):,} flies  "
             f"mean word {mean:,.0f}{of}  {status['presses_per_s']:,.0f} presses/s"
             + (f"  WINNER fly {status['winner']}" if status["winner"] is not None else "")]
    for rank, f in enumerate(ranked, 1):
        tgt = f"'{f['target']}' try {f['attempts']:,}" if f["target"] else "DONE"
        lines.append(f"  {rank}. fly {f['id']:>4}  word {f['word']:>9,}{of}  {tgt}  "
                     f"wrong {f['wrong_rate']:.0%}  fly-time {f['fly_days']:.1f} d")
    return "\n".join(lines)
