import numpy as np

from flyspeare.inner import InnerState

KCS = np.arange(100)


def press_for(inner, seconds, word_right_every=None, hits=0):
    """Type flat out (0.3 s a key) for `seconds` of fly time in 5-letter tries."""
    n = int(seconds / 1.5)
    for i in range(n):
        right = bool(word_right_every) and i % word_right_every == 0
        inner.attempt("abcde", signals=[1.0] * 5 if right else [0.1] * hits + [-0.05] * (5 - hits),
                      correct=right, kcs=KCS, last_kcs=KCS)


def test_fatigue_builds_with_constant_pressing_and_saturates():
    s = InnerState()
    press_for(s, 60)
    early = s.fatigue
    press_for(s, 4 * 3600)
    assert 0.15 < early < 0.35 and 0.85 < s.fatigue < 0.95   # ~3 min to tire, settles near 90%
    assert s.leg_fatigue["L"] > 0.5 and s.leg_fatigue["R"] > 0.5


def test_sleep_pressure_only_grows_awake():
    s = InnerState()
    press_for(s, 3600)
    one_hour = s.sleep_pressure
    press_for(s, 15 * 3600)
    assert 0.05 < one_hour < 0.2 and s.sleep_pressure > 0.85


def test_failure_builds_stress_and_helplessness_success_relieves_them():
    s = InnerState()
    press_for(s, 3 * 3600)                 # nothing but failure
    stressed, helpless = s.stress, s.helplessness
    assert stressed > 0.6 and helpless > 0.1 and s.satisfaction < 0.01
    s.attempt("abcde", signals=[1.0] * 5, correct=True, kcs=KCS, last_kcs=KCS)
    assert s.satisfaction > 0.4 and s.stress < stressed and s.helplessness < helpless


def test_same_brain_pattern_over_and_over_habituates():
    s = InnerState()
    press_for(s, 600)
    assert s.habituation > 0.9


def test_state_round_trips_for_checkpoints():
    s = InnerState()
    press_for(s, 900, word_right_every=50, hits=2)
    t = InnerState.from_dict(s.to_dict())
    assert t.to_dict() == s.to_dict()
