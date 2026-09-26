"""The real MBON output layer, and a fly's day: sleep, meals, and states that change behaviour."""
import numpy as np

from flyspeare.brain import BrainConfig, make_brain
from flyspeare.run import RunConfig, Runner

VERSE = "to be or not to be".split()


def mb(**kw):
    return make_brain(BrainConfig(wiring="flywire", ctx_len=4, output="mbon", **kw), seed=0)


def test_output_layer_is_the_real_mbon_types():
    b = mb()
    assert b.n_units >= 25 and "MBON22" not in b.unit_names          # calyx MBON: no dopamine
    assert set(b.unit_dan) == {"PAM", "PPL1"}
    lobe = dict(zip(b.unit_names, b.unit_lobe))
    assert lobe["MBON07"] == "ab" and lobe["MBON11"] == "gamma" and lobe["MBON13"] == "apbp"  # a1, g1, a'2


def test_reward_only_depresses_pam_compartments_and_favours_the_key():
    b = mb()
    kcs = b.kcs(b.encode("the ", "", 3))
    before, p0 = b.w.copy(), b.probs(kcs)[4]
    b.learn([(kcs, 4)], [1.0])
    changed = np.flatnonzero((b.w != before).any(axis=1))
    assert len(changed) and b.e_pam[changed].all() and (b.w <= before).all()
    assert b.probs(kcs)[4] > p0


def test_punishment_only_depresses_ppl1_compartments_and_disfavours_the_key():
    b = mb()
    kcs = b.kcs(b.encode("the ", "", 3))
    before, p0 = b.w.copy(), b.probs(kcs)[4]
    b.learn([(kcs, 4)], [-0.05])
    changed = np.flatnonzero((b.w != before).any(axis=1))
    assert len(changed) and (~b.e_pam[changed]).all()
    assert b.probs(kcs)[4] < p0


def test_short_term_fades_long_term_stays():
    b = mb()
    kcs = b.kcs(b.encode("the ", "", 3))
    b.learn([(kcs, 4)], [1.0])
    lobe = b.unit_lobe[b.e_unit]
    dep = lambda l: (b.cfg.w0 - b.w[lobe == l, 4]).sum()
    g0, ab0 = dep("gamma"), dep("ab")
    b.elapse(8 * 3600)
    assert dep("gamma") < 0.01 * g0 and dep("ab") > 0.9 * ab0


def life_runner(tmp_path, words=None):
    cfg = RunConfig(seed=0, life=True, brain=BrainConfig(wiring="flywire", ctx_len=4, output="mbon"))
    return Runner(words or VERSE * 400, tmp_path / "life", cfg, quiet=True)


def test_it_sleeps_at_night_and_replays_its_day(tmp_path):
    r = life_runner(tmp_path)
    while r.inner.nights == 0:
        r.attempt()
        if r.attempts == 0 or r.inner.hour() > 21.99:
            pass
    ev = [e for e in r.events if e["type"] == "sleep"]
    assert ev and ev[0]["hours"] > 9 and ev[0]["replayed"] > 0
    assert 8 <= r.inner.hour() < 8.1                    # woke at 8 am
    assert r.inner.sleep_pressure < 0.1 and r.inner.hunger == 0.0   # rested, breakfast
    assert [e["meal"] for e in r.events if e["type"] == "meal"] == ["dinner", "breakfast"]


def test_tiredness_slows_its_presses(tmp_path):
    r = life_runner(tmp_path)
    r.attempt(); fresh = r.totals["fly_s"]
    r.inner.fatigue = 1.0
    before = r.totals["fly_s"]; r.attempt()
    tired = r.totals["fly_s"] - before
    assert tired > fresh * 1.5


def test_life_state_survives_a_checkpoint(tmp_path):
    r = life_runner(tmp_path)
    while r.inner.nights == 0:
        r.attempt()
    for _ in range(50):
        r.attempt()
    r.checkpoint()
    again = Runner(r.words, tmp_path / "life", r.cfg, quiet=True, resume=True)
    assert again.inner.nights == 1 and len(again.events) == len(r.events)
    assert len(again.replay) == len(r.replay) and np.array_equal(again.brain.w, r.brain.w)
