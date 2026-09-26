"""The fly's internal states: what builds up in it from constant pressing, failure and success.

Real flies carry internal states that integrate their recent history and change how they
behave. These are modelled as simple leaky integrators running on fly time (0.3 s a keypress),
updated after every attempt and saved in checkpoints, so a fly that has typed for days carries
days of history. They are read, not fed back into learning: they describe the fly; they do
not change what it types.

  fatigue         effort from every keypress, recovering only with rest (it never rests);
                  per leg too (each front leg covers half the keys)
  sleep_pressure  homeostatic sleep drive: builds with time awake, cleared only by sleep
                  (flies sleep at night; this one never does)
  stress          builds with punishment and failed words, relieved by success
  satisfaction    a surge when a whole word comes right, fading over fly-minutes
  helplessness    grows with effort that never brings reward (flies given inescapable shocks
                  show learned helplessness); a success eases it
  habituation     overlap of its real Kenyon-cell patterns from one try to the next: the same
                  situation over and over
  tone            running balance of dopamine: reward minus punishment per press
  hunger          time since food. Nobody feeds the model fly; a real fly starves in ~3 days
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .brain import FLY_SECONDS_PER_PRESS

LEFT_KEYS = set("qwertasdfgzxcv")

TAU_FATIGUE = 1800.0      # s of fly time to recover most effort
EFFORT = 0.0015           # per keypress; flat-out pressing settles near 0.9
TAU_SLEEP = 8 * 3600.0    # awake time for sleep drive to build
TAU_STRESS = 3600.0
STRESS_PER_FAIL = 0.02
TAU_JOY = 1200.0
TAU_TONE = 300.0          # keypresses
HELPLESS_PER_FAIL = 5e-5   # ~30% after 3 fly-hours of nothing but failure
TAU_HUNGER = 24 * 3600.0     # without meals (older rooms never eat)
TAU_HUNGER_MEAL = 10 * 3600.0  # since the last meal
TAU_SLEEP_CLEAR = 2.5 * 3600.0  # sleep drains sleep pressure


@dataclass
class InnerState:
    fatigue: float = 0.0
    leg_fatigue: dict = field(default_factory=lambda: {"L": 0.0, "R": 0.0})
    awake_s: float = 0.0
    sleep_pressure: float = 0.0
    stress: float = 0.0
    satisfaction: float = 0.0
    helplessness: float = 0.0
    habituation: float = 0.0
    tone: float = 0.0
    hunger: float = 0.0
    fails_since_win: int = 0
    wins: int = 0
    clock_s: float = 0.0        # fly time since it first sat down, awake and asleep
    since_meal_s: float = 0.0
    meals: int = 0
    nights: int = 0

    def attempt(self, typed: str, signals: list[float], correct: bool, kcs: np.ndarray | None,
                last_kcs: np.ndarray | None = None, dt: float | None = None) -> None:
        dt = len(typed) * FLY_SECONDS_PER_PRESS if dt is None else dt
        decay = lambda tau: math.exp(-dt / tau)

        # body: effort in, slow recovery out
        self.fatigue = self.fatigue * decay(TAU_FATIGUE)
        self.fatigue += (1 - self.fatigue) * (1 - (1 - EFFORT) ** len(typed))
        n_left = sum(map(LEFT_KEYS.__contains__, typed))
        for side, n in (("L", n_left), ("R", len(typed) - n_left)):
            f = self.leg_fatigue[side] * decay(TAU_FATIGUE)
            self.leg_fatigue[side] = f + (1 - f) * (1 - (1 - 2 * EFFORT) ** n)
        self.awake_s += dt
        self.clock_s += dt
        self.since_meal_s += dt
        self.sleep_pressure = 1 - (1 - self.sleep_pressure) * decay(TAU_SLEEP)
        self.hunger = 1 - math.exp(-self.since_meal_s / (TAU_HUNGER_MEAL if self.meals else TAU_HUNGER))

        # dopamine history
        if signals:   # the attempt's mean signal, blended in as len(signals) presses' worth
            mean = sum(signals) / len(signals)
            self.tone += (mean - self.tone) * (1 - (1 - 1 / TAU_TONE) ** len(signals))
        self.stress *= decay(TAU_STRESS)
        self.satisfaction *= decay(TAU_JOY)
        if correct:
            self.wins += 1
            self.fails_since_win = 0
            self.satisfaction += (1 - self.satisfaction) * 0.6
            self.stress *= 0.6
            self.helplessness *= 0.7
        else:
            self.fails_since_win += 1
            self.stress += (1 - self.stress) * STRESS_PER_FAIL
            self.helplessness += (1 - self.helplessness) * HELPLESS_PER_FAIL

        # sameness of the brain's own activity, try to try (sampled every 8th try: cheap, and
        # still its real Kenyon-cell patterns)
        self._n = getattr(self, "_n", 0) + 1
        if self._n % 8 == 0 and kcs is not None and last_kcs is not None and len(kcs):
            overlap = len(np.intersect1d(kcs, last_kcs, assume_unique=True)) / len(kcs)
            self.habituation += (overlap - self.habituation) * 0.15

    def sleep(self, seconds: float) -> None:
        """A night: sleep pressure drains, the body recovers, stress and old joy fade."""
        f = lambda tau: math.exp(-seconds / tau)
        self.sleep_pressure *= f(TAU_SLEEP_CLEAR)
        self.fatigue *= f(TAU_FATIGUE)
        self.leg_fatigue = {k: v * f(TAU_FATIGUE) for k, v in self.leg_fatigue.items()}
        self.stress *= f(TAU_STRESS)
        self.satisfaction *= f(TAU_JOY)
        self.clock_s += seconds
        self.since_meal_s += seconds
        self.nights += 1

    def rest(self, seconds: float) -> None:
        """Time off the keys that is not sleep (a meal): the body recovers a little, time passes."""
        f = math.exp(-seconds / TAU_FATIGUE)
        self.fatigue *= f
        self.leg_fatigue = {k: v * f for k, v in self.leg_fatigue.items()}
        self.clock_s += seconds
        self.since_meal_s += seconds

    def eat(self) -> None:
        self.since_meal_s = 0.0
        self.hunger = 0.0
        self.meals += 1

    def hour(self) -> float:
        """Its body clock: it first sat down at 8 am."""
        return (8 + self.clock_s / 3600) % 24

    def to_dict(self) -> dict:
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in asdict(self).items()}
        # (the sampling counter _n is not a field, so it is not saved: it only sets the cadence)

    @classmethod
    def from_dict(cls, d: dict) -> "InnerState":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        st = cls(**known)
        if "clock_s" not in d:            # saved before sleep and meals existed
            st.clock_s = st.awake_s
            st.since_meal_s = st.awake_s
        return st
