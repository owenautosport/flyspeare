import csv
import json

import numpy as np

from flyspeare.brain import BrainConfig
from flyspeare.run import RunConfig, Runner

VERSE = "to be or not to be".split()


def rows(run_dir):
    with open(run_dir / "words.csv") as f:
        return list(csv.DictReader(f))


def test_learning_beats_a_frozen_brain(tmp_path):
    learner = Runner(VERSE * 30, tmp_path / "learn", RunConfig(seed=0), quiet=True)
    learner.run()
    frozen = Runner(VERSE, tmp_path / "frozen", RunConfig(seed=0, brain=BrainConfig(eta=0)), quiet=True)
    frozen.run()
    learned_tail = np.mean([int(r["attempts"]) for r in rows(tmp_path / "learn")[-30:]])
    frozen_mean = np.mean([int(r["attempts"]) for r in rows(tmp_path / "frozen")])
    assert learned_tail < 15, learned_tail
    assert frozen_mean > 20 * learned_tail


def test_resume_matches_an_uninterrupted_run(tmp_path):
    words = VERSE * 8
    straight = Runner(words, tmp_path / "a", RunConfig(seed=3), quiet=True)
    straight.run()

    first = Runner(words, tmp_path / "b", RunConfig(seed=3), quiet=True)
    first.run(max_words=17)
    first.checkpoint()
    second = Runner(words, tmp_path / "b", RunConfig(seed=3), quiet=True, resume=True)
    second.run()

    assert np.array_equal(straight.brain.w, second.brain.w)
    key = lambda rs: [(r["index"], r["word"], r["attempts"], r["presses"]) for r in rs]
    assert key(rows(tmp_path / "a")) == key(rows(tmp_path / "b"))


def test_resume_drops_rows_written_after_the_checkpoint(tmp_path):
    words = VERSE * 4
    r = Runner(words, tmp_path / "c", RunConfig(seed=1), quiet=True)
    r.run(max_words=5)
    r.checkpoint()
    r.run(max_words=9)  # rows 5-8 written, but no checkpoint: a crash here
    again = Runner(words, tmp_path / "c", RunConfig(seed=1), quiet=True, resume=True)
    again.run()
    idx = [int(x["index"]) for x in rows(tmp_path / "c")]
    assert idx == list(range(len(words)))


def test_stop_mid_word_keeps_the_attempt_count(tmp_path):
    r = Runner(["abcdefghij"], tmp_path / "d", RunConfig(seed=0), quiet=True)
    r.run(max_attempts=50)
    assert r.word_idx == 0 and r.attempts == 50
    r.checkpoint()
    again = Runner(["abcdefghij"], tmp_path / "d", RunConfig(seed=0), quiet=True, resume=True)
    assert again.word_idx == 0 and again.attempts == 50


def test_outputs_for_the_viewer(tmp_path):
    r = Runner(VERSE, tmp_path / "e", RunConfig(seed=0), quiet=True)
    r.run()
    r.checkpoint()
    lines = (tmp_path / "e" / "recent.jsonl").read_text().splitlines()
    last = json.loads(lines[-1])
    assert last["correct"] and last["typed"] == "be"
    assert len(last["kcs"]) == 2 and len(last["kcs"][0]) == 100
    assert len(last["probs"][0]) == 26 and len(last["dopamine"]) == 2
    assert len(last["pns"]) == 2 and last["seq"] == r.totals["attempts"]
    brain = json.loads((tmp_path / "e" / "brain.json").read_text())
    assert brain["n_kc"] == 2000 and len(brain["pn_to_kc"]) == 2000


def test_p_word_rises_after_learning_it(tmp_path):
    r = Runner(["rose", "rose"], tmp_path / "f", RunConfig(seed=0), quiet=True)
    before = r.p_word()
    r.run(max_words=1)
    assert r.p_word() > before


def test_block_rows_sum_words(tmp_path):
    r = Runner(VERSE * 2, tmp_path / "g", RunConfig(seed=0, csv_every=5), quiet=True)
    r.run()
    got = rows(tmp_path / "g")
    assert [int(x["index"]) for x in got] == [4, 9, 11]
    one = Runner(VERSE * 2, tmp_path / "h", RunConfig(seed=0), quiet=True)
    one.run()
    assert sum(int(x["attempts"]) for x in got) == sum(int(x["attempts"]) for x in rows(tmp_path / "h"))


def test_unreliable_dopamine_drops_small_hits_only(tmp_path):
    from flyspeare.rules import Rewards
    r = Runner(["abcdefgh"], tmp_path / "q", RunConfig(seed=0, rewards=Rewards(hit_prob=0.0)), quiet=True)
    for _ in range(50):
        typed, correct, signals = r.attempt()
        assert all(s <= 0 for s in signals) or correct  # no small hits ever arrive


def test_hit_prob_makes_learning_harder(tmp_path):
    from flyspeare.rules import Rewards
    words = "the rose that thee thine".split() * 6
    def presses(q):
        r = Runner(words, tmp_path / f"p{q}", RunConfig(seed=0, rewards=Rewards(hit_prob=q)), quiet=True)
        r.run()
        return r.totals["presses"]
    assert presses(0.0) > presses(1.0)


def test_slipping_feet_type_neighbours_and_credit_the_intended_key(tmp_path):
    from flyspeare.rules import NEIGHBOURS, Rewards
    r = Runner(["abcdefgh"], tmp_path / "s", RunConfig(seed=0, rewards=Rewards(slip=1.0)), quiet=True)
    for _ in range(20):
        r.attempt()
        typed, intended = r.recent[-1]["typed"], r.recent[-1]["intended"]
        assert all(t in NEIGHBOURS[i] for t, i in zip(typed, intended))


def test_no_slip_types_what_it_meant(tmp_path):
    r = Runner(["abcdefgh"], tmp_path / "n", RunConfig(seed=0), quiet=True)
    r.attempt()
    assert r.recent[-1]["typed"] == r.recent[-1]["intended"]


def test_kc_cache_stays_bounded_on_a_long_stall(tmp_path):
    # the brain's input is only the last few keypresses + position, so a word failed
    # thousands of times must not grow the cache without limit (it once reached 9 GB)
    from dataclasses import replace
    from flyspeare import run as run_mod
    cfg = RunConfig(seed=0, brain=BrainConfig(ctx_len=4, length_cue=False))
    r = Runner(["abcdefghijklm"], tmp_path / "c", cfg, quiet=True)
    old = run_mod.KC_CACHE_MAX
    run_mod.KC_CACHE_MAX = 500
    try:
        r.run(max_attempts=3000)
    finally:
        run_mod.KC_CACHE_MAX = old
    assert len(r._kc_cache) <= 500


def test_cache_key_gives_identical_results(tmp_path):
    # same seed, same inputs: caching by (window, position) must not change what is typed
    words = VERSE * 3
    a = Runner(words, tmp_path / "x", RunConfig(seed=5), quiet=True)
    a.run()
    b = Runner(words, tmp_path / "y", RunConfig(seed=5), quiet=True)
    b._kc_cache_disabled = True
    b.run()
    assert np.array_equal(a.brain.w, b.brain.w)


def test_live_stream_has_every_attempt_in_order(tmp_path):
    r = Runner(VERSE * 3, tmp_path / "s", RunConfig(seed=0), quiet=True)
    r.run(max_attempts=500)
    snap = r.live_snapshot()
    st = snap["stream"]
    n = len(st["typed"])
    assert n == min(500, r.totals["attempts"])
    # consecutive sequence numbers: nothing skipped
    assert st["last_seq"] - st["first_seq"] + 1 == n == r.totals["attempts"]
    assert all(st["typed"][i] == VERSE[st["word"][i] % len(VERSE)] for i in st["correct"])


def test_inner_state_is_carried_through_checkpoints(tmp_path):
    r = Runner(VERSE * 4, tmp_path / "i", RunConfig(seed=0), quiet=True)
    r.run(max_words=10)
    r.checkpoint()
    again = Runner(VERSE * 4, tmp_path / "i", RunConfig(seed=0), quiet=True, resume=True)
    assert again.inner.to_dict() == r.inner.to_dict() and again.inner.fatigue > 0
    assert r.live_snapshot()["inner"]["wins"] == 10


def test_rooms_from_before_inner_states_are_seeded_from_their_history(tmp_path):
    import json
    r = Runner(["abcdefghij"], tmp_path / "old", RunConfig(seed=0), quiet=True)
    r.run(max_attempts=400)
    r.checkpoint()
    state = json.loads((tmp_path / "old" / "state.json").read_text())
    del state["inner"]                       # as a checkpoint written before they existed
    (tmp_path / "old" / "state.json").write_text(json.dumps(state))
    again = Runner(["abcdefghij"], tmp_path / "old", RunConfig(seed=0), quiet=True, resume=True)
    # seeded from exactly what the checkpoint recorded
    assert again.inner.fails_since_win == again.attempts == state["attempts"]
    assert again.inner.wins == again.word_idx == state["word_idx"]
    assert again.inner.awake_s == again.totals["presses"] * 0.3 > 0
