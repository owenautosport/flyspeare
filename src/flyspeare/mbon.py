"""The mushroom body's real output layer: MBON types from FlyWire, not invented units.

Each learning unit is a real MBON type (right hemisphere, FlyWire v783) with
  - its real Kenyon-cell inputs, weighted by their synapse counts;
  - its real dopamine input: PAM (reward) or PPL1 (punishment), from the anatomy
    (Aso et al. 2014; Li et al. 2020, the hemibrain mushroom body);
  - the memory timescale of its lobe: gamma short-term, alpha'beta' medium, alpha-beta
    long-term (the lobe is read from which Kenyon-cell types actually feed it).

Valence follows the real circuit: MBONs in PAM compartments drive avoidance, so reward (which
depresses their KC synapses) turns the fly towards the rewarded action; MBONs in PPL1
compartments drive approach, so punishment turns it away.

What is still a model: a fly chooses among 26 keys somewhere downstream of the mushroom body
(premotor circuits), not in the MBONs themselves. So each MBON unit carries 26 "action
channels": which key its output is currently bound to. Dopamine still only ever depresses
KC->MBON synapses, only in its own compartments.
"""
from __future__ import annotations

import numpy as np

from .brain import Brain, BrainConfig, N_KEYS
from .rules import ALPHABET

# MBON type -> dopamine cluster innervating its compartment(s). The calyx MBON (MBON22) has
# no dopaminergic compartment and is left out.
DAN_OF = {
    **{t: "PAM" for t in ["MBON01", "MBON02", "MBON03", "MBON04", "MBON05", "MBON06", "MBON07",
                          "MBON09", "MBON10", "MBON21", "MBON24", "MBON26", "MBON27", "MBON29"]},
    **{t: "PPL1" for t in ["MBON11", "MBON12", "MBON13", "MBON14", "MBON15", "MBON15-like", "MBON16",
                           "MBON17", "MBON17-like", "MBON18", "MBON19", "MBON20", "MBON23",
                           "MBON25,MBON34", "MBON28", "MBON30", "MBON31", "MBON32", "MBON33",
                           "MBON35"]},
}
MIN_KCS = 20                      # MBON types reached by fewer KCs carry no learnable signal here

# memory phase by lobe: plasticity rate multiplier and forgetting time (fly seconds)
PHASES = {
    "gamma": {"eta": 1.0, "tau_s": 3600.0},                # short-term
    "apbp": {"eta": 0.45, "tau_s": 6 * 3600.0},             # middle-term (alpha'beta')
    "ab": {"eta": 0.25, "tau_s": 7 * 86400.0},              # long-term, consolidated in sleep
}
LOBE_OF_KC = {"KCg": "gamma", "KCapbp": "apbp", "KCa'b'": "apbp", "KCab": "ab"}


def _lobe(kc_type: str) -> str:
    for prefix, lobe in LOBE_OF_KC.items():
        if kc_type.startswith(prefix):
            return lobe
    return "gamma"


class MBBrain(Brain):
    """Same senses and Kenyon cells as Brain; the output layer is the real MBONs."""

    def __init__(self, cfg: BrainConfig, seed: int = 0):
        super().__init__(cfg, seed)
        from . import flywire
        fw = flywire.load()
        syn, types, kc_type = fw["kc_mbon"], [str(t) for t in fw["mb_types"]], fw["kc_type"]
        keep = [i for i, t in enumerate(types) if t in DAN_OF and (syn[:, i] > 0).sum() >= MIN_KCS]
        self.unit_names = [types[i] for i in keep]
        self.unit_dan = np.array([DAN_OF[t] for t in self.unit_names])
        self.unit_sign = np.where(self.unit_dan == "PAM", -1.0, 1.0)   # PAM: avoid, PPL1: approach
        lobes = []
        for i in keep:                      # the lobe that supplies most of its KC input
            w = syn[:, i]
            votes = {}
            for kc in np.flatnonzero(w):
                votes[_lobe(str(kc_type[kc]))] = votes.get(_lobe(str(kc_type[kc])), 0) + w[kc]
            lobes.append(max(votes, key=votes.get))
        self.unit_lobe = np.array(lobes)
        self.unit_eta = np.array([PHASES[l]["eta"] for l in lobes])
        self.unit_tau = np.array([PHASES[l]["tau_s"] for l in lobes])
        # sparse KC->unit entries, grouped by KC so the active KCs' entries gather quickly
        entries = [(kc, u, syn[kc, i]) for u, i in enumerate(keep) for kc in np.flatnonzero(syn[:, i])]
        entries.sort()
        self.e_kc = np.array([e[0] for e in entries], dtype=np.int32)
        self.e_unit = np.array([e[1] for e in entries], dtype=np.int32)
        self.e_syn = np.array([e[2] for e in entries], dtype=np.float32)
        self.kc_ptr = np.searchsorted(self.e_kc, np.arange(self.n_kc + 1))
        self.n_units = len(keep)
        # the plastic synapses: one weight per (KC->MBON entry, action channel)
        self.w = np.full((len(entries), N_KEYS), cfg.w0, dtype=np.float32)
        self.e_eta = self.unit_eta[self.e_unit].astype(np.float32)
        self.e_tau = self.unit_tau[self.e_unit]
        self.e_pam = self.unit_dan[self.e_unit] == "PAM"
        self._ecache: dict[bytes, np.ndarray] = {}
        self._flat = np.arange(N_KEYS)

    def _prep(self, kcs: np.ndarray):
        """For one set of active KCs: their KC->MBON entries, and each entry's fixed share of
        the drive (its synapse count within its MBON, that MBON's sign, averaged per class), so
        a keypress is one matrix-vector product. Cached per KC set."""
        key = kcs.tobytes()
        hit = self._ecache.get(key)
        if hit is not None:
            return hit
        starts, ends = self.kc_ptr[kcs], self.kc_ptr[kcs + 1]
        lens = ends - starts
        e = np.repeat(starts - np.concatenate(([0], np.cumsum(lens)[:-1])), lens) + np.arange(lens.sum())
        units, syn = self.e_unit[e], self.e_syn[e]
        norm = np.bincount(units, weights=syn, minlength=self.n_units)
        live = norm > 0
        n_pam = int((live & (self.unit_sign < 0)).sum()) or 1
        n_ppl = int((live & (self.unit_sign > 0)).sum()) or 1
        per_unit = np.where(self.unit_sign < 0, 1.0 / n_pam, -1.0 / n_ppl) / np.where(live, norm, 1)
        coef = (syn * per_unit[units] / self.cfg.w0).astype(np.float32)
        pam = self.e_pam[e]
        out = (e, coef, e[pam], e[~pam])
        if len(self._ecache) > 8000:
            self._ecache.clear()
        self._ecache[key] = out
        return out

    def probs(self, kcs: np.ndarray, noise: float = 1.0) -> np.ndarray:
        # drive per key = mean depression over the active PAM (avoid) MBONs minus the mean over
        # the active PPL1 (approach) MBONs, each MBON's KCs weighted by real synapse counts.
        # Depressing an avoid MBON favours the key; depressing an approach MBON disfavours it.
        e, coef, _, _ = self._prep(kcs)
        drive = coef @ (self.cfg.w0 - self.w[e])
        logits = drive / (self.cfg.tau * noise)
        x = np.exp(logits - logits.max())
        return (1 - N_KEYS * self.cfg.floor) * x / x.sum() + self.cfg.floor

    def learn(self, traces, signals, gain: float = 1.0) -> None:
        """Reward depresses active KC synapses onto PAM-compartment MBONs; punishment onto
        PPL1-compartment MBONs; each at its own compartment's rate."""
        if self.cfg.eta == 0:
            return
        base = self.cfg.eta * self.cfg.compartments[0].eta   # the calibrated fast (gamma) rate
        for (kcs, key), s in zip(traces, signals):
            if s == 0:
                continue
            _, _, e_pam, e_ppl = self._prep(kcs)
            e = e_pam if s > 0 else e_ppl
            if not len(e):
                continue
            amt = base * abs(s) * (gain if s > 0 else 1.0) * self.e_eta[e]
            self.w[e, key] *= 1 - np.minimum(amt, 1.0)

    def elapse(self, fly_seconds: float) -> None:
        f = np.exp(-fly_seconds / self.e_tau).astype(np.float32)[:, None]
        self.w -= (self.w - self.cfg.w0) * (1 - f)

    def consolidate(self, replay: list, strength: float = 1.0) -> int:
        """Sleep: replay the day's rewarded moments into the long-term (alpha-beta) compartments."""
        base = self.cfg.eta * self.cfg.compartments[0].eta * strength
        n = 0
        for kcs, key, s in replay:
            _, _, e, _ = self._prep(kcs)
            e = e[self.unit_lobe[self.e_unit[e]] == "ab"]
            if len(e):
                self.w[e, key] *= 1 - np.minimum(base * s * self.e_eta[e] * 4, 1.0)
                n += 1
        return n

    def memory_state(self) -> dict:
        dep = 1 - self.w.mean(axis=1) / self.cfg.w0
        by = lambda mask: round(float(dep[mask].mean()), 5) if mask.any() else 0.0
        lobe = self.unit_lobe[self.e_unit]
        return {"st_reward": by((lobe == "gamma") & self.e_pam), "st_punish": by((lobe == "gamma") & ~self.e_pam),
                "lt_reward": by((lobe == "ab") & self.e_pam), "lt_punish": by((lobe == "ab") & ~self.e_pam),
                "mt": by(lobe == "apbp")}
