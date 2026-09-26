"""The typewriter's judgement of one attempt at one word (spec §4.3)."""
from __future__ import annotations

from dataclasses import dataclass

ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# A QWERTY typewriter: which keys a slipping foot can land on instead.
_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]


def _neighbours() -> dict[str, tuple[str, ...]]:
    pos = {ch: (r, c) for r, row in enumerate(_ROWS) for c, ch in enumerate(row)}
    out = {}
    for ch, (r, c) in pos.items():
        # each row sits half a key to the right of the row above
        near = [(r, c - 1), (r, c + 1), (r - 1, c), (r - 1, c + 1), (r + 1, c), (r + 1, c - 1)]
        out[ch] = tuple(_ROWS[rr][cc] for rr, cc in near if 0 <= rr < 3 and 0 <= cc < len(_ROWS[rr]))
    return out


NEIGHBOURS = _neighbours()


@dataclass(frozen=True)
class Rewards:
    word: float = 1.0     # big hit: the whole word is right
    letter: float = 0.1   # small hit for a letter (see feedback)
    punish: float = 0.05  # punishment for a letter that gets no small hit
    # "membership": small hit if the letter is anywhere in the word (never position)
    # "position":   small hit only if the letter is in the right place (never "right letter, wrong place")
    feedback: str = "position"
    # Dopamine release is probabilistic: each small hit reaches the brain with this chance.
    # The difficulty knob. Big word hits and punishments are always delivered.
    hit_prob: float = 1.0
    # Slipping feet: chance a press lands on a neighbouring key instead of the intended one.
    # The brain is judged on what was typed but credits the key it meant to press.
    slip: float = 0.0


def score_attempt(attempt: str, target: str, rw: Rewards) -> tuple[bool, list[float]]:
    """Return (correct, one dopamine signal per press)."""
    if attempt == target:
        return True, [rw.word] * len(attempt)
    if rw.feedback == "position":
        hits = [a == t for a, t in zip(attempt, target)]
    else:
        letters = set(target)
        hits = [ch in letters for ch in attempt]
    return False, [rw.letter if h else -rw.punish for h in hits]
