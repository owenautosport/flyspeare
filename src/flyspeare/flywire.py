"""The real mushroom-body wiring, from the FlyWire whole-brain connectome (v783).

Right hemisphere: olfactory projection neurons (ALPN) -> Kenyon cells, and Kenyon cells ->
mushroom body output neurons (MBONs, grouped by type), with synapse counts, plus soma
positions for the brain map. Built once from the public data and cached as a small
.npz, so a room of 1,000 flies loads it in milliseconds.

Sources:
  connectivity  github.com/philshiu/Drosophila_brain_model  (Connectivity_783.parquet)
  annotations   github.com/flyconnectome/flywire_annotations (Supplemental_file1)
"""
from __future__ import annotations

import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parents[2] / "data" / "flywire"
CACHE = DATA / "mb_right_783.npz"
SOURCES = {
    "Connectivity_783.parquet":
        "https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/main/Connectivity_783.parquet",
    "annotations.tsv":
        "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/"
        "supplemental_files/Supplemental_file1_neuron_annotations.tsv",
}


def _position(df) -> np.ndarray:
    """Soma position where FlyWire has one, else the neuron's representative point, in nm.

    Both columns are in FlyWire's 4 x 4 x 40 nm voxels.
    """
    voxel = np.array([4, 4, 40])
    soma = df[["soma_x", "soma_y", "soma_z"]].to_numpy(dtype=float) * voxel
    pos = df[["pos_x", "pos_y", "pos_z"]].to_numpy(dtype=float) * voxel
    return np.where(np.isnan(soma), pos, soma).astype(np.float32)


def build(data: Path = DATA) -> Path:
    import pandas as pd  # only needed once, to build the cache

    data.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        if not (data / name).exists():
            print(f"downloading {name} ...", flush=True)
            urllib.request.urlretrieve(url, data / name)

    ann = pd.read_csv(data / "annotations.tsv", sep="\t", low_memory=False,
                      usecols=["root_id", "cell_class", "cell_type", "side",
                               "soma_x", "soma_y", "soma_z", "pos_x", "pos_y", "pos_z"])
    right = ann[ann.side == "right"]
    kcs = right[right.cell_class == "Kenyon_Cell"]
    pns = ann[ann.cell_class == "ALPN"]
    conn = pd.read_parquet(data / "Connectivity_783.parquet",
                           columns=["Presynaptic_ID", "Postsynaptic_ID", "Connectivity"])
    edges = conn[conn.Postsynaptic_ID.isin(kcs.root_id) & conn.Presynaptic_ID.isin(pns.root_id)]

    kc_ids = np.array(sorted(edges.Postsynaptic_ID.unique()))  # KCs with olfactory input
    pn_ids = np.array(sorted(edges.Presynaptic_ID.unique()))
    kc_ix = {r: i for i, r in enumerate(kc_ids)}
    pn_ix = {r: i for i, r in enumerate(pn_ids)}
    syn = np.zeros((len(pn_ids), len(kc_ids)), dtype=np.float32)
    for pre, post, n in edges.itertuples(index=False):
        syn[pn_ix[pre], kc_ix[post]] += n

    by_id = ann.set_index("root_id")
    kc_meta = by_id.loc[kc_ids]
    pn_meta = by_id.loc[pn_ids]
    mbon = right[right.cell_class == "MBON"]
    dan = right[right.cell_class == "DAN"]
    # Kenyon cell -> MBON synapses, summed per MBON type (the unit the model learns in)
    mb_types = sorted(set(mbon.cell_type.astype(str)))
    type_of = dict(zip(mbon.root_id, mbon.cell_type.astype(str)))
    out = conn[conn.Presynaptic_ID.isin(kc_ids) & conn.Postsynaptic_ID.isin(mbon.root_id)]
    kc_mbon = np.zeros((len(kc_ids), len(mb_types)), dtype=np.float32)
    col = {t_: i for i, t_ in enumerate(mb_types)}
    for pre, post, n in out.itertuples(index=False):
        kc_mbon[kc_ix[pre], col[type_of[post]]] += n
    np.savez_compressed(
        CACHE if data == DATA else data / CACHE.name,
        syn=syn, kc_ids=kc_ids, pn_ids=pn_ids,
        kc_type=kc_meta.cell_type.astype(str).to_numpy().astype("U32"), kc_pos=_position(kc_meta),
        pn_type=pn_meta.cell_type.astype(str).to_numpy().astype("U32"), pn_pos=_position(pn_meta),
        mbon_type=mbon.cell_type.astype(str).to_numpy().astype("U32"), mbon_pos=_position(mbon),
        dan_type=dan.cell_type.astype(str).to_numpy().astype("U32"), dan_pos=_position(dan),
        # a faint whole-brain outline for the map: 20,000 neurons sampled from all 139k
        brain_pos=_position(ann.sample(20000, random_state=0)),
        kc_mbon=kc_mbon, mb_types=np.array(mb_types).astype("U32"),
    )
    return CACHE


@lru_cache(maxsize=1)
def load() -> dict[str, np.ndarray]:
    if not CACHE.exists():
        build()
    with np.load(CACHE, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}
