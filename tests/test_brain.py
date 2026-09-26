import numpy as np
import pytest

from flyspeare.brain import APPROACH, AVOID, Brain, BrainConfig


def make(seed=0, **kw):
    return Brain(BrainConfig(**kw), seed=seed)


def comp(b, name):
    return [c.name for c in b.cfg.compartments].index(name)


# -- wiring and sparsity -------------------------------------------------------------------

def test_kc_layer_is_sparse():
    b = make()
    kcs = b.kcs(b.encode("the son", "net", 7))
    assert len(kcs) == b.n_active == 100  # 5% of 2,000
    assert len(set(kcs.tolist())) == len(kcs)


def test_each_random_kc_has_six_to_eight_pn_inputs():
    counts = make().pn_to_kc.sum(axis=0)
    assert counts.min() >= 6 and counts.max() <= 8


def test_flywire_wiring_is_the_real_connectome():
    from flyspeare import flywire
    real = flywire.load()["syn"]
    b = make(wiring="flywire", ctx_len=4)
    assert b.n_kc == real.shape[1] == 2456
    assert b.n_active == round(0.05 * 2456)
    # every input channel drives one distinct real projection neuron, with its real synapses
    assert len(set(b.channel_to_pn.tolist())) == b.n_pn
    assert np.array_equal(b.pn_kc_w, real[b.channel_to_pn])


def test_flywire_flies_share_the_brain_but_map_senses_differently():
    a, c = make(1, wiring="flywire", ctx_len=4), make(2, wiring="flywire", ctx_len=4)
    assert not np.array_equal(a.channel_to_pn, c.channel_to_pn)


def test_same_seed_same_wiring():
    assert (make(1).pn_to_kc == make(1).pn_to_kc).all()
    assert not (make(1).pn_to_kc == make(2).pn_to_kc).all()


def test_long_words_encode_without_error():
    b = make()
    word = "honorificabilitudinitatibus"
    assert len(b.kcs(b.encode("the ", word[:26], len(word)))) == b.n_active


def test_without_length_cue_word_length_is_invisible():
    b = make(length_cue=False)
    assert (b.encode("the ", "ro", 4) == b.encode("the ", "ro", 9)).all()
    assert not (make().encode("the ", "ro", 4) == make().encode("the ", "ro", 9)).all()


# -- choosing ------------------------------------------------------------------------------

def test_probs_are_a_distribution_with_a_floor():
    b = make()
    p = b.probs(b.kcs(b.encode("", "", 3)))
    assert p.shape == (26,) and abs(p.sum() - 1) < 1e-9
    assert p.min() >= b.cfg.floor


# -- dopamine: depression only -------------------------------------------------------------

def test_dopamine_never_strengthens_a_synapse():
    b = make()
    kcs = b.kcs(b.encode("abc", "", 3))
    before = b.w.copy()
    b.learn([(kcs, 4), (kcs, 5)], [1.0, -0.05])
    assert (b.w <= before).all()


def test_reward_depresses_only_avoid_synapses_of_active_kcs_for_the_chosen_key():
    b = make()
    kcs = b.kcs(b.encode("abc", "", 3))
    before = b.w.copy()
    b.learn([(kcs, 4)], [1.0])
    changed = np.argwhere(b.w != before)  # (compartment, valence, kc, key)
    assert set(changed[:, 1]) == {AVOID}
    assert set(changed[:, 3]) == {4}
    assert set(changed[:, 2]) == set(kcs.tolist())


def test_punishment_depresses_only_short_term_approach_synapses():
    b = make()
    kcs = b.kcs(b.encode("abc", "", 3))
    before = b.w.copy()
    b.learn([(kcs, 7)], [-0.05])
    changed = np.argwhere(b.w != before)
    assert set(changed[:, 0]) == {comp(b, "short-term")}
    assert set(changed[:, 1]) == {APPROACH}


def test_reward_shifts_choice_towards_the_key_and_punishment_away():
    b = make()
    kcs = b.kcs(b.encode("x", "", 1))
    p0 = b.probs(kcs)
    b.learn([(kcs, 3)], [1.0])
    assert b.probs(kcs)[3] > p0[3]
    b2 = make()
    b2.learn([(kcs, 3)], [-0.05])
    assert b2.probs(kcs)[3] < p0[3]


def test_long_term_learns_slower_than_short_term():
    b = make()
    kcs = b.kcs(b.encode("abc", "", 3))
    st, lt = comp(b, "short-term"), comp(b, "long-term")
    b.learn([(kcs, 2)], [1.0])
    drop = lambda i: b.cfg.w0 - b.w[i, AVOID][kcs, 2].mean()
    assert drop(st) > drop(lt) > 0


def test_short_term_recovers_within_hours_long_term_lasts():
    b = make()
    kcs = b.kcs(b.encode("abc", "", 3))
    st, lt = comp(b, "short-term"), comp(b, "long-term")
    b.learn([(kcs, 2)], [1.0])
    drop = lambda i: b.cfg.w0 - b.w[i, AVOID][kcs, 2].mean()
    st0, lt0 = drop(st), drop(lt)
    b.elapse(fly_seconds=4 * 3600)
    assert drop(st) < 0.05 * st0
    assert drop(lt) > 0.9 * lt0


def test_repeated_reward_builds_long_term_memory():
    b, once = make(), make()
    kcs = b.kcs(b.encode("abc", "", 3))
    lt = comp(b, "long-term")
    once.learn([(kcs, 2)], [1.0])
    for _ in range(10):
        b.learn([(kcs, 2)], [1.0])
    assert b.w[lt, AVOID][kcs, 2].mean() < once.w[lt, AVOID][kcs, 2].mean()


def test_unknown_wiring_is_rejected():
    with pytest.raises(ValueError):
        make(wiring="nonsense")
