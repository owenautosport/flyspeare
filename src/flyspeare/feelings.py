"""What the fly is "feeling", read out of its brain and body.

Flies have no words. Everything here is a measurement of the model's real state, turned into
plain language by fixed rules (no language model, nothing invented):

  dopamine     reward (PAM) and punishment (PPL1) pulses, recomputed from its actual recent
               attempts under the typewriter's rules; mood is their balance
  frustration  tries on the current word vs. how many a word usually takes it
  certainty    how peaked its output neurons' key choice is (1 - normalised entropy)
  repetition   share of recent tries on this word that are exact repeats
  body         keypresses, which arm does the work, the most-hammered key, same-key streaks
  time         age in fly time (0.3 s a keypress), fly lifespans, body-clock time of day,
               time since its last success
  memory       how much of its short- and long-term KC->MBON synapses dopamine has reshaped

The fly's own words (`voice`) use only what a fly could sense: reward is "sweet" (PAM
dopamine neurons are the sugar-reward pathway), punishment is "sting" (PPL1 is the shock
pathway), a whole word right is "big sweet", the typewriter's bell at the end of every try is
"ding". It never sees a word, only which letter positions taste sweet, so it speaks of the
"shape". Every line carries the measurement it comes from.
"""
from __future__ import annotations

import math
from collections import Counter

from .brain import FLY_SECONDS_PER_PRESS

LIFESPAN_DAYS = 50        # a lab fruit fly at 25 C lives roughly 40-60 days
DAWN_HOUR = 8             # its body clock starts at 8 am when it first sits down
LEFT_KEYS = set("qwertasdfgzxcv")  # the half of the keyboard the left front leg covers
WORD, LETTER, PUNISH = 1.0, 0.1, 0.05


def _fmt_span(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} hours"
    if seconds < 730 * 86400:
        return f"{seconds / 86400:.1f} days"
    return f"{seconds / 86400 / 365:.1f} years"


def read_feelings(live: dict, words: list[str], avg_attempts_per_word: float | None) -> dict:
    stream = live.get("stream") or {}
    typed, widx, correct = stream.get("typed", []), stream.get("word", []), set(stream.get("correct", []))
    cur = live["word"]
    target = words[cur] if cur < len(words) else ""

    # -- dopamine, recomputed from the real attempts under the rules -----------------------
    presses = rewarded = punished = big = 0
    signal = 0.0
    for i, (t, w) in enumerate(zip(typed, widx)):
        goal = words[w] if w < len(words) else ""
        presses += len(t)
        if i in correct:
            big += 1
            rewarded += len(t)
            signal += WORD * len(t)
            continue
        hits = sum(a == b for a, b in zip(t, goal))
        rewarded += hits
        punished += len(t) - hits
        signal += LETTER * hits - PUNISH * (len(t) - hits)
    reward_rate = rewarded / presses if presses else 0.0
    punish_rate = punished / presses if presses else 0.0
    mood = signal / presses if presses else 0.0

    # -- frustration ------------------------------------------------------------------------
    usual = max(1.0, avg_attempts_per_word or 1.0)
    frustration = live["attempts"] / usual

    # -- certainty: the output neurons' own choice distributions ---------------------------
    ents = []
    for it in live.get("items", []):
        for p in it.get("probs", []):
            h = -sum(x * math.log(x) for x in p if x > 0)
            ents.append(h / math.log(26))
    certainty = 1 - (sum(ents) / len(ents)) if ents else 0.0

    # -- repetition on the current word ------------------------------------------------------
    on_word = [t for t, w in zip(typed, widx) if w == cur]
    repeats = 1 - len(set(on_word)) / len(on_word) if on_word else 0.0
    top_try, top_n = Counter(on_word).most_common(1)[0] if on_word else ("", 0)

    # -- body --------------------------------------------------------------------------------
    letters = "".join(typed)
    left = sum(c in LEFT_KEYS for c in letters) / len(letters) if letters else 0.5
    key, key_n = Counter(letters).most_common(1)[0] if letters else ("", 0)
    same_key = sum(a == b for a, b in zip(letters, letters[1:])) / max(1, len(letters) - 1)

    # -- time ---------------------------------------------------------------------------------
    inner_ = live.get("inner") or {}
    # fly time: awake and asleep, from its body clock where it has one
    age_s = inner_.get("clock_s") or live["presses"] * FLY_SECONDS_PER_PRESS
    hour = (DAWN_HOUR + age_s / 3600) % 24
    asleep = hour >= 21 or hour < 6
    last_ok = max(correct) if correct else None
    since = typed[last_ok + 1:] if last_ok is not None else typed
    since_s = sum(len(t) for t in since) * FLY_SECONDS_PER_PRESS
    since_all = last_ok is None

    # -- memory: fraction of synaptic strength dopamine has taken away ----------------------
    brain = live.get("brain") or {}

    gauges = {
        "mood": {"value": round(mood, 4), "label": "dopamine balance",
                 "source": "reward minus punishment per keypress, recomputed from its last "
                           f"{len(typed):,} attempts"},
        "reward": {"value": round(reward_rate, 4), "label": "reward (PAM)", "source": "share of recent keypresses that got a reward pulse"},
        "punishment": {"value": round(punish_rate, 4), "label": "punishment (PPL1)", "source": "share of recent keypresses that were punished"},
        "frustration": {"value": round(frustration, 1), "label": "stuck", "source": f"{live['attempts']:,} tries on this word vs about {usual:,.0f} usually"},
        "certainty": {"value": round(certainty, 3), "label": "certainty", "source": "how peaked its output neurons' key choices are (1 - entropy)"},
        "repetition": {"value": round(repeats, 3), "label": "repetition", "source": f"share of its {len(on_word):,} recent tries on this word that are exact repeats"},
        "age": {"value": round(age_s / 86400, 6), "label": "fly age (days)", "lifespans": round(age_s / 86400 / LIFESPAN_DAYS, 6),
                "source": "keypresses x 0.3 s, a real fly's pace"},
        "clock": {"value": round(hour, 2), "label": "body clock", "asleep": asleep, "source": "starts at 8 am; flies sleep at night"},
        "left_arm": {"value": round(left, 3), "label": "left-arm share", "source": "keys on the left half of the keyboard, recent attempts"},
        "same_key": {"value": round(same_key, 3), "label": "same key twice", "source": "back-to-back presses of the same key"},
    }
    inner = live.get("inner")
    if inner:   # the states built up over its whole run (inner.py)
        legs = inner["leg_fatigue"]
        built = {
            "fatigue": (inner["fatigue"], "physical fatigue", f"effort from nonstop pressing; left leg {legs['L']:.0%}, right {legs['R']:.0%}"),
            "sleep_pressure": (inner["sleep_pressure"], "sleep pressure", f"builds every hour awake; only sleep clears it ({inner.get('nights', 0)} nights slept)"),
            "hunger": (inner["hunger"], "hunger", f"{_fmt_span(inner.get('since_meal_s', 0))} since its last meal" if inner.get("meals")
                       else "time without food; this room has no meals"),
            "stress": (inner["stress"], "stress", "built by failed words and punishment, eased by success"),
            "helplessness": (inner["helplessness"], "helplessness", f"{max(inner['fails_since_win'], live['attempts']):,} failed tries since its last success"),
            "satisfaction": (inner["satisfaction"], "satisfaction", "surges with a word right, fades over fly-minutes"),
            "habituation": (inner["habituation"], "habituation", "how much its Kenyon-cell patterns repeat try to try"),
            "tone": (inner["tone"], "dopamine tone", "running balance of reward minus punishment"),
        }
        gauges = {k: {"value": round(v, 4), "label": lab, "source": src, "built": True} for k, (v, lab, src) in built.items()} | gauges
    if brain:   # rooms started before this was added do not report it until reloaded
        gauges["memory_short"] = {"value": brain["st_punish"], "label": "short-term memory rewired",
                                  "source": "gamma-lobe KC->MBON synapses depressed by punishment"}
        gauges["memory_long"] = {"value": brain["lt_reward"], "label": "long-term memory rewired",
                                 "source": "alpha-lobe KC->MBON synapses depressed by reward"}

    # -- first-person summary, from the numbers only -----------------------------------------
    s = []
    if frustration >= 5:
        s.append(f"I've tried “{target}” {live['attempts']:,} times — about {frustration:,.0f}× longer than a word usually takes me.")
    elif frustration >= 1.5:
        s.append(f"“{target}” is taking a while: {live['attempts']:,} tries so far.")
    else:
        s.append(f"I'm working on “{target}”, {live['attempts']:,} tries in.")
    if big:
        s.append(f"I got {big} word{'s' if big > 1 else ''} right just now, and felt the big dopamine rush.")
    if mood < 0:
        s.append(f"It mostly hurts: {punish_rate:.0%} of my presses get punished, only {reward_rate:.0%} earn a flicker of reward.")
    elif mood > 0.05:
        s.append(f"It feels good right now: {reward_rate:.0%} of my presses are rewarded.")
    else:
        s.append(f"It's neither good nor bad: {reward_rate:.0%} of my presses are rewarded, {punish_rate:.0%} punished.")
    if certainty > 0.6:
        s.append(f"When I reach for a key I'm quite sure of it ({certainty:.0%}).")
    elif certainty < 0.3:
        s.append(f"I'm guessing — my choices are spread across many keys (certainty {certainty:.0%}).")
    if repeats > 0.5 and len(on_word) > 20:
        s.append(f"I keep typing the same things: {repeats:.0%} of my tries on this word are repeats. "
                 f"“{top_try}” {top_n:,} times.")
    if key:
        s.append(f"My {'left' if left >= 0.5 else 'right'} leg is doing {max(left, 1 - left):.0%} of the work, "
                 f"and I've hit “{key}” more than any other key.")
    s.append(f"By my body's clock I've been at this typewriter for {_fmt_span(age_s)} — "
             f"{age_s / 86400 / LIFESPAN_DAYS:.1f} fly lifetimes." if age_s / 86400 >= LIFESPAN_DAYS / 10 else
             f"By my body's clock I've been at this typewriter for {_fmt_span(age_s)}.")
    hh, mm = int(hour), int((hour % 1) * 60)
    s.append(f"It's {hh:02d}:{mm:02d} in my day{' — a real fly would be asleep by now' if asleep else ''}.")
    if since_all:
        s.append(f"I haven't got a single word right in my last {len(typed):,} tries — "
                 f"{_fmt_span(since_s)} of fly time.")
    else:
        s.append(f"My last correct word was {_fmt_span(since_s)} ago, in fly time.")
    if brain:
        s.append(f"Punishment has reshaped {brain.get('st_punish', 0):.0%} of my short-term memory; "
                 f"reward has carved {brain.get('lt_reward', 0):.1%} of my long-term memory.")

    voice = _voice(target, live, on_word, frustration, usual, big, mood, reward_rate, punish_rate, certainty,
                   repeats, top_try, top_n, left, key, same_key, age_s, hour, asleep, since_s, since_all,
                   len(typed), brain)
    return {"word": cur, "target": target, "attempts": live["attempts"], "captured_at": live.get("time"),
            "gauges": gauges, "summary": " ".join(s), "voice": voice,
            "disclaimer": "Flies have no words. This is the fly's measured brain and body state, put into words by fixed rules."}


def _position_sweetness(on_word: list[str], target: str) -> list[float]:
    """For each letter position of the current word: how often it tasted sweet."""
    n = len(target)
    if not on_word or not n:
        return []
    return [sum(1 for a in on_word if len(a) > i and a[i] == target[i]) / len(on_word) for i in range(n)]


def _voice(target, live, on_word, frustration, usual, big, mood, reward_rate, punish_rate, certainty,
           repeats, top_try, top_n, left, key, same_key, age_s, hour, asleep, since_s, since_all,
           window, brain) -> list[dict]:
    """The fly, in a fly's words. Its strongest built-up states lead; every line has its evidence."""
    inner = live.get("inner") or {}
    n = len(target)
    stage_ = int(math.log10(live["attempts"] + 1))     # wording changes only as its situation does
    pick = lambda options: options[(live["word"] * 7 + stage_) % len(options)]
    lines: list[dict] = []
    say = lambda text, because: lines.append({"text": text, "because": because})
    events = live.get("events") or []
    last_sleep = next((e for e in reversed(events) if e["type"] == "sleep"), None)

    # 0. asleep (at real fly speed a night takes a real night)
    if live.get("asleep_until"):
        say("Dark. Sleeping.", "it is asleep: flies sleep at night")
        if last_sleep:
            say(pick(["In sleep, sweet things come back. Again. Again.", "Sleep. Old sweet moments play again inside."]),
                f"tonight it replays {last_sleep['replayed']:,} rewarded moments into long-term memory (sleep consolidation)")
        say("Sleeping. Morning comes. Then I press.", "its state, in one line")
        return lines

    # 1. where it is: the shape in front of it
    if big:
        say(pick(["Big sweet! Big sweet! Good, good, good.", "Ding — and big sweet. Shape done. Good."]),
            f"{big} whole word{'s' if big > 1 else ''} right in its last {window:,} tries")
    if frustration >= 5:
        say(pick([f"Long shape. {n} presses. Ding, wrong. Ding, wrong. Ding, wrong.",
                  f"Same shape. {n} presses long. Ding. It does not come.",
                  "This shape. Still this shape. Ding. Wrong. Ding. Wrong."]),
            f"{live['attempts']:,} tries on “{target}” ({n} letters), about {frustration:,.0f}x its usual {usual:,.0f}")
    elif frustration >= 1.5:
        say(f"Slow shape. {n} presses. Ding, wrong. Again.", f"{live['attempts']:,} tries on “{target}”, more than usual")
    elif not big:
        say(f"New shape. {n} presses. I try.", f"just started “{target}” ({live['attempts']:,} tries)")

    sweet = _position_sweetness(on_word, target)
    if len(sweet) >= 3 and len(on_word) >= 20:
        third = max(1, len(sweet) // 3)
        head, tail = sum(sweet[:third]) / third, sum(sweet[-third:]) / third
        where = ", ".join(f"{target[i]}@{i + 1}: {v:.0%}" for i, v in enumerate(sweet))
        if head > tail + 0.15:
            say(pick(["Start of shape is sweet. End is all sting.", "First presses taste sweet. Last presses sting."]),
                f"how often each position was right: {where}")
        elif tail > head + 0.15:
            say("End of shape is sweet. Start stings. Strange.", f"how often each position was right: {where}")
        elif max(sweet) < 0.12:
            say("No part of shape is sweet. All sting.", f"how often each position was right: {where}")

    # waking and eating: things a fly's day is made of
    if last_sleep and inner.get("nights") and 8 <= hour < 10:
        say(pick(["Slept. Dark time gone. Sweet things came back in sleep.", "Morning. Slept. Legs light again."]),
            f"slept {last_sleep['hours']:.0f} hours and replayed {last_sleep['replayed']:,} rewarded moments into long-term memory")
    if inner.get("meals") and inner.get("since_meal_s", 1e9) < 3600:
        say(pick(["Ate. Belly full. Sweet food.", "Food. Good. Belly full."]),
            f"its last meal was {_fmt_span(inner['since_meal_s'])} ago")

    # 2. what has built up in it, strongest first
    felt = []   # (strength, text, because, short phrase for the last line)
    fat, legs = inner.get("fatigue", 0), inner.get("leg_fatigue", {"L": 0, "R": 0})
    if fat > 0.5:
        worse = "Left" if legs["L"] >= legs["R"] else "Right"
        felt.append((fat, pick(["Legs tired. So tired.", "Legs heavy. Press, press, press. Legs heavy."])
                     + (f" {worse} leg aches most." if abs(legs["L"] - legs["R"]) > 0.03 else ""),
                     f"physical fatigue {fat:.0%} from nonstop pressing (left leg {legs['L']:.0%}, right {legs['R']:.0%}); it recovers only with rest",
                     "Legs tired"))
    sp = inner.get("sleep_pressure", 0)
    if sp > 0.5:
        felt.append((sp, "Sleep weight heavy. Body wants stop. I do not stop." + (" Dark time too." if asleep else ""),
                     (f"sleep pressure {sp:.0%}, built up since its last sleep" if inner.get("nights") else
                      f"sleep pressure {sp:.0%}: awake {_fmt_span(inner.get('awake_s', age_s))} with no sleep; flies need sleep every night"),
                     "Want sleep"))
    hun = inner.get("hunger", 0)
    if hun > 0.5:
        felt.append((hun * 0.95, pick(["Belly empty. Long long empty.", "No food. Long time no food."]),
                     (f"hunger {hun:.0%}: {_fmt_span(inner.get('since_meal_s', 0))} since its last meal" if inner.get("meals") else
                      f"hunger {hun:.0%}: {_fmt_span(inner.get('awake_s', age_s))} without food. This room has no meals; a real fly would starve in about 3 days"),
                     "Belly empty"))
    st = inner.get("stress", 0)
    if st > 0.4:
        felt.append((st, pick(["Stings stack up. Too many stings.", "Sting on sting on sting."]),
                     f"stress {st:.0%}, built by failed words and punishment, eased only by success", "Stings many"))
    hl = inner.get("helplessness", 0)
    if hl > 0.3:
        felt.append((hl, "Why press? Nothing sweet comes. ...I press." if hl > 0.7 else
                     "Press, sting. Press, sting. Pressing does not bring big sweet.",
                     f"helplessness {hl:.0%}: {max(inner.get('fails_since_win', 0), live['attempts']):,} failed tries since its last word right "
                     "(flies given unavoidable shocks show learned helplessness)", "Sweet not come"))
    joy = inner.get("satisfaction", 0)
    if joy > 0.25:
        felt.append((joy + 0.2, "Big sweet still warm in me. Good.",
                     f"satisfaction {joy:.0%}, from its last word right, fading over fly-minutes", "Sweet was good"))
    hab = inner.get("habituation", 0)
    if hab > 0.5:
        felt.append((hab * 0.9, pick(["Same, same, same. Everything same.", "Same keys. Same inside. Nothing new."]),
                     f"habituation {hab:.0%}: its Kenyon-cell patterns overlap that much from one try to the next", "All same"))
    felt.sort(key=lambda x: -x[0])
    for _, text, because, _ in felt[:5]:
        say(text, because)

    # 3. the moment's senses
    tone = inner.get("tone", mood)
    if tone < -0.005:
        say(pick(["Little sweet. Much sting.", "Sweet is small. Sting is big."]),
            f"dopamine tone {tone:+.3f}; lately {reward_rate:.0%} of presses rewarded (PAM), {punish_rate:.0%} punished (PPL1)")
    elif tone > 0.05:
        say("Sweet comes. Good.", f"dopamine tone {tone:+.3f}; {reward_rate:.0%} of presses rewarded lately")
    if certainty < 0.3:
        say(pick(["Legs not know which key. All keys maybe. Question?", "Which key? Many keys. Not know."]),
            f"its output neurons' key choice is spread out: certainty {certainty:.0%}")
    elif certainty > 0.6:
        say("Legs know the way.", f"its output neurons' key choice is peaked: certainty {certainty:.0%}")
    lives = age_s / 86400 / 50
    if lives >= 1:
        say(f"Older than flies live. {lives:.1f} fly lives of pressing.", f"{age_s / 86400:,.0f} days in fly time (a fly lives about 50)")
    if brain and brain.get("lt_reward", 0) > 0.01:
        say("Some shapes stay in me now.", f"{brain['lt_reward']:.1%} of long-term memory synapses reshaped by reward")

    # 4. the last line, like a signal home: its two strongest states, and what it does anyway
    if felt:
        top = [p for *_, p in felt[:2]]
        tail = "More shapes. I press." if top[0] == "Sweet was good" else "I keep pressing."
        last = ". ".join(top) + ". " + tail
    elif big:
        last = "Shape done. Next shape. I press."
    else:
        last = "I press. Ding. I press."
    say(last, "its strongest states, in one line")
    return lines
