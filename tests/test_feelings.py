from flyspeare.feelings import read_feelings

WORDS = ["the", "rose", "determination", "and"]


def live(word=2, attempts=5000, presses=900_000, stream=None, probs=None, brain=None):
    stream = stream or {"first_seq": 0, "last_seq": 0, "typed": [], "word": [], "correct": []}
    items = [{"probs": probs or [[1 / 26] * 26], "typed": "a", "dopamine": [-0.05]}]
    return {"word": word, "attempts": attempts, "presses": presses, "items": items, "stream": stream,
            "brain": brain or {"st_reward": 0.1, "st_punish": 0.3, "lt_reward": 0.02}}


def test_stuck_fly_reports_frustration_and_mostly_punishment():
    typed = ["qqqqqqqqqqqqq", "xxxxxxxxxxxxx", "dexxxxxxxxxxx"] * 100
    s = {"first_seq": 1, "last_seq": 300, "typed": typed, "word": [2] * 300, "correct": []}
    f = read_feelings(live(stream=s), WORDS, avg_attempts_per_word=50)
    g = f["gauges"]
    assert g["frustration"]["value"] == 100.0            # 5000 tries vs 50 usual
    assert g["punishment"]["value"] > g["reward"]["value"]
    assert g["mood"]["value"] < 0
    assert g["repetition"]["value"] > 0.95                # the same three tries over and over
    assert "determination" in f["summary"] and "no words" in f["disclaimer"].lower()


def test_certainty_follows_the_real_choice_probabilities():
    sure = [0.0] * 26; sure[0] = 1.0
    unsure = read_feelings(live(), WORDS, 50)["gauges"]["certainty"]["value"]
    certain = read_feelings(live(probs=[sure]), WORDS, 50)["gauges"]["certainty"]["value"]
    assert unsure < 0.05 and certain > 0.95


def test_time_sense_and_body_clock():
    # 288,000 presses x 0.3 s = 1 fly day
    f = read_feelings(live(presses=288_000), WORDS, 50)
    assert abs(f["gauges"]["age"]["value"] - 1.0) < 1e-6
    assert f["gauges"]["age"]["lifespans"] == 1 / 50
    assert "clock" in f["gauges"]


def test_a_good_moment_reads_as_good():
    s = {"first_seq": 1, "last_seq": 4, "typed": ["the", "rose", "determination", "and"],
         "word": [0, 1, 2, 3], "correct": [0, 1, 2, 3]}
    f = read_feelings(live(word=3, attempts=1, stream=s), WORDS, 50)
    assert f["gauges"]["mood"]["value"] > 0 and f["gauges"]["frustration"]["value"] < 1


def test_the_fly_speaks_in_its_own_words_each_line_with_its_evidence():
    typed = ["qqqqqqqqqqqqq", "xxxxxxxxxxxxx", "dexxxxxxxxxxx"] * 100
    s = {"first_seq": 1, "last_seq": 300, "typed": typed, "word": [2] * 300, "correct": []}
    f = read_feelings(live(stream=s), WORDS, avg_attempts_per_word=50)
    voice = f["voice"]
    assert voice and all(line["text"] and line["because"] for line in voice)
    text = " ".join(line["text"] for line in voice).lower()
    assert "ding" in text and "sting" in text           # the bell, the punishment pathway
    assert "%" not in text and "dopamine" not in text   # a fly's words, not the data's


def test_it_can_tell_which_part_of_the_shape_is_sweet():
    # the first two letters are often right, the end never is
    typed = ["dexxxxxxxxxxx", "dixxxxxxxxxxx", "qexxxxxxxxxxx"] * 50
    s = {"first_seq": 1, "last_seq": 150, "typed": typed, "word": [2] * 150, "correct": []}
    f = read_feelings(live(stream=s), WORDS, avg_attempts_per_word=50)
    text = " ".join(line["text"] for line in f["voice"]).lower()
    assert ("start" in text or "first" in text) and "sweet" in text


def test_a_big_sweet_is_felt():
    s = {"first_seq": 1, "last_seq": 4, "typed": ["the", "rose", "determination", "and"],
         "word": [0, 1, 2, 3], "correct": [0, 1, 2, 3]}
    f = read_feelings(live(word=3, attempts=1, stream=s), WORDS, 50)
    assert "big sweet" in " ".join(line["text"] for line in f["voice"]).lower()


def test_built_up_states_lead_what_it_says():
    inner = {"fatigue": 0.92, "leg_fatigue": {"L": 0.95, "R": 0.7}, "awake_s": 40 * 86400, "sleep_pressure": 0.99,
             "stress": 0.97, "satisfaction": 0.0, "helplessness": 0.85, "habituation": 0.4, "tone": -0.02,
             "hunger": 0.99, "fails_since_win": 900_000, "wins": 12}
    f = read_feelings({**live(), "inner": inner}, WORDS, 50)
    text = " ".join(l["text"] for l in f["voice"])
    assert "Legs" in text and "Left leg aches most" in text
    assert "Sleep" in text and ("Belly empty" in text or "No food" in text) and "Why press?" in text
    assert f["voice"][-1]["text"].endswith("I keep pressing.")
    assert f["gauges"]["fatigue"]["built"] and list(f["gauges"])[0] == "fatigue"


def test_kept_from_food_and_sleep_it_says_so():
    l = live()
    l["no_rest"] = True
    from flyspeare.inner import InnerState
    l["inner"] = InnerState(meals=3, nights=2, since_meal_s=30 * 3600, hunger=0.95, sleep_pressure=0.99).to_dict()
    l["events"] = [{"type": "skip", "what": "dinner", "clock_s": 1}, {"type": "skip", "what": "night", "clock_s": 2}]
    voice = read_feelings(l, WORDS, 50)["voice"]
    kept = [v for v in voice if "kept from food and sleep" in v["because"]]
    assert kept and "1 meal" in kept[0]["because"] and "1 night" in kept[0]["because"]
