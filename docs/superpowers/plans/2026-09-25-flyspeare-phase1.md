# flyspeare Phase 1 Implementation Plan

> Executed natively in the session it was written in (Owen: "build it"). Steps are TDD per task.

**Goal:** A headless mushroom-body fly that types Shakespeare word by word under the spec's
dopamine rules, with resumable runs, live terminal stats, and a stall report.

**Architecture:** `text` → target words + display spans. `rules` → check an attempt and assign
per-press dopamine. `brain` → PN encoding → sparse KCs (k-WTA) → 26 key MBONs → softmax, with a
three-factor plasticity update. `run` → the loop, checkpoints, outputs. `cli` → `run` and `report`.

**Tech Stack:** Python 3.11, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-flyspeare-design.md`

## Global Constraints

- 26 keys, a–z. The target stream is lowercase and split on any non a–z character.
- Rewards: `R_word`=1.0, `r_letter`=0.1, `p_letter`=0.05, membership only, never position.
- No stall cap. The watchdog reports at 1k / 10k / 100k attempts and never intervenes.
- 2,000 KCs, 6–8 PN inputs each, ~5% active (k-WTA).
- A seeded run is deterministic, and resume gives the same result as an uninterrupted run.

## Review Focus

1. Accented or odd Unicode letters (é, æ, curly apostrophes) must not crash; they either map
   to a–z or split the word.
2. SIGINT mid-word must checkpoint the current word's attempt count and resume on the same word.
3. Very long words (> 20 letters) must encode without index errors (positions are binned).
4. A resumed run must not duplicate rows in `words.csv`.
5. A mid-stall checkpoint must be time-based, not only every N words, or a stall loses hours
   of progress.

## Tasks

1. **Scaffold + text** — `pyproject.toml`, `text.py` (strip Gutenberg, start at the Sonnets,
   tokenise with spans). Tests: golden normalisation, spans, Unicode.
2. **Rules** — `rules.py`, `score_attempt`. Tests: the §4.3 table, doubled letters.
3. **Brain** — `brain.py`, covering encoding, KC sparsity, probs with floor, and learn. Tests:
   sparsity, update touches only active KCs × the chosen key, determinism, long-word encoding.
4. **Run loop** — `run.py`, with the loop, `P(word)` estimate, stats, checkpoints (N words +
   time + SIGINT), `words.csv`, `recent.jsonl`, `brain.json`. Tests: toy-corpus learning beats
   the frozen baseline; resume equals uninterrupted; no duplicate CSV rows.
5. **CLI + report** — `flyspeare run|report`. Benchmark presses/s.
6. **Phase 1 run** — the first 10,000 words of the Sonnets, then the report (exit criteria §11).
