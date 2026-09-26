"""The typing loop: attempt, judge, dopamine, repeat until the word is right (spec §4, §6)."""
from __future__ import annotations

import csv
import json
import math
import os
import signal
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .brain import FLY_SECONDS_PER_PRESS, BrainConfig, make_brain
from .inner import InnerState
from .rules import ALPHABET, NEIGHBOURS, Rewards, score_attempt

PRESS_SECONDS = FLY_SECONDS_PER_PRESS
FORGET_EVERY = 256         # presses between applying forgetting (batched for speed)
KC_CACHE_MAX = 200_000     # entries; cleared when full so a long stall cannot eat memory
MEAL_S = 20 * 60           # a meal: 20 minutes of fly time off the keys
STREAM_MAX = 8000          # every recent attempt (letters only) for the viewer's real-pace mode
STALL_REPORTS = [10**k for k in range(3, 13)]  # 1k, 10k, 100k ... attempts on one word
CSV_FIELDS = ["index", "word", "attempts", "presses", "wall_s", "fly_s"]


@dataclass(frozen=True)
class RunConfig:
    seed: int = 0
    rewards: Rewards = field(default_factory=Rewards)
    brain: BrainConfig = field(default_factory=BrainConfig)
    checkpoint_words: int = 1000
    checkpoint_secs: float = 60.0   # stalls can last hours: checkpoint on time too
    recent_len: int = 2000          # attempts kept in full detail for the viewer
    stats_secs: float = 2.0
    csv_every: int = 1              # words per words.csv row (>1 sums blocks: a room of flies)
    life: bool = False              # sleep, meals, and internal states that change its behaviour
    start_hour: float = 8.0         # its body clock when it first sits down (8 am)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Runner:
    def __init__(self, words: list[str], run_dir: str | Path, cfg: RunConfig = RunConfig(),
                 *, resume: bool = False, quiet: bool = False):
        self.words, self.cfg, self.quiet = words, cfg, quiet
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.brain = make_brain(cfg.brain, seed=cfg.seed)
        self.rng = np.random.default_rng(cfg.seed + 1)
        self.recent: deque = deque(maxlen=cfg.recent_len)
        self.stream: deque = deque(maxlen=STREAM_MAX)   # (seq, word index, typed, correct)
        self.inner = InnerState()                        # what builds up in it (inner.py)
        self._last_kcs = None
        self.replay: deque = deque(maxlen=4000)          # today's rewarded moments, replayed in sleep
        self.events: deque = deque(maxlen=20)            # nights and meals, for the viewer
        self.slept_s = 0.0                               # fly seconds slept, read by the room's pacing
        self.rest_s = 0.0                                # fly seconds spent eating or asleep
        self.resting = None                              # [{"kind": "sleep"|"meal", "until": epoch}, ...], set by the room
        self.no_rest = False                             # kept from food and sleep, set by the room
        self._rested = False                             # a rest happened in this run() slice
        self.sim_rate = None                             # its fly-seconds per real second, set by the room

        self.word_idx = 0
        self.attempts = 0             # on the current word
        self.presses_on_word = 0
        self.context = ""             # committed text, last few chars
        self.totals = {"presses": 0, "wrong_presses": 0, "attempts": 0,
                       "worst_word": "", "worst_attempts": 0}
        self._word_started = time.monotonic()
        # (sensed window, position) -> (PNs, KCs): exactly what the brain's input depends on
        self._kc_cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
        self._kc_cache_disabled = False
        self._stop = False
        self._unforgotten = 0         # presses since forgetting was last applied
        self._block = {"attempts": 0, "presses": 0, "wall_s": 0.0}  # words.csv block so far
        self._last_ckpt = time.monotonic()

        self.inner.clock_s = (cfg.start_hour - 8.0) * 3600   # a fresh fly: its day starts at start_hour
        if resume and (self.dir / "state.json").exists():
            self._load()
        else:
            with open(self.dir / "words.csv", "w", newline="") as f:
                csv.writer(f).writerow(CSV_FIELDS)
            self._write_brain_json()

    # -- one attempt -----------------------------------------------------------------------
    def attempt(self) -> tuple[str, bool, list[float]]:
        target = self.words[self.word_idx]
        L = len(target)
        prefix, intended, traces, probs, pns_seen = "", "", [], [], []
        slip = self.cfg.rewards.slip
        # how it feels changes how it acts (life only): tiredness and lack of sleep make its
        # choices sloppier and its presses slower; hunger makes a sweet reward count for more
        noise, gain, press_s = 1.0, 1.0, FLY_SECONDS_PER_PRESS
        if self.cfg.life:
            i = self.inner
            noise = (1 + 0.25 * i.fatigue) * (1 + 0.5 * max(0.0, i.sleep_pressure - 0.5))
            gain = 0.6 + 0.8 * i.hunger
            press_s = FLY_SECONDS_PER_PRESS * (1 + 0.8 * i.fatigue)
        for _ in range(L):
            key = ((self.context + prefix)[-self.brain.cfg.ctx_len:], len(prefix))
            hit = None if self._kc_cache_disabled else self._kc_cache.get(key)
            if hit is None:
                pns = self.brain.encode(self.context, prefix, L)
                hit = (pns, self.brain.kcs(pns))
                if not self._kc_cache_disabled:
                    if len(self._kc_cache) >= KC_CACHE_MAX:
                        self._kc_cache.clear()
                    self._kc_cache[key] = hit
            pns, kcs = hit
            pns_seen.append(pns)
            p = self.brain.probs(kcs, noise)
            key = min(int(np.searchsorted(np.cumsum(p), self.rng.random())), len(ALPHABET) - 1)
            traces.append((kcs, key))
            probs.append(p)
            meant = ALPHABET[key]
            intended += meant
            if slip and self.rng.random() < slip:
                ns = NEIGHBOURS[meant]
                prefix += ns[int(self.rng.random() * len(ns))]
            else:
                prefix += meant
        correct, signals = score_attempt(prefix, target, self.cfg.rewards)
        q = self.cfg.rewards.hit_prob
        if q < 1 and not correct:
            signals = [s if s <= 0 or self.rng.random() < q else 0.0 for s in signals]
        self.brain.learn(traces, signals, gain)
        dt = L * press_s
        if self.cfg.life and not correct:           # helplessness: it stops and waits between tries
            dt += 2.0 * self.inner.helplessness
        self.inner.attempt(prefix, signals, correct, traces[0][0] if traces else None, self._last_kcs, dt=dt)
        self._last_kcs = traces[0][0] if traces else None
        self.totals["fly_s"] = self.totals.get("fly_s", 0.0) + dt
        self._unforgotten += dt
        if self._unforgotten >= FORGET_EVERY * PRESS_SECONDS:
            self.brain.elapse(self._unforgotten)
            self._unforgotten = 0
        if self.cfg.life:
            for tr, s in zip(traces, signals):
                if s > 0:
                    self.replay.append((tr[0], tr[1], s))
            self._day()

        self.attempts += 1
        self.presses_on_word += L
        self.totals["attempts"] += 1
        self.totals["presses"] += L
        if not correct:
            self.totals["wrong_presses"] += sum(a != b for a, b in zip(prefix, target))
        self.stream.append((self.totals["attempts"], self.word_idx, prefix, correct))
        self.recent.append({"seq": self.totals["attempts"], "word": self.word_idx, "target": target,
                            "typed": prefix, "intended": intended, "correct": correct,
                            "dopamine": signals, "kcs": [t[0] for t in traces], "pns": pns_seen,
                            "probs": probs})
        return prefix, correct, signals

    # -- a fly's day: meals at 8 am and 6 pm, sleep from 10 pm to 8 am -------------------------
    def _day(self) -> None:
        i = self.inner
        hour = i.hour()
        day = int((i.clock_s + 8 * 3600) // 86400)
        night = hour >= 22 or hour < 8
        if self.no_rest:
            # kept from food and sleep: what it misses is missed, not made up later (a night
            # skipped is its breakfast skipped too). Hunger and sleep pressure keep building.
            if hour >= 18 and getattr(self, "_dinner_day", -1) != day:
                self._dinner_day = day
                self._skip("dinner")
            night_id = int((i.clock_s + 10 * 3600) // 86400)    # 22:00 to 08:00 is one night
            if night and getattr(self, "_skipped_night", -1) != night_id:
                self._skipped_night = night_id
                self._skip("night")
            return
        if hour >= 18 and getattr(self, "_dinner_day", -1) != day:
            self._dinner_day = day
            self._meal("dinner")
        if night:
            self.sleep()

    def _skip(self, what: str) -> None:
        self.events.append({"type": "skip", "what": what, "seq": self.totals["attempts"], "clock_s": self.inner.clock_s})

    def _meal(self, which: str) -> None:
        """Twenty minutes of fly time off the keys, eating."""
        if self._unforgotten:
            self.brain.elapse(self._unforgotten)
            self._unforgotten = 0
        self.brain.elapse(MEAL_S)
        self.inner.rest(MEAL_S)
        self.inner.eat()
        self.totals["fly_s"] = self.totals.get("fly_s", 0.0) + MEAL_S
        self.rest_s += MEAL_S
        self._rested = True
        self.events.append({"type": "meal", "meal": which, "minutes": MEAL_S // 60,
                            "seq": self.totals["attempts"], "clock_s": self.inner.clock_s})

    def sleep(self) -> None:
        """Sleep until 8 am: replay the day's rewarded moments into long-term memory (as real
        flies consolidate memory in sleep), let time pass for every synapse, recover, then eat."""
        i = self.inner
        until8 = ((8 - i.hour()) % 24) * 3600 or 24 * 3600
        if self._unforgotten:
            self.brain.elapse(self._unforgotten)
            self._unforgotten = 0
        replayed = self.brain.consolidate(list(self.replay))
        self.replay.clear()
        self.brain.elapse(until8)
        i.sleep(until8)
        self.totals["fly_s"] = self.totals.get("fly_s", 0.0) + until8
        self.slept_s += until8
        self.rest_s += until8
        self._rested = True
        self.events.append({"type": "sleep", "hours": round(until8 / 3600, 2), "replayed": replayed,
                            "seq": self.totals["attempts"], "clock_s": i.clock_s})
        self._meal("breakfast")

    def p_word(self) -> float:
        """Probability the brain types the current word right in one go, as it stands now."""
        target = self.words[self.word_idx]
        p = 1.0
        for i, ch in enumerate(target):
            kcs = self.brain.kcs(self.brain.encode(self.context, target[:i], len(target)))
            p *= self.brain.probs(kcs)[ALPHABET.index(ch)]
        return p

    # -- the loop --------------------------------------------------------------------------
    def run(self, max_words: int | None = None, max_attempts: int | None = None) -> None:
        end = len(self.words) if max_words is None else min(max_words, len(self.words))
        last_stats = time.monotonic()
        attempts_this_call = 0
        old = old_term = None
        if not self.quiet:
            old = signal.signal(signal.SIGINT, self._on_sigint)
            old_term = signal.signal(signal.SIGTERM, self._on_sigint)
        try:
            self._rested = False
            while self.word_idx < end and not self._stop:
                if max_attempts is not None and attempts_this_call >= max_attempts:
                    break
                _, correct, _ = self.attempt()
                attempts_this_call += 1
                # in a room (sliced runs) stop when it goes to eat or sleep, so the room can
                # pause it for that long; a plain `flyspeare run` just carries on
                if self._rested and max_attempts is not None:
                    if correct:
                        self._commit_word()
                    break
                if self.attempts in STALL_REPORTS:
                    self._report_stall()
                if correct:
                    self._commit_word()
                    if self.word_idx % self.cfg.checkpoint_words == 0:
                        self.checkpoint()
                now = time.monotonic()
                if now - self._last_ckpt >= self.cfg.checkpoint_secs:
                    self.checkpoint()
                if not self.quiet and now - last_stats >= self.cfg.stats_secs:
                    self._print_stats()
                    last_stats = now
        finally:
            if old is not None:
                signal.signal(signal.SIGINT, old)
                signal.signal(signal.SIGTERM, old_term)
        if self._stop:
            self.checkpoint()
            self._say(f"\nstopped at word {self.word_idx:,} (attempt {self.attempts:,}); checkpoint saved")

    def _on_sigint(self, *_):
        self._stop = True  # finish the current attempt, then checkpoint

    def _commit_word(self) -> None:
        word = self.words[self.word_idx]
        wall = time.monotonic() - self._word_started
        b = self._block
        b["attempts"] += self.attempts
        b["presses"] += self.presses_on_word
        b["wall_s"] += wall
        if (self.word_idx + 1) % self.cfg.csv_every == 0 or self.word_idx + 1 == len(self.words):
            with open(self.dir / "words.csv", "a", newline="") as f:
                csv.writer(f).writerow([self.word_idx, word, b["attempts"], b["presses"],
                                        f"{b['wall_s']:.3f}", f"{b['presses'] * PRESS_SECONDS:.1f}"])
            self._block = {"attempts": 0, "presses": 0, "wall_s": 0.0}
        if self.attempts > self.totals["worst_attempts"]:
            self.totals["worst_word"], self.totals["worst_attempts"] = word, self.attempts
        self.context = (self.context + word + " ")[-self.cfg.brain.ctx_len:]
        self.word_idx += 1
        self.attempts = self.presses_on_word = 0
        self._kc_cache.clear()
        self._word_started = time.monotonic()

    # -- reporting -------------------------------------------------------------------------
    def _say(self, msg: str) -> None:
        if not self.quiet:
            print(msg, flush=True)

    def _report_stall(self) -> None:
        p = self.p_word()
        self._say(f"\nSTALL  '{self.words[self.word_idx]}' has taken {self.attempts:,} attempts; "
                  f"P(right next try)={p:.2e} (~{1 / p:,.0f} tries at this skill)")

    def _print_stats(self) -> None:
        t = self.totals
        elapsed = time.monotonic() - self._run_started if hasattr(self, "_run_started") else None
        self._run_started = getattr(self, "_run_started", time.monotonic())
        rate = t["presses"] / elapsed if elapsed else 0
        wrong = t["wrong_presses"] / max(t["presses"], 1)
        word = self.words[self.word_idx] if self.word_idx < len(self.words) else "-"
        print(f"\rword {self.word_idx:,}/{len(self.words):,} ({100 * self.word_idx / len(self.words):.3f}%)"
              f"  '{word}' try {self.attempts:,}  wrong-press {wrong:.0%}"
              f"  worst '{t['worst_word']}' {t['worst_attempts']:,}  {rate:,.0f} presses/s{self._eta(rate)}   ",
              end="", flush=True)

    def _eta(self, rate: float) -> str:
        if not rate or not self.word_idx:
            return ""
        left = (len(self.words) - self.word_idx) * self.totals["presses"] / self.word_idx / rate
        return f"  ETA {left / 86400:.1f} d" if left > 86400 else f"  ETA {left / 3600:.1f} h"

    # -- persistence -----------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.word_idx >= len(self.words)

    def checkpoint(self) -> None:
        self._last_ckpt = time.monotonic()
        buf = self.dir / "weights.npy"
        np.save(buf.with_suffix(".tmp.npy"), self.brain.w)
        os.replace(buf.with_suffix(".tmp.npy"), buf)
        state = {
            "word_idx": self.word_idx, "attempts": self.attempts,
            "presses_on_word": self.presses_on_word, "context": self.context,
            "unforgotten_s": self._unforgotten, "block": self._block, "inner": self.inner.to_dict(),
            "rest_s": self.rest_s,
            "events": list(self.events), "dinner_day": getattr(self, "_dinner_day", -1),
            "skipped_night": getattr(self, "_skipped_night", -1),
            "replay": [[k.tolist(), int(key), float(s)] for k, key, s in self.replay],
            "totals": self.totals, "rng": self.rng.bit_generator.state,
            "seed": self.cfg.seed, "brain": asdict(self.cfg.brain),
        }
        _atomic_write(self.dir / "state.json", json.dumps(state).encode())
        lines = [json.dumps(item) for item in self.live_items()]
        _atomic_write(self.dir / "recent.jsonl", ("\n".join(lines) + "\n").encode())

    def live_items(self, n: int | None = None) -> list[dict]:
        """The most recent attempts, JSON-ready: what the viewer replays."""
        items = list(self.recent)[-n:] if n else list(self.recent)
        return [{**it, "dopamine": [round(float(s), 4) for s in it["dopamine"]],
                 "kcs": [k.tolist() for k in it["kcs"]], "pns": [p.tolist() for p in it["pns"]],
                 "probs": [np.round(p, 4).tolist() for p in it["probs"]]} for it in items]

    def live_snapshot(self, n: int = 40) -> dict:
        return {"word": self.word_idx, "attempts": self.attempts, "presses": self.totals["presses"],
                "total_attempts": self.totals["attempts"], "finished": self.finished,
                "target": None if self.finished else self.words[self.word_idx],
                "items": self.live_items(n), "stream": self._stream_json(), "brain": self._brain_state(),
                "inner": self.inner.to_dict(), "events": list(self.events), "life": self.cfg.life,
                "asleep_until": self._resting_until("sleep"), "eating_until": self._resting_until("meal"),
                "rest_until": self._resting_until(None), "sim_rate": self.sim_rate, "no_rest": self.no_rest}

    def _resting_until(self, kind: str | None):
        """When its current or coming sleep / meal ends (None: when the whole rest ends)."""
        now = time.time()
        ahead = [p for p in self.resting or [] if p["until"] > now and kind in (None, p["kind"])]
        return ahead[-1]["until"] if ahead else None

    def _brain_state(self) -> dict:
        """How much dopamine has reshaped each memory store: 0 = untouched, 1 = fully depressed."""
        return self.brain.memory_state()

    def _stream_json(self) -> dict:
        """Every recent attempt, compactly: what real-pace mode plays at the true rate."""
        s = self.stream
        return {"first_seq": s[0][0] if s else 0, "last_seq": s[-1][0] if s else 0,
                "typed": [x[2] for x in s], "word": [x[1] for x in s],
                "correct": [i for i, x in enumerate(s) if x[3]]}

    def _load(self) -> None:
        state = json.loads((self.dir / "state.json").read_text())
        # a brain setting added since the checkpoint was saved ran at its default
        as_json = lambda b: json.loads(json.dumps(asdict(b)))
        saved = {**as_json(BrainConfig()), **state["brain"]}
        if state["seed"] != self.cfg.seed or saved != as_json(self.cfg.brain):
            raise ValueError("checkpoint was made with a different seed or brain config")
        self.brain.w = np.load(self.dir / "weights.npy")
        self.word_idx, self.attempts = state["word_idx"], state["attempts"]
        self.presses_on_word, self.context = state["presses_on_word"], state["context"]
        self.totals = state["totals"]
        # (older checkpoints counted unforgotten keypresses, not fly seconds)
        self._unforgotten = state.get("unforgotten_s", state.get("unforgotten", 0) * PRESS_SECONDS)
        self.events = deque(state.get("events", []), maxlen=20)
        self.rest_s = state.get("rest_s", 0.0)
        self._dinner_day = state.get("dinner_day", -1)
        self._skipped_night = state.get("skipped_night", -1)
        self.replay = deque(((np.array(k, dtype=np.int64), key, s) for k, key, s in state.get("replay", [])), maxlen=4000)
        self._block = state.get("block", self._block)
        if "inner" in state:
            self.inner = InnerState.from_dict(state["inner"])
        else:   # saved before inner states existed: seed what is known exactly from its history
            from .inner import HELPLESS_PER_FAIL
            self.inner = InnerState(awake_s=self.totals["presses"] * FLY_SECONDS_PER_PRESS,
                                    fails_since_win=self.attempts, wins=self.word_idx,
                                    helplessness=1 - (1 - HELPLESS_PER_FAIL) ** self.attempts)
        self.rng.bit_generator.state = state["rng"]
        # Drop words.csv rows written after the checkpoint (a crash between checkpoints).
        with open(self.dir / "words.csv", newline="") as f:
            kept = [r for r in csv.DictReader(f) if int(r["index"]) < self.word_idx]
        with open(self.dir / "words.csv", "w", newline="") as f:
            w = csv.DictWriter(f, CSV_FIELDS)
            w.writeheader()
            w.writerows(kept)

    def _write_brain_json(self) -> None:
        b = self.brain
        data = {"n_pn": b.n_pn, "n_kc": b.n_kc, "keys": ALPHABET, "wiring": b.cfg.wiring,
                "pn_to_kc": [np.flatnonzero(b.pn_to_kc[:, k]).tolist() for k in range(b.n_kc)]}
        if b.cfg.wiring == "flywire":
            from . import flywire
            fw = flywire.load()
            data["flywire"] = {
                "version": 783, "channel_to_pn": b.channel_to_pn.tolist(),
                "kc_root_ids": [str(x) for x in fw["kc_ids"]], "kc_type": fw["kc_type"].tolist(),
                "kc_pos": fw["kc_pos"].round().tolist(),
                "pn_root_ids": [str(x) for x in fw["pn_ids"]], "pn_pos": fw["pn_pos"].round().tolist(),
                "dan_type": fw["dan_type"].tolist(), "dan_pos": fw["dan_pos"].round().tolist(),
                "mbon_type": fw["mbon_type"].tolist(), "mbon_pos": fw["mbon_pos"].round().tolist(),
            }
        _atomic_write(self.dir / "brain.json", json.dumps(data).encode())
