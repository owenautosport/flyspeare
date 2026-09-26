"""The speed-ups in the hot path are exact: each computes the same numbers as the plain code."""
import numpy as np

from flyspeare.brain import AVOID, BrainConfig, make_brain


def test_encode_indices_are_already_sorted_and_distinct():
    for cue in (True, False):
        b = make_brain(BrainConfig(ctx_len=4, length_cue=cue), seed=0)
        for ctx, prefix, L in [("the ", "", 3), ("aa  ", "zzzz", 9), ("", "q", 30), ("xyz ", "abcdefghijklmnopqrstuvw", 25)]:
            pns = b.encode(ctx, prefix, L)
            assert np.array_equal(pns, np.unique(pns))


def test_mbon_choice_and_forgetting_match_the_plain_formulas():
    b = make_brain(BrainConfig(wiring="flywire", ctx_len=4, output="mbon", tau=0.18, length_cue=False), seed=0)
    b.w *= np.random.default_rng(1).uniform(0.3, 1, b.w.shape).astype(np.float32)
    kcs = b.kcs(b.encode("the ", "ab", 7))
    e, coef = b._prep(kcs)[:2]
    drive = coef @ (b.cfg.w0 - b.w[e])                        # plain fancy indexing
    logits = drive / b.cfg.tau
    x = np.exp(logits - logits.max())
    assert np.array_equal(b.probs(kcs), (1 - 26 * b.cfg.floor) * x / x.sum() + b.cfg.floor)
    w = b.w.copy()
    w -= (w - b.cfg.w0) * (1 - np.exp(-777.0 / b.e_tau).astype(np.float32)[:, None])   # exp per synapse
    b.elapse(777.0)
    assert np.array_equal(b.w, w)


def test_per_key_choice_and_learning_match_the_plain_formulas():
    b = make_brain(BrainConfig(wiring="flywire", ctx_len=4, tau=0.2, length_cue=False), seed=0)
    b.w *= np.random.default_rng(1).uniform(0.3, 1, b.w.shape).astype(np.float32)
    kcs = b.kcs(b.encode("the ", "ab", 7))
    m = b.w[:, :, kcs].mean(axis=2)
    drive = b._gain @ (m[:, 0] - m[:, 1])
    x = np.exp(drive / b.cfg.tau - (drive / b.cfg.tau).max())
    assert np.array_equal(b.probs(kcs), (1 - 26 * b.cfg.floor) * x / x.sum() + b.cfg.floor)
    w = b.w.copy()
    w[0, AVOID, kcs, 4] *= 1 - min(1.0, b.cfg.eta * b.cfg.compartments[0].eta * 0.1)
    w[1, AVOID, kcs, 4] *= 1 - min(1.0, b.cfg.eta * b.cfg.compartments[1].eta * 0.1)
    b.learn([(kcs, 4)], [0.1])
    assert np.array_equal(b.w, w)
