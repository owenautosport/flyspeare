from flyspeare.rules import Rewards, score_attempt

RW = Rewards(word=1.0, letter=0.1, punish=0.05, feedback="membership")


def test_correct_word_gives_big_hit_to_every_press():
    ok, sig = score_attempt("rose", "rose", RW)
    assert ok and sig == [1.0, 1.0, 1.0, 1.0]


def test_wrong_word_is_membership_only_not_position():
    # 'eosr' has every letter of 'rose' in the wrong place: all small hits, no punishment
    ok, sig = score_attempt("eosr", "rose", RW)
    assert not ok and sig == [0.1, 0.1, 0.1, 0.1]


def test_letters_not_in_word_are_punished():
    ok, sig = score_attempt("rzsx", "rose", RW)
    assert not ok and sig == [0.1, -0.05, 0.1, -0.05]


def test_doubled_letters_judged_by_membership():
    ok, sig = score_attempt("eeee", "thee", RW)
    assert not ok and sig == [0.1, 0.1, 0.1, 0.1]


POS = Rewards(word=1.0, letter=0.1, punish=0.0, feedback="position")


def test_position_mode_rewards_only_letters_in_the_right_place():
    # 'eosr' vs 'rose': 'o' and 's' are in the right place; 'e' and 'r' are not
    ok, sig = score_attempt("eosr", "rose", POS)
    assert not ok and sig == [0.0, 0.1, 0.1, 0.0]


def test_position_mode_never_rewards_right_letter_wrong_place():
    ok, sig = score_attempt("esor", "rose", POS)
    assert sig == [0.0, 0.0, 0.0, 0.0]


def test_position_mode_can_punish_the_misses():
    rw = Rewards(word=1.0, letter=0.1, punish=0.05, feedback="position")
    ok, sig = score_attempt("rzsx", "rose", rw)
    assert sig == [0.1, -0.05, 0.1, -0.05]


def test_position_mode_correct_word_still_big_hit():
    assert score_attempt("rose", "rose", POS) == (True, [1.0] * 4)


def test_qwerty_neighbours():
    from flyspeare.rules import NEIGHBOURS
    assert set(NEIGHBOURS["g"]) == {"f", "h", "t", "y", "v", "b"}
    assert set(NEIGHBOURS["q"]) == {"w", "a"}
    assert all(k in NEIGHBOURS[n] for k, ns in NEIGHBOURS.items() for n in ns)  # symmetric
