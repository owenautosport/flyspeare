"""Shakespeare as two streams: what the fly must type, and what the paper shows.

The target stream is lowercase a-z words. Each word keeps its character span in the
original (display) text, so the paper can print the capitals and punctuation around it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

GUTENBERG_URL = "https://www.gutenberg.org/cache/epub/100/pg100.txt"
_START = re.compile(r"^\*\*\* START OF THE PROJECT GUTENBERG EBOOK.*$", re.M)
_END = re.compile(r"^\*\*\* END OF THE PROJECT GUTENBERG EBOOK.*$", re.M)


@dataclass(frozen=True)
class Word:
    text: str   # lowercase a-z
    start: int  # span in the display text
    end: int


def strip_gutenberg(raw: str) -> str:
    """The works only: no Gutenberg header/licence, no title page or contents list."""
    start, end = _START.search(raw), _END.search(raw)
    body = raw[start.end() if start else 0 : end.start() if end else len(raw)]
    # The contents list names THE SONNETS first; the works begin at its second,
    # unindented occurrence.
    m = re.search(r"^THE SONNETS\s*$", body, re.M)
    return body[m.start():].rstrip() + "\n" if m else body.strip() + "\n"


def _letter(ch: str) -> str | None:
    base = unicodedata.normalize("NFKD", ch)[:1].lower()
    return base if "a" <= base <= "z" else None


def tokenize(display: str) -> list[Word]:
    words: list[Word] = []
    buf: list[str] = []
    start = 0
    for i, ch in enumerate(display):
        letter = _letter(ch)
        if letter is not None:
            if not buf:
                start = i
            buf.append(letter)
        elif buf:
            words.append(Word("".join(buf), start, i))
            buf = []
    if buf:
        words.append(Word("".join(buf), start, len(display)))
    return words


def load(path: str | Path) -> tuple[str, list[Word]]:
    display = strip_gutenberg(Path(path).read_text(encoding="utf-8"))
    return display, tokenize(display)
