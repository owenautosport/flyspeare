"""Export the NeuroMechFly body (flygym's MuJoCo model) for the browser.

Writes web/assets/fly.json (the body tree, joints and geoms) and web/assets/fly.bin (mesh
vertices float32, faces uint32). The fly on screen is then the real NeuroMechFly model,
posed and animated joint by joint.

  python -m flyspeare.export_fly [path/to/flygym/data]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

WEB = Path(__file__).parent / "web" / "assets"
MJCF = "mjcf/neuromechfly_seqik_kinorder_ypr.xml"


def find_flygym_data() -> Path:
    """flygym's data folder: $FLYGYM_DATA, or the installed flygym package."""
    import os
    if os.environ.get("FLYGYM_DATA"):
        return Path(os.environ["FLYGYM_DATA"])
    try:
        import importlib.util
        spec = importlib.util.find_spec("flygym")
        if spec and spec.origin:
            return Path(spec.origin).parent / "data"
    except ImportError:
        pass
    raise SystemExit("The 3D fly needs NeuroMechFly's body from flygym: `pip install flygym` "
                     "(or set FLYGYM_DATA to its data folder), then run `python -m flyspeare.export_fly`.")


def export(flygym_data: Path | None = None, out: Path = WEB) -> Path:
    import mujoco

    flygym_data = flygym_data or find_flygym_data()
    m = mujoco.MjModel.from_xml_path(str(flygym_data / MJCF))
    name = lambda kind, i: mujoco.mj_id2name(m, kind, i)
    bodies = [{"name": name(mujoco.mjtObj.mjOBJ_BODY, i) or "world",
               "parent": int(m.body_parentid[i]),
               "pos": m.body_pos[i].tolist(), "quat": m.body_quat[i].tolist()}  # quat: w, x, y, z
              for i in range(m.nbody)]
    joints = [{"name": name(mujoco.mjtObj.mjOBJ_JOINT, j), "body": int(m.jnt_bodyid[j]),
               "type": int(m.jnt_type[j]), "axis": m.jnt_axis[j].tolist(), "pos": m.jnt_pos[j].tolist(),
               "range": m.jnt_range[j].tolist()} for j in range(m.njnt)]
    chunks, geoms, offset = [], [], 0
    for g in range(m.ngeom):
        mid = int(m.geom_dataid[g])
        if m.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH or mid < 0:
            continue
        v0, nv = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        f0, nf = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        verts = m.mesh_vert[v0:v0 + nv].astype(np.float32)
        faces = m.mesh_face[f0:f0 + nf].astype(np.uint32)
        geoms.append({"name": name(mujoco.mjtObj.mjOBJ_GEOM, g) or name(mujoco.mjtObj.mjOBJ_MESH, mid),
                      "body": int(m.geom_bodyid[g]), "pos": m.geom_pos[g].tolist(),
                      "quat": m.geom_quat[g].tolist(), "rgba": m.geom_rgba[g].tolist(),
                      "verts": [offset, int(nv)], "faces": [offset + verts.nbytes, int(nf)]})
        chunks += [verts.tobytes(), faces.tobytes()]
        offset += verts.nbytes + faces.nbytes
    out.mkdir(parents=True, exist_ok=True)
    (out / "fly.bin").write_bytes(b"".join(chunks))
    _export_lowpoly(m, geoms, b"".join(chunks), out)
    (out / "fly.json").write_text(json.dumps({"source": "NeuroMechFly (flygym) " + MJCF,
                                              "bodies": bodies, "joints": joints, "geoms": geoms}))
    return out / "fly.json"


def _export_lowpoly(m, geoms, blob: bytes, out: Path, keep: float = 0.015) -> None:
    """The same body at ~1.5% of the triangles, for drawing a crowd of flies (fly_lo.*)."""
    import fast_simplification

    chunks, lo, offset = [], [], 0
    for g in geoms:
        o, nv = g["verts"]
        fo, nf = g["faces"]
        verts = np.frombuffer(blob, np.float32, nv * 3, o).reshape(-1, 3)
        faces = np.frombuffer(blob, np.uint32, nf * 3, fo).reshape(-1, 3)
        if nf > 60:
            verts, faces = fast_simplification.simplify(verts, faces, target_reduction=1 - keep)
        verts = np.ascontiguousarray(verts, dtype=np.float32)
        faces = np.ascontiguousarray(faces, dtype=np.uint32)
        lo.append({**g, "verts": [offset, int(len(verts))], "faces": [offset + verts.nbytes, int(len(faces))]})
        chunks += [verts.tobytes(), faces.tobytes()]
        offset += verts.nbytes + faces.nbytes
    (out / "fly_lo.bin").write_bytes(b"".join(chunks))
    (out / "fly_lo.json").write_text(json.dumps({"geoms": lo}))


if __name__ == "__main__":
    p = export(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print("wrote", p, "and fly.bin", (p.parent / "fly.bin").stat().st_size // 1024, "KB")
