"""A mushroom-body model: the fly's learning centre (spec §5).

context -> projection neurons (PNs) -> Kenyon cells (KCs, sparse) -> output neurons (MBONs)
-> softmax choice. Dopamine changes only KC->MBON synapses, and only for the KCs that were
active when the rewarded or punished key was pressed.

Wiring: "flywire" uses the real right-hemisphere PN->KC connectome (synapse counts, FlyWire
v783); each input channel drives one real projection neuron, as an odour drives a glomerulus.
"random" draws wiring with the same statistics.

Dopamine only ever weakens synapses, as in the real fly. Each key has an approach MBON and an
avoid MBON; the key's drive is approach minus avoid.
  reward (PAM)       depresses active KC -> avoid-MBON synapses:    the key is favoured
  punishment (PPL1)  depresses active KC -> approach-MBON synapses: the key is disfavoured
Forgetting is recovery: depressed synapses relax back to their resting strength.

Memory is split into compartments, as in the real mushroom body, each with its own dopamine
inputs, learning rate and forgetting time:
  short-term (gamma lobe): reward and punishment, one-trial learning, fades within ~an hour.
  long-term  (alpha lobe): reward only (PAM), slow, needs repetition, lasts days.
Punishment therefore cannot erase what the long-term store has learned.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rules import ALPHABET

CTX_CHARS = ALPHABET + " "  # committed-text context: letters plus a word boundary
N_KEYS = len(ALPHABET)


FLY_SECONDS_PER_PRESS = 0.3  # a fly walking to a key and pressing it
APPROACH, AVOID = 0, 1


@dataclass(frozen=True)
class Compartment:
    name: str
    learns_from: str    # "both" (reward and punishment) or "reward"
    eta: float          # plasticity rate
    tau_s: float        # forgetting time constant, in fly seconds
    gain: float = 1.0   # weight of this compartment's MBONs in the choice


SHORT_TERM = Compartment("short-term", "both", eta=1.0, tau_s=3600.0)
LONG_TERM = Compartment("long-term", "reward", eta=0.05, tau_s=7 * 86400.0)


@dataclass(frozen=True)
class BrainConfig:
    ctx_len: int = 8        # sliding window: the last N characters typed
    max_pos: int = 20       # word positions / lengths encoded; longer ones share the last slot
    wiring: str = "random"  # "flywire": the real connectome; "random": same statistics
    n_kc: int = 2000        # random wiring only; FlyWire's right hemisphere has 2,456 with olfactory input
    claws: tuple[int, ...] = (6, 7, 8)  # random wiring only: PN inputs per KC (FlyWire median: 6)
    active_frac: float = 0.05  # k-winners-take-all: 5% of KCs fire, standing in for APL inhibition
    w0: float = 0.5         # resting KC->MBON weight; dopamine depresses it towards 0
    eta: float = 1.0        # global plasticity multiplier; 0 freezes the brain (no-learning baseline)
    tau: float = 0.05       # softmax temperature over MBON drive
    compartments: tuple[Compartment, ...] = (SHORT_TERM, LONG_TERM)
    length_cue: bool = True  # False: the fly only learns a word is over when the bell rings
    output: str = "per_key"  # "mbon": the real FlyWire MBON types (mbon.py); "per_key": invented units
    floor: float = 0.001    # every key keeps at least this probability


class Brain:
    def __init__(self, cfg: BrainConfig = BrainConfig(), seed: int = 0):
        self.cfg = cfg
        c = cfg
        self._off_len = c.ctx_len * len(CTX_CHARS)
        self._off_pos = self._off_len + c.max_pos
        self.n_pn = self._off_pos + c.max_pos  # input channels

        rng = np.random.default_rng(seed)
        self.channel_to_pn = None  # which real projection neuron each input channel drives
        if c.wiring == "flywire":
            from . import flywire
            syn = flywire.load()["syn"]  # (real PNs, real KCs) synapse counts
            n_real = syn.shape[0]
            # each fly maps its senses onto the real PNs differently
            self.channel_to_pn = (rng.permutation(n_real)[:self.n_pn] if self.n_pn <= n_real
                                  else rng.integers(0, n_real, self.n_pn))
            self.pn_kc_w = syn[self.channel_to_pn].astype(np.float32)
            self.pn_to_kc = self.pn_kc_w > 0
        elif c.wiring == "random":
            self.pn_to_kc = np.zeros((self.n_pn, c.n_kc), dtype=bool)
            for k in range(c.n_kc):
                self.pn_to_kc[rng.choice(self.n_pn, rng.choice(c.claws), replace=False), k] = True
            # Synapse strengths vary, so KCs rarely tie.
            self.pn_kc_w = np.where(self.pn_to_kc, rng.uniform(0.5, 1.5, self.pn_to_kc.shape),
                                    0.0).astype(np.float32)
        else:
            raise ValueError(f"unknown wiring {c.wiring!r}")
        self.n_kc = self.pn_kc_w.shape[1]
        self.n_active = max(1, round(c.active_frac * self.n_kc))
        # (compartment, approach/avoid, KC, key)
        self.w = np.full((len(c.compartments), 2, self.n_kc, N_KEYS), c.w0, dtype=np.float32)
        self._gain = np.array([k.gain for k in c.compartments])

    # -- sensing ---------------------------------------------------------------------------
    def encode(self, context: str, prefix: str, length: int) -> np.ndarray:
        """Active PN indices for: the last few characters typed (a sliding window over the
        committed text and this attempt so far), the word's length, and the position in it.

        The window is relative ("one back", "two back", ...), so what follows "th" is learned
        once and reused in every word, and neighbouring positions of one word do not blur.
        """
        c = self.cfg
        window = (context + prefix)[-c.ctx_len:].rjust(c.ctx_len)
        idx = [i * len(CTX_CHARS) + CTX_CHARS.index(ch) for i, ch in enumerate(window)]
        if c.length_cue:
            idx.append(self._off_len + min(length, c.max_pos) - 1)
        idx.append(self._off_pos + min(len(prefix), c.max_pos - 1))
        return np.unique(np.array(idx))

    def kcs(self, pns: np.ndarray) -> np.ndarray:
        drive = self.pn_kc_w[pns].sum(axis=0)
        return np.sort(np.argpartition(drive, -self.n_active)[-self.n_active:])

    # -- choosing --------------------------------------------------------------------------
    def probs(self, kcs: np.ndarray, noise: float = 1.0) -> np.ndarray:
        m = self.w[:, :, kcs].mean(axis=2)            # (compartment, approach/avoid, key)
        drive = self._gain @ (m[:, APPROACH] - m[:, AVOID])
        logits = drive / (self.cfg.tau * noise)
        e = np.exp(logits - logits.max())
        return (1 - N_KEYS * self.cfg.floor) * e / e.sum() + self.cfg.floor

    # -- dopamine --------------------------------------------------------------------------
    def learn(self, traces: list[tuple[np.ndarray, int]], signals: list[float], gain: float = 1.0) -> None:
        """Three-factor rule: active KC x chosen key x dopamine, depression only.

        Reward depresses the avoid synapses, punishment the approach synapses, each by a
        fraction eta*|signal| of what is left.
        """
        if self.cfg.eta == 0:
            return
        for (kcs, key), s in zip(traces, signals):
            if s == 0:
                continue
            valence = AVOID if s > 0 else APPROACH
            amt = abs(s) * (gain if s > 0 else 1.0)       # hunger makes reward count for more
            for i, comp in enumerate(self.cfg.compartments):
                if s < 0 and comp.learns_from == "reward":
                    continue
                self.w[i, valence, kcs, key] *= 1 - min(1.0, self.cfg.eta * comp.eta * amt)

    def consolidate(self, replay: list, strength: float = 1.0) -> int:
        """Sleep: replay the day's rewarded moments into the long-term compartment."""
        names = [c.name for c in self.cfg.compartments]
        if "long-term" not in names:
            return 0
        i, lt = names.index("long-term"), self.cfg.compartments[names.index("long-term")]
        for kcs, key, s in replay:
            self.w[i, AVOID, kcs, key] *= 1 - min(1.0, self.cfg.eta * lt.eta * s * strength * 4)
        return len(replay)

    def memory_state(self) -> dict:
        names = [c.name for c in self.cfg.compartments]
        dep = lambda comp, v: round(float(1 - self.w[names.index(comp), v].mean() / self.cfg.w0), 5) if comp in names else 0.0
        return {"st_reward": dep("short-term", AVOID), "st_punish": dep("short-term", APPROACH),
                "lt_reward": dep("long-term", AVOID)}

    def elapse(self, fly_seconds: float) -> None:
        """Forgetting: every depressed synapse recovers toward rest at its compartment's rate."""
        w0 = self.cfg.w0
        for i, comp in enumerate(self.cfg.compartments):
            self.w[i] -= (self.w[i] - w0) * (1 - np.exp(-fly_seconds / comp.tau_s))


def make_brain(cfg: BrainConfig, seed: int = 0) -> Brain:
    """The invented per-key output units (older rooms), or the real FlyWire MBONs."""
    if cfg.output == "mbon":
        from .mbon import MBBrain
        return MBBrain(cfg, seed)
    return Brain(cfg, seed)
