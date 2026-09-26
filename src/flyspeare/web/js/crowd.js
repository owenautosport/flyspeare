// The hall: every fly in a room, each at its own desk and typewriter, drawn with GPU
// instancing from a low-poly copy of the same NeuroMechFly body (fly_lo.*), in the same
// seated pose as the fly being watched. Each fly is coloured by how far it has typed: dim
// flies are behind, bright orange ones ahead, the leader gold, the watched fly cyan.
import * as THREE from "three";

const SPACING_X = 7.5, SPACING_Y = 6.5, FIRST_ROW_X = 9;

export async function loadCrowd(stage, base = "assets/") {
  const [meta, bin] = await Promise.all([
    fetch(base + "fly_lo.json").then((r) => r.json()),
    fetch(base + "fly_lo.bin").then((r) => r.arrayBuffer()),
  ]);
  return new Crowd(stage, meta, bin);
}

export class Crowd {
  constructor(stage, meta, bin) {
    this.stage = stage;
    this.group = new THREE.Group();
    this.group.visible = false;
    stage.scene.add(this.group);
    this.n = 0;
    this.meshes = [];
    // each low-poly part's pose relative to the seated fly's holder, taken from the hi-res fly
    const hero = stage.fly, holder = stage.flyHolder;
    hero.setArm("L", hero.rest.L); hero.setArm("R", hero.rest.R); hero.apply();
    holder.updateWorldMatrix(true, true);
    const toHolder = new THREE.Matrix4().copy(holder.matrixWorld).invert();
    const byName = {};
    hero.root.traverse((o) => { if (o.isMesh) byName[o.name] = o; });
    this.parts = meta.geoms.map((g) => {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(bin, g.verts[0], g.verts[1] * 3), 3));
      geo.setIndex(new THREE.BufferAttribute(new Uint32Array(bin, g.faces[0], g.faces[1] * 3), 1));
      geo.computeVertexNormals();
      const src = byName[g.name];
      const rel = new THREE.Matrix4().multiplyMatrices(toHolder, src.matrixWorld);
      const kind = g.name.endsWith("Eye") ? "eye" : g.name.endsWith("Wing") ? "wing" : "body";
      return { geo, rel, kind };
    });
    this.holderMatrix = holder.matrixWorld.clone();       // where the hero's body sits
    this.propGeos = this._props();
    this.colors = { body: new THREE.Color(), dim: new THREE.Color(0x5a4a38), lead: new THREE.Color(0xffc24a),
                    mid: new THREE.Color(0xe39a3b), watched: new THREE.Color(0x5ff3ff) };
  }

  // a simplified desk + typewriter + stool for each seat
  _props() {
    const box = (sx, sy, sz, x, y, z) => new THREE.BoxGeometry(sx, sy, sz).translate(x, y, z);
    const cyl = (r, h, x, y, z) => new THREE.CylinderGeometry(r, r, h, 16).rotateX(Math.PI / 2).translate(x, y, z);
    const tw = this.stage.tw.group.position, deskTop = tw.z;
    return {
      dark: mergeGeometries([
        box(2.2, 4.4, deskTop, 0.85, 0, deskTop / 2),                       // desk
        box(1.0, 3.2, 0.25, tw.x + 0.55, 0, tw.z + 0.05),                   // deck
        box(0.8, 3.8, 0.95, tw.x + 1.45, 0, tw.z + 0.42),                   // housing
        cyl(0.55, 0.48, -1.35, 0, 0.24),                                    // stool
      ]),
      platen: mergeGeometries([new THREE.CylinderGeometry(0.22, 0.22, 4.3, 16).translate(0, 0, 0)
        .translate(tw.x + 1.6, 0, tw.z + 1.0)]),
      paper: new THREE.PlaneGeometry(3.4, 3.0).rotateX(Math.PI / 2).rotateZ(Math.PI / 2).translate(tw.x + 1.65, 0, tw.z + 2.7),
    };
  }

  seat(i) {  // row-major hall of desks in front of the watched fly, all facing the same way
    const cols = Math.ceil(Math.sqrt(this.n * 1.6));
    const r = Math.floor(i / cols), c = i % cols;
    return new THREE.Vector3(FIRST_ROW_X + r * SPACING_X, (c - (cols - 1) / 2) * SPACING_Y, 0);
  }

  // (re)build the instances for a room of n flies
  setFlies(n) {
    if (n === this.n) return;
    for (const m of this.meshes) { this.group.remove(m); m.dispose(); }
    this.meshes = [];
    this.n = n;
    this.group.visible = n > 1;
    if (n <= 1) { this.stage.scene.fog.near = 14; this.stage.scene.fog.far = 30; return; }
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.55 });
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0xb8231a, roughness: 0.4 });
    const wingMat = new THREE.MeshStandardMaterial({ color: 0xd9e6ff, transparent: true, opacity: 0.18, depthWrite: false, side: THREE.DoubleSide });
    const m = new THREE.Matrix4(), t = new THREE.Matrix4();
    const holderAt = (i) => t.makeTranslation(this.seat(i)).multiply(this.holderMatrix);
    this.bodyMeshes = [];
    for (const p of this.parts) {
      const mat = p.kind === "eye" ? eyeMat : p.kind === "wing" ? wingMat : bodyMat;
      const im = new THREE.InstancedMesh(p.geo, mat, n);
      for (let i = 0; i < n; i++) im.setMatrixAt(i, m.multiplyMatrices(holderAt(i), p.rel));
      if (p.kind === "body") { im.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3); this.bodyMeshes.push(im); }
      im.frustumCulled = false;
      this.group.add(im); this.meshes.push(im);
    }
    const propMats = {
      dark: new THREE.MeshStandardMaterial({ color: 0x1c212c, roughness: 0.45, metalness: 0.4 }),
      platen: new THREE.MeshStandardMaterial({ color: 0x0b0c10, roughness: 0.7 }),
      paper: new THREE.MeshStandardMaterial({ color: 0xe9e3d3, roughness: 0.9, side: THREE.DoubleSide }),
    };
    for (const [k, geo] of Object.entries(this.propGeos)) {
      const im = new THREE.InstancedMesh(geo, propMats[k], n);
      for (let i = 0; i < n; i++) im.setMatrixAt(i, t.makeTranslation(this.seat(i)));
      im.frustumCulled = false;
      this.group.add(im); this.meshes.push(im);
    }
    // thinner fog so the rows stay visible, fading only at the far end of the hall
    this.stage.scene.fog.near = 60;
    this.stage.scene.fog.far = Math.max(120, this.seat(n - 1).length() * 1.2);
  }

  // colour every fly by progress; the watched fly glows cyan, the leader gold
  update(flies, watched) {
    if (!this.bodyMeshes?.length) return;
    const best = Math.max(1, ...flies.map((f) => f.word));
    const lead = flies.reduce((a, f) => (f.word > a.word ? f : a), flies[0]);
    const c = this.colors.body;
    for (const f of flies) {
      if (f.id >= this.n) continue;
      if (f.id === watched) c.copy(this.colors.watched);
      else if (f.id === lead.id) c.copy(this.colors.lead);
      else c.copy(this.colors.dim).lerp(this.colors.mid, Math.min(1, f.word / best));
      for (const im of this.bodyMeshes) im.setColorAt(f.id, c);
    }
    for (const im of this.bodyMeshes) im.instanceColor.needsUpdate = true;
  }

  // a diagonal look across the hall from just behind the watched fly: the nearest rows are
  // large, the rest recede into the distance
  overview() {
    const far = this.seat(this.n - 1), halfW = Math.abs(this.seat(0).y);
    return { pos: [-10, -Math.min(halfW, 60) - 12, 26], target: [Math.min(far.x, 90) * 0.45, 0, 0] };
  }
}

// small local copy of BufferGeometryUtils.mergeGeometries for non-indexed/indexed boxes
function mergeGeometries(geos) {
  const parts = geos.map((g) => (g.index ? g.toNonIndexed() : g));
  const pos = [], nor = [];
  for (const g of parts) {
    pos.push(...g.attributes.position.array);
    nor.push(...g.attributes.normal.array);
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  out.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  return out;
}
