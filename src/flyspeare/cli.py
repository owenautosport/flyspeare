"""flyspeare run | report."""
from __future__ import annotations

import argparse
import time
import csv
import json
import urllib.request
from pathlib import Path

from dataclasses import replace

from .brain import LONG_TERM, SHORT_TERM, BrainConfig
from .rules import Rewards
from .room import Room, RoomConfig, leaderboard, load_room_config, read_status, room_text, set_control
from .run import RunConfig, Runner
from .text import GUTENBERG_URL, load

# The realistic fly, calibrated 2026-09-25 so one fly at max speed takes about a week on an
# M4 Pro (~80x the easy fly, which takes ~2.1 h). Every limit is a real fly's, none is sabotage:
SPAN = 4           # working memory: the last 4 keypresses
TAU = 0.2          # choice noise: a fully learned key is chosen ~83% of the time, like a trained fly
STM_ETA = 0.09     # one brief dopamine pulse only nudges a synapse (a real trial is a minute of pairings)
# Recalibrated 2026-09-25 for the real FlyWire wiring and depression-only dopamine
# (eta 0.065 -> 126x, 0.10 -> 69x the easy fly on the opening words; 0.09 ~ 80x ~ 7 days).
# No length cue: the fly only learns a word is over when the bell rings.
# Optional extra handicaps, off by default: unreliable dopamine and slipping feet.
HIT_PROB, SLIP = 1.0, 0.0


# The real-MBON fly (the default since 2026-09-26), calibrated the same way: about 32x the easy
# fly's effort on the opening words at 15,550 keys/s, so about 7 days. Choice noise is the lever
# (0.16 -> 21x, 0.18 -> 32x, 0.20 -> ~570x); a fully learned key is then chosen ~93% of the time.
MBON_TAU, MBON_ETA = 0.18, 0.25


def _brain(a) -> BrainConfig:
    if a.easy:
        return BrainConfig()
    mbon = a.output == "mbon"
    tau = a.tau if a.tau is not None else (MBON_TAU if mbon else TAU)
    eta = a.stm_eta if a.stm_eta is not None else (MBON_ETA if mbon else STM_ETA)
    return BrainConfig(wiring=a.wiring, output=a.output, ctx_len=a.span, tau=tau, length_cue=a.length_cue,
                       compartments=(replace(SHORT_TERM, eta=eta), LONG_TERM))


def _words(text_path: Path) -> list[str]:
    if not text_path.exists():
        text_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {GUTENBERG_URL}")
        urllib.request.urlretrieve(GUTENBERG_URL, text_path)
    return [w.text for w in load(text_path)[1]]


def cmd_run(a) -> None:
    words = _words(Path(a.text))
    cfg = RunConfig(seed=a.seed, brain=replace(_brain(a), eta=0.0 if a.frozen else 1.0), life=not a.no_life and not a.easy,
                    rewards=Rewards(letter=a.letter, punish=a.punish, feedback=a.feedback,
                                    hit_prob=a.hit_prob, slip=a.slip))
    r = Runner(words, a.run_dir, cfg, resume=a.resume)
    print(f"{len(words):,} words of Shakespeare; starting at word {r.word_idx:,}"
          f" ('{words[r.word_idx]}', attempt {r.attempts:,}). Ctrl-C checkpoints and stops.")
    r.run(max_words=a.max_words)
    r.checkpoint()
    print()
    report(Path(a.run_dir))


def report(run_dir: Path) -> None:
    with open(run_dir / "words.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    state = json.loads((run_dir / "state.json").read_text())
    if not rows:
        print("no words completed yet")
    else:
        att = [int(r["attempts"]) for r in rows]
        presses = sum(int(r["presses"]) for r in rows) + state["presses_on_word"]
        wall = sum(float(r["wall_s"]) for r in rows)
        print(f"words completed: {len(rows):,}   attempts: {sum(att):,}   presses: {presses:,}")
        print(f"speed: {sum(int(r['presses']) for r in rows) / max(wall, 1e-9):,.0f} presses/s"
              f"   fly time at 0.3 s/press: {presses * 0.3 / 86400:,.1f} days")
        print("\nmean attempts per word, by stretch of text:")
        n = max(1, len(att) // 10)
        for i in range(0, len(att), n):
            chunk = att[i:i + n]
            print(f"  words {i:>7,}-{i + len(chunk) - 1:<7,} {sum(chunk) / len(chunk):>12,.1f}")
        print("\nattempts needed:")
        for lo, hi in [(1, 1), (2, 10), (11, 100), (101, 1000), (1001, 10**4), (10**4 + 1, 10**5),
                       (10**5 + 1, 10**6), (10**6 + 1, 10**12)]:
            c = sum(lo <= x <= hi for x in att)
            if c:
                print(f"  {lo:>9,}-{hi:<14,} {c:>7,} words")
        print("\nhardest words:")
        for r in sorted(rows, key=lambda r: -int(r["attempts"]))[:10]:
            print(f"  {r['word']:<18} {int(r['attempts']):>12,} attempts  ({float(r['wall_s']):,.1f} s)")
    if state["attempts"]:
        print(f"\nin progress: word {state['word_idx']:,} after {state['attempts']:,} attempts")


def cmd_room(a) -> None:
    import os
    room_dir = Path(a.room_dir)
    workers = a.workers or RoomConfig().workers
    if a.resume and (room_dir / "room-config.json").exists():
        # load exactly the settings the room was created with; only speed may change
        text = room_text(room_dir)
        cfg = load_room_config(room_dir, speed=a.speed, resume=True, workers=workers)
    else:
        text = Path(a.text)
        cfg = RoomConfig(flies=a.flies, speed=a.speed, seed=a.seed, resume=a.resume, brain=_brain(a),
                         life=not a.no_life and not a.easy,
                         rewards=Rewards(hit_prob=a.hit_prob, slip=a.slip), workers=workers)
    n_words = len(_words(text))
    room_dir.mkdir(parents=True, exist_ok=True)
    (room_dir / "room.pid").write_text(str(os.getpid()))
    set_control(room_dir, paused=False)
    print(f"{cfg.flies:,} flies, each typing all {n_words:,} words of Shakespeare, {cfg.workers} workers, "
          f"speed={cfg.speed}.\nControl it live from another terminal:\n"
          f"  flyspeare ctl {a.room_dir} --speed max|real   /  --pause  /  --go\n"
          f"  flyspeare status {a.room_dir}\nCtrl-C checkpoints every fly and stops.")
    room = Room(text, a.room_dir, cfg)
    import signal, threading

    def _stop(*_):
        print("\nstopping: checkpointing every fly...", flush=True)
        room.stop()
    # Background launches inherit SIGINT=ignored; install handlers so Ctrl-C, `kill -INT`
    # and `kill` (SIGTERM, the viewer's Stop button) all checkpoint every fly before exiting.
    # The room runs in this main thread, so it always waits for its workers to finish saving.
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def _print_leaderboard():
        while True:
            time.sleep(5)
            try:
                print("\n" + leaderboard(read_status(a.room_dir), n_words), flush=True)
            except (FileNotFoundError, ValueError):
                pass
    threading.Thread(target=_print_leaderboard, daemon=True).start()
    room.run()
    (room_dir / "room.pid").unlink(missing_ok=True)
    st = read_status(a.room_dir)
    if all(f["done"] for f in st["flies"]):
        print(f"finished. Winner: fly {st['winner']}.")
    else:
        print("stopped. Resume with the same command plus --resume.")


def cmd_ctl(a) -> None:
    paused = True if a.pause else False if a.go else None
    print(set_control(Path(a.room_dir), speed=a.speed, paused=paused))


def cmd_status(a) -> None:
    st = read_status(a.room_dir)
    cfg = json.loads((Path(a.room_dir) / "room-config.json").read_text())
    n_words = len(_words(Path(cfg["text"])))
    print(leaderboard(st, n_words, top=a.top))


def _difficulty_args(p) -> None:
    p.add_argument("--easy", action="store_true", help="the original easy fly (~2 h at max speed)")
    p.add_argument("--wiring", choices=["flywire", "random"], default="flywire",
                   help="flywire: the real PN->KC connectome (default); random: same statistics")
    p.add_argument("--output", choices=["mbon", "per_key"], default="mbon",
                   help="mbon: the real FlyWire MBON types (default); per_key: the older invented units")
    p.add_argument("--no-life", action="store_true", help="no sleep, meals or state-driven behaviour")
    p.add_argument("--span", type=int, default=SPAN, help=f"working memory in keypresses (default {SPAN})")
    p.add_argument("--tau", type=float, default=None,
                   help=f"choice noise (default {MBON_TAU} for the MBON brain, {TAU} for per_key; lower = surer)")
    p.add_argument("--stm-eta", type=float, default=None,
                   help=f"learning per dopamine pulse (default {MBON_ETA} MBON, {STM_ETA} per_key; higher = easier)")
    p.add_argument("--length-cue", action="store_true", help="tell the fly each word's length in advance")
    p.add_argument("--hit-prob", type=float, default=HIT_PROB,
                   help=f"chance each small dopamine hit reaches the brain (default {HIT_PROB})")
    p.add_argument("--slip", type=float, default=SLIP,
                   help=f"chance a foot slips onto a neighbouring key (default {SLIP})")


def main() -> None:
    p = argparse.ArgumentParser(prog="flyspeare")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="make the fly type Shakespeare")
    r.add_argument("run_dir")
    r.add_argument("--text", default="data/pg100.txt")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--max-words", type=int)
    r.add_argument("--resume", action="store_true")
    r.add_argument("--frozen", action="store_true", help="no plasticity: the no-learning baseline")
    r.add_argument("--feedback", choices=["membership", "position"], default="position",
                   help="small hit for a letter anywhere in the word, or only in the right place")
    r.add_argument("--letter", type=float, default=0.1, help="small-hit size")
    r.add_argument("--punish", type=float, default=0.05, help="punishment for a letter with no small hit")
    _difficulty_args(r)
    r.set_defaults(fn=cmd_run)
    rm = sub.add_parser("room", help="a room of flies racing to type all of Shakespeare")
    rm.add_argument("room_dir")
    rm.add_argument("--flies", type=int, default=1000)
    rm.add_argument("--speed", choices=["real", "max"], default="real",
                    help="real: 0.3 s per keypress per fly; max: as fast as the CPU allows")
    rm.add_argument("--workers", type=int, help="processes (default: CPU cores - 2)")
    rm.add_argument("--text", default="data/pg100.txt")
    rm.add_argument("--seed", type=int, default=0)
    rm.add_argument("--resume", action="store_true")
    _difficulty_args(rm)
    rm.set_defaults(fn=cmd_room)
    c = sub.add_parser("ctl", help="change a running room: speed, pause, go")
    c.add_argument("room_dir")
    c.add_argument("--speed", choices=["real", "max"])
    c.add_argument("--pause", action="store_true")
    c.add_argument("--go", action="store_true")
    c.set_defaults(fn=cmd_ctl)
    stt = sub.add_parser("status", help="leaderboard of a room")
    stt.add_argument("room_dir")
    stt.add_argument("--top", type=int, default=10)
    stt.set_defaults(fn=cmd_status)
    v = sub.add_parser("view", help="open the 9:16 viewer in your browser")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--runs", default="runs")
    v.add_argument("--no-browser", action="store_true")
    v.set_defaults(fn=lambda a: __import__("flyspeare.view", fromlist=["main"]).main(
        a.port, a.runs, not a.no_browser))
    rep = sub.add_parser("report", help="summarise a run")
    rep.add_argument("run_dir")
    rep.set_defaults(fn=lambda a: report(Path(a.run_dir)))
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
