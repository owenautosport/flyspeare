# flyspeare — design

**Date:** 2026-09-25
**Status:** approved 2026-09-25; revised the same day after phase 1 trials (see §0)
**Scope of this document:** the whole project, built in four phases. Phase 1 is specified in
full; phases 2–4 are specified to the level needed to keep phase 1's outputs compatible.

## 0. Revisions after the first trials (2026-09-25)

These supersede the sections below where they conflict.

1. **Feedback is by position, not membership.** The blind rule ("letter anywhere in the word")
   can teach which letters are in a word but never their order. The fly got stuck on
   "creatures" after 8.5M attempts; "substantial" was estimated at 13 days. Owen chose:
   small hit only for a letter in the right place, never "right letter, wrong place".
   Misses are still punished (without punishment it stalled on "contracted" at 2M attempts).
2. **Memory has compartments, as in the real mushroom body.**
   - Short-term (γ lobe): reward and punishment, one-trial learning, τ = 1 h of fly time.
   - Long-term (α lobe): reward only, slow (η = 0.05), τ = 7 days.
   - Forgetting runs on fly time, at 0.3 s per keypress.
3. **The input is a sliding window** over the last 8 typed characters, plus the word length
   and the position in the word. The absolute position slots let punishment at "creat_"
   bleed into "crea_" and wiped out the correct "t". With the window, learning carries
   across words: mean attempts per word fell 96 → 54 over the first 5,000 words.
4. **A room of flies** (`room.py`). N flies (default 1000) with separate brains, and every
   fly types everything: a race. The winner has the fewest keypresses, which means the
   first to finish in fly time. Speed is `real` (0.3 s per keypress per fly, ~2.7 years for
   the works) or `max`, and it is switched live through `control.json`
   (`flyspeare ctl DIR --speed/--pause/--go`). Room flies write one `words.csv` row per
   1,000 words.

5. **Difficulty: the realistic fly, calibrated to about a week.** One easy fly at max speed
   finishes in ~2.1 h. Owen wanted about a week (~80× harder), made harder only by real fly
   limits (slipping feet and unreliable dopamine were tried and judged unfair; both remain as
   optional flags, off by default). The CLI defaults are:
   - no length cue: the fly only learns a word is over when the bell rings;
   - a working memory of the last 4 keypresses;
   - choice noise τ = 0.2, so a fully learned key is chosen ~83% of the time, like a trained
     fly in a T-maze;
   - short-term learning η = 0.065 per dopamine pulse. One pulse is far smaller than a real
     conditioning trial.
   Calibration on the opening 500 words: η = 0.06 → 90×, η = 0.10 → 37×, so 0.065 ≈ 80×.
   `--easy` restores the original fly.

6. **Real wiring and the real dopamine mechanism** (the default since 2026-09-25).
   - **Wiring:** the right-hemisphere PN→KC connectome from FlyWire v783. That is 168
     olfactory projection neurons, 2,456 Kenyon cells with olfactory input, and 149,906
     synapses, with a median of 6 PN inputs per KC. Each input channel drives one real PN.
     Every fly shares the real wiring but maps its senses onto PNs differently (by seed).
     Real KC, PN, DAN and MBON positions go into `brain.json` for the brain map.
   - **Dopamine only depresses.** Each key has an approach and an avoid MBON:
     - reward (PAM) depresses KC→avoid synapses;
     - punishment (PPL1) depresses KC→approach synapses;
     - forgetting is recovery toward rest.
   - Recalibrated to η = 0.09 (~80× the easy fly, ~7.2 days at 37.8k presses/s).
   - `--wiring random` keeps the statistical wiring.

7. **The viewer** (`flyspeare view`, http://127.0.0.1:8765). Phases 2 and 3 were built together
   as one 9:16 page in the style of the meliwat.lifts reference videos.
   - **3D fly:** the real NeuroMechFly body (flygym's MuJoCo meshes and skeleton, exported by
     `export_fly.py`) sits upright on a stool and types with its front legs. Each key the brain
     chose is reached with inverse kinematics over the real leg joints. This is animation
     driven by the brain's choices, not a physics simulation.
   - **Brain map:** real FlyWire positions. A whole-brain outline, 2,456 KCs, 168 PNs, and
     PAM/PPL1 DANs light up from the model's actual activity per keypress.
   - **Paper:** the original text, with struck-out attempts.
   - **Controls:** speed and pause (live), fly picker or follow the leader, save now, and
     stop/load rooms.
   - **Rooms outlive the viewer:** a room saves its own settings, so loading one restores
     every brain and resumes.
   - **Watching at max speed:** the viewer samples the newest attempts rather than every one.

8. **The real output layer, a fly's day, and states that act** (2026-09-26; the default for
   new rooms, while older rooms keep their brain).
   - **MBONs from FlyWire** (`mbon.py`). There are 29 MBON types with ≥20 Kenyon-cell inputs
     (right hemisphere), wired with their real KC→MBON synapse counts (79,843 synapses). The
     calyx MBON22 is excluded because it has no dopamine input.
     - Each type's dopamine cluster comes from the anatomy (Aso 2014, Li 2020): PAM or PPL1.
     - Its memory phase comes from which Kenyon-cell lobe feeds it: γ short-term (τ 1 h),
       α′β′ middle-term (τ 6 h), αβ long-term (τ 7 d).
     - PAM MBONs drive avoidance and PPL1 MBONs drive approach.
     - Dopamine only depresses, and only in its own compartments.
     - The 26 keys remain a downstream model: each MBON carries 26 action channels.
   - **A fly's day** (`run.py`, `inner.py`).
     - It wakes at 08:00, eats at 08:00 and 18:00, and sleeps 22:00–08:00.
     - Sleep replays the day's rewarded moments into the αβ (long-term) compartments. It drains
       sleep pressure and lets the body recover.
     - At real fly speed a night takes a real night. At max speed it takes only the replay.
   - **States change behaviour.**
     - Fatigue makes presses take longer (in fly time) and choices noisier.
     - Sleep pressure above 50% makes choices noisier.
     - Hunger scales reward (0.6× fed to 1.4× starving).
     - Helplessness adds up to 2 s of fly-time pause after each failure.
   - **Autosave** every 5 minutes (every 15 for rooms over 50 flies).
   - **Speed:** about 15,500 keys/s for one fly with the real MBONs, against about 30,000 with the
     per-key layer, because each press sums ~1,000 real KC→MBON synapses.
   - **Recalibrated to about a week.** Choice noise is the lever: τ 0.16 gives 21×, 0.18 gives
     32×, 0.20 about 570× the easy fly, on the opening words (η 0.25). The default is τ 0.18,
     so 32 × 300M keypresses at 15,550/s ≈ 7.1 days. A fully learned key is then chosen ~93% of
     the time: a little surer than trained flies (~70–85%), a trade-off for a one-week run.
9. **"How do you feel?"** (`feelings.py`) captures one moment. The fly speaks in fly words built
   from measurements (sweet = PAM, sting = PPL1, ding = the bell). Its strongest built-up states
   lead, and each line carries its evidence.

## 1. Goal

A virtual fruit fly learns to type on a typewriter, and is made to keep typing until it has
written the Complete Works of Shakespeare, in order, word by word. It learns only from
dopamine: a big hit for a correct word, small hits for letters that belong in the word. The
run is watched on a Reels-style 9:16 page: a 3D fly at the typewriter, a live map of its
brain firing, and the paper filling up.

It is for Owen's curiosity — it should *look* like the viral fly videos, but what the brain
map shows must be true: every flicker is a real activation in the model that is choosing the
keys.

## 2. Non-goals

- The full 139k-neuron FlyWire whole-brain simulation. It has no plasticity and cannot learn;
  the learner is the mushroom body alone (§5), and the brain map says so.
- Capitals, punctuation, line breaks as typed keys. They are printed on the paper for show,
  but the fly never types them (§4).
- Physics during learning. The body is only simulated to replay what the brain already did
  (§8).
- A stall cap. Decided: no cap for now; measure how bad it gets (§4.4).
- The earlier meme scenarios (reels, lactic acid, gym). Parked; may return as a separate spec.

## 3. Decisions taken, and why

| Decision | Choice | Reason |
|---|---|---|
| What "writes all of Shakespeare" means | Retry each word until correct, in text order | Guaranteed to finish in principle; learning shows as fewer attempts per word |
| Unit of checking | The word, typed letter by letter | Owen's rule: when the attempt reaches the word's length it is checked; wrong → struck out, retry from the word's start |
| Reward | Big dopamine for a correct word; small dopamine per typed letter that occurs *anywhere* in the word; punishment for letters not in the word | Owen's rule: no placement information, so it must learn Shakespeare's patterns itself |
| Order | The real text order, no curriculum | Owen's rule |
| Stuck words | No cap | Owen: "try with no cap and see how much of an issue it becomes" |
| Keys | 26 lowercase letters | Keeps the problem about words, not punctuation |
| Brain | Mushroom body model, wired to FlyWire statistics | The fly's real learning centre, with real dopamine-gated plasticity; honest brain map |
| Learning vs body | Headless learning; physical replay for viewing | Physics at ~1 s per keypress would put Shakespeare at months |
| Compute | Mac (M4 Pro) first, rented VM for the long run later | Same plan as flychef |

## 4. The typewriter rules

### 4.1 Text

- The source is Project Gutenberg eBook #100, *The Complete Works of William Shakespeare*,
  with the Gutenberg header and licence stripped. It starts with the Sonnets ("From fairest
  creatures we desire increase…").
- **Target stream:** lowercase, split on anything that is not a–z. An apostrophe splits too
  ("'tis" → "tis"; "o'er" → "o", "er"). This is lossy by design.
- **Display stream:** the original text. Every target word maps to a character span in it,
  so the paper can show the capitals and punctuation around what the fly typed.

### 4.2 An attempt

1. The fly is at word *w*, which has length *L*. It knows *L*: the typewriter bell rings at
   the word's length, the way a typist hears the carriage bell.
2. It presses keys one at a time. Each press is a choice among 26 keys, made by the brain
   (§5).
3. After the *L*-th press the attempt is checked:
   - **Correct:** big dopamine (§4.3). The word is committed to the paper, and the fly moves
     to word *w+1*.
   - **Wrong:** the attempt is struck out on the paper, its presses are rewarded or punished
     (§4.3), and the fly starts word *w* again from the first letter.

### 4.3 Dopamine

These are delivered at the check, to the eligibility trace of each press in the attempt (§5.4).

| Event | Signal | To which presses |
|---|---|---|
| Correct word | `R_word` (big, default 1.0) | every press in the attempt |
| Wrong word, a press whose letter ∈ set(letters of *w*) | `r_letter` (small, default 0.1) | that press |
| Wrong word, a press whose letter ∉ set(letters of *w*) | `−p_letter` (punishment, default 0.05) | that press |

- Membership only, never position. A doubled letter is judged by membership alone, like any
  other letter.
- All three magnitudes are config values.

### 4.4 Stalls

There is no cap. The run tracks attempts on the current word, the worst stall so far, and the
distribution of attempts per word. A watchdog *reports* a stall past thresholds (1k, 10k,
100k attempts) but never intervenes. Whether to add a cap is a decision for after phase 1's
numbers.

## 5. The brain: a mushroom body model

The real mushroom body learns associations like this: sensory input goes through projection
neurons (PNs) to a large, sparse population of Kenyon cells (KCs). Dopamine neurons (DANs)
change the KC→output-neuron (MBON) synapses. The model keeps that structure.

### 5.1 Input: projection neurons

PN activity encodes the context of the next press, as one-hot blocks:

- the last 8 characters of the committed text (a–z plus a word-boundary symbol);
- the letters typed so far in this attempt, by position (up to 20 positions);
- the target length *L* (1–20, with 20+ binned);
- the current position in the word.

The fly does not see its earlier failed attempts. What it learns within a word's retries, it
learns through the plasticity itself.

### 5.2 Kenyon cells

- 2,000 KCs, roughly one hemisphere's worth.
- Each KC samples a fixed random 6–8 PN inputs. The number of inputs per KC follows the
  FlyWire claw-count distribution.
- Sparsity comes from k-winners-take-all at ~5% active. This stands in for APL feedback
  inhibition.
- The wiring is fixed at build time and seeded.

### 5.3 Output neurons: one per key

- There are 26 MBONs, one per key, each summing weighted input from the active KCs.
- The key is chosen by softmax over MBON drive at temperature τ, with a small floor
  probability for every key so exploration never dies.
- τ is a config value; annealing is optional.

### 5.4 Dopamine plasticity (three-factor rule)

- Each press leaves an eligibility trace: (the set of active KCs, the chosen key).
- At the check, each trace gets its signal from §4.3:
  - **Reward (PAM-like):** strengthens the synapses from those active KCs to the chosen key.
  - **Punishment (PPL1-like):** weakens them.
- Weights are clipped to [0, w_max].
- Updates are sparse: ~100 KCs × 1 key per press, which is cheap.

### 5.5 Speed

Pure numpy, CPU, single process. The target is ≥20k presses/s on the M4 Pro. A benchmark test
records the actual figure.

## 6. The run

- `flyspeare run --config … [--resume]` runs headless. It checkpoints every N words and on
  SIGINT. `--resume` continues exactly: weights, RNG state and position in the text. This
  follows flychef's lesson that an interrupted run should cost nothing.
- A deterministic seed gives the same run twice.
- **Terminal stats every few seconds:**
  - words completed / total, and % of Shakespeare;
  - attempts on the current word;
  - rolling mean attempts per word;
  - wrong-press rate;
  - worst stall;
  - presses/s.

### 6.1 Outputs (the contract phases 2–4 read)

- `runs/<id>/words.csv` — one row per completed word: index, word, attempts, presses, wall
  time, sim time.
- `runs/<id>/recent.jsonl` — a ring buffer of the last ~2,000 attempts in full detail: the
  typed string, per-press key probabilities, the active KC ids per press, and the dopamine
  signals. This is the viewer's replay source.
- `runs/<id>/checkpoints/` — weights and state.
- `runs/<id>/brain.json` — the fixed wiring (PN→KC), for the brain map.

Nothing stores every attempt of a long stall in full. `words.csv` summarises them.

## 7. Phase 2: the page (brain map and paper)

- A local web page served from the run directory. It tails `recent.jsonl` and replays at
  watchable speed. The layout is 9:16.
- **Brain map:** KCs, MBONs and DANs drawn at real FlyWire mushroom-body neuron positions. Model
  KC *i* is assigned to a real KC position. KCs flicker per press; DANs flash green on reward and
  red on punishment. It is labelled "mushroom body model — FlyWire positions".
- **Paper:** typewriter-style, with the original capitalisation and punctuation around the
  committed words. Strike-outs are shown for failed attempts, with a progress bar through
  the works.
- **Stats strip:** word *n* of *N*, tries on this word, and a dopamine counter.
- **Open item for the plan:** confirm the FlyWire public release (Codex, v783) gives mushroom-body
  neuron positions in a downloadable form. If it doesn't, fall back to a schematic layout, and
  label it as schematic.

## 8. Phase 3: the 3D fly

- The FlyGym fly from flychef (`flychef/fg`) stands on a typewriter keyboard asset. For each
  press in `recent.jsonl` it walks or reaches to that key and presses it. This replays the
  brain's choices; the body chooses nothing.
- The on-screen label says so.
- The render uses flychef's dark-stage lighting and three-quarter camera. Frames stream into
  the top of the phase 2 page.

## 9. Phase 4: clips and cloud

- **Clip export:** 9:16 MP4s of chosen moments (milestones, long words finally cracked), made
  from the same page layout.
- **Cloud:** the phase 1 run moves to a rented VM. That needs a Docker image, and resume
  across machines through the checkpoint format.

## 10. Testing

- **Text:** normaliser golden cases (apostrophes, hyphens, headers stripped), and
  target↔display span mapping.
- **Rules:** attempt checking, and the reward table in §4.3 applied to hand-made attempts,
  including doubled letters.
- **Brain:** KC sparsity is ~5%; the update touches only active KCs × the chosen key; a
  seeded run is deterministic.
- **Learning works:** on a toy corpus (a short repeated verse), mean attempts per word fall
  well below a frozen-weights baseline. This is the phase 1 proof.
- **Resume:** run N words, stop, resume, and get identical results to an uninterrupted run.
- **Benchmark:** presses/s is recorded, not asserted.

## 11. Phase 1 exit criteria

1. The toy-corpus learning test passes.
2. A run over the first 10,000 words of the Sonnets finishes, or is stopped with the stall
   data recorded.
3. A short report: attempts-per-word curve against the no-learning baseline, stall
   distribution, worst words, and presses/s. That report decides whether a stall cap is
   needed.

## 12. Repo layout (phase 1)

```
flyspeare/
  pyproject.toml
  src/flyspeare/
    text.py        # Gutenberg fetch, strip, target/display streams
    rules.py       # attempt check, reward table
    brain.py       # PN encoding, KC layer, MBONs, plasticity
    run.py         # loop, checkpoints, resume, stats, outputs
    cli.py
  tests/
  runs/            # gitignored
```
