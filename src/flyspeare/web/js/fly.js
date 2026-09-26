// The NeuroMechFly body (exported from flygym's MuJoCo model), posed sitting upright at a
// typewriter and typing with its front legs. Units are millimetres, +x forward, +z up,
// exactly as in the MuJoCo model; the caller places the whole fly in the scene.
import * as THREE from "three";

const ORANGE = new THREE.MeshStandardMaterial({ color: 0xe39a3b, roughness: 0.5, metalness: 0.08 });
const EYE = new THREE.MeshStandardMaterial({ color: 0xc8261b, roughness: 0.35, metalness: 0.05, emissive: 0x3a0503 });
const WING = new THREE.MeshPhysicalMaterial({
  color: 0xd9e6ff, roughness: 0.15, transmission: 0.6, transparent: true, opacity: 0.22,
  side: THREE.DoubleSide, depthWrite: false,
});
const DARK = new THREE.MeshStandardMaterial({ color: 0x8a5a22, roughness: 0.6 });

function materialFor(name) {
  if (name.endsWith("Eye")) return EYE;
  if (name.endsWith("Wing")) return WING;
  if (/Arista|Haltere|Tarsus[45]/.test(name)) return DARK;
  return ORANGE;
}

const q = (wxyz) => new THREE.Quaternion(wxyz[1], wxyz[2], wxyz[3], wxyz[0]); // MuJoCo w,x,y,z

export async function loadFly(base = "assets/") {
  const [meta, bin] = await Promise.all([
    fetch(base + "fly.json").then((r) => r.json()),
    fetch(base + "fly.bin").then((r) => r.arrayBuffer()),
  ]);
  return new Fly(meta, bin);
}

export class Fly {
  constructor(meta, bin) {
    this.root = new THREE.Group();
    this.bodies = meta.bodies.map((b, i) => {
      const g = i === 0 ? new THREE.Group() : new THREE.Group();
      g.name = b.name;
      g.userData.baseQuat = q(b.quat);
      g.position.fromArray(b.pos);
      g.quaternion.copy(g.userData.baseQuat);
      g.userData.joints = [];
      return g;
    });
    meta.bodies.forEach((b, i) => {
      if (i === 0) this.root.add(this.bodies[0]);
      else this.bodies[b.parent].add(this.bodies[i]);
    });
    this.byName = Object.fromEntries(this.bodies.map((b) => [b.name, b]));
    // hinge joints, in MuJoCo order within each body: body_quat * R(j1) * R(j2) * ...
    this.joints = {};
    for (const j of meta.joints) {
      const body = this.bodies[j.body];
      const joint = { name: j.name, axis: new THREE.Vector3().fromArray(j.axis), angle: 0, body };
      body.userData.joints.push(joint);
      this.joints[j.name.replace(/^joint_/, "")] = joint;
    }
    for (const gm of meta.geoms) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(bin, gm.verts[0], gm.verts[1] * 3), 3));
      geo.setIndex(new THREE.BufferAttribute(new Uint32Array(bin, gm.faces[0], gm.faces[1] * 3), 1));
      geo.computeVertexNormals();
      const mesh = new THREE.Mesh(geo, materialFor(gm.name));
      mesh.name = gm.name;
      mesh.position.fromArray(gm.pos);
      mesh.quaternion.copy(q(gm.quat));
      mesh.castShadow = !gm.name.endsWith("Wing");
      this.bodies[gm.body].add(mesh);
    }
    this._tmpQ = new THREE.Quaternion();
    this.sit();
  }

  set(name, angle) {
    const j = this.joints[name];
    if (j) j.angle = angle;
  }

  apply() {
    for (const b of this.bodies) {
      if (!b.userData.joints.length) continue;
      b.quaternion.copy(b.userData.baseQuat);
      for (const j of b.userData.joints) b.quaternion.multiply(this._tmpQ.setFromAxisAngle(j.axis, j.angle));
    }
  }

  // Sitting upright on the abdomen with mid and hind legs braced, front legs raised like arms.
  sit() {
    const deg = THREE.MathUtils.degToRad;
    for (const side of ["L", "R"]) {
      const s = side === "L" ? 1 : -1;
      // The body is pitched nearly upright, so "backwards along the body" is now "down".
      // hind legs: tucked down along the abdomen onto the seat, knees out to the side
      this.set(`${side}HCoxa`, deg(80)); this.set(`${side}HCoxa_roll`, deg(35 * s));
      this.set(`${side}HFemur`, deg(-60)); this.set(`${side}HTibia`, deg(95));
      this.set(`${side}HTarsus1`, deg(-30));
      // middle legs: out to the sides and down onto the seat edge
      this.set(`${side}MCoxa`, deg(55)); this.set(`${side}MCoxa_roll`, deg(60 * s));
      this.set(`${side}MFemur`, deg(-70)); this.set(`${side}MTibia`, deg(95));
      this.set(`${side}MTarsus1`, deg(-30));
      // front legs: arms held out towards the keys, elbows bent
      this.rest[side] = { yaw: deg(-6 * s), coxa: deg(-25), roll: deg(10 * s), femur: deg(-55), tibia: deg(75) };
      this.setArm(side, this.rest[side]);
      for (let t = 1; t <= 5; t++) this.set(`${side}FTarsus${t}`, deg(t === 1 ? -25 : -10));
    }
    this.apply();
  }

  get rest() {
    return (this._rest ||= {});
  }

  setArm(side, a) {
    this.set(`${side}FCoxa_yaw`, a.yaw);
    this.set(`${side}FCoxa`, a.coxa);
    this.set(`${side}FCoxa_roll`, a.roll);
    this.set(`${side}FFemur`, a.femur);
    this.set(`${side}FTibia`, a.tibia);
  }

  // Foot tip (end of the last tarsal segment) in world coordinates.
  footWorld(side, out = new THREE.Vector3(), leg = "F") {
    const t5 = this.byName[`${side}${leg}Tarsus5`];
    t5.updateWorldMatrix(true, false);
    return out.set(0.006, 0, -0.12).applyMatrix4(t5.matrixWorld);
  }

  // Solve the front leg to put the foot on `targetWorld` (cyclic coordinate descent over the
  // leg's own joints, within loose anatomical limits). Returns the arm angles it found.
  reach(side, targetWorld, iters = 14, leg = "F") {
    const L = `${side}${leg}`;
    const names = [`${L}Coxa`, `${L}Coxa_yaw`, `${L}Coxa_roll`, `${L}Femur`, `${L}Tibia`];
    const lim = leg === "F" ? {
      [`${L}Coxa`]: [-2.2, 0.6], [`${L}Coxa_yaw`]: [-0.9, 0.9], [`${L}Coxa_roll`]: [-1.2, 1.2],
      [`${L}Femur`]: [-2.4, 0.3], [`${L}Tibia`]: [0.1, 2.6],
    } : {
      [`${L}Coxa`]: [-0.5, 2.0], [`${L}Coxa_yaw`]: [-0.9, 0.9], [`${L}Coxa_roll`]: [-1.4, 1.4],
      [`${L}Femur`]: [-2.4, 0.3], [`${L}Tibia`]: [0.1, 2.6],
    };
    const foot = new THREE.Vector3(), pivot = new THREE.Vector3(), axisW = new THREE.Vector3();
    const toFoot = new THREE.Vector3(), toTarget = new THREE.Vector3(), mq = new THREE.Quaternion();
    for (let it = 0; it < iters; it++) {
      for (let k = names.length - 1; k >= 0; k--) {
        const j = this.joints[names[k]];
        this.apply();
        j.body.updateWorldMatrix(true, false);
        this.footWorld(side, foot, leg);
        pivot.setFromMatrixPosition(j.body.matrixWorld);
        // the joint axis in world space: body's parent frame * base quat * earlier joints
        j.body.getWorldQuaternion(mq);
        // undo this joint and the ones after it to get the frame the axis is expressed in
        const js = j.body.userData.joints;
        for (let n = js.length - 1; n >= js.indexOf(j); n--) {
          mq.multiply(this._tmpQ.setFromAxisAngle(js[n].axis, -js[n].angle));
        }
        axisW.copy(j.axis).applyQuaternion(mq).normalize();
        toFoot.subVectors(foot, pivot).projectOnPlane(axisW);
        toTarget.subVectors(targetWorld, pivot).projectOnPlane(axisW);
        if (toFoot.lengthSq() < 1e-8 || toTarget.lengthSq() < 1e-8) continue;
        let d = toFoot.angleTo(toTarget);
        if (new THREE.Vector3().crossVectors(toFoot, toTarget).dot(axisW) < 0) d = -d;
        const [lo, hi] = lim[names[k]];
        j.angle = THREE.MathUtils.clamp(j.angle + d * 0.7, lo, hi);
      }
    }
    this.apply();
    return {
      yaw: this.joints[`${L}Coxa_yaw`].angle, coxa: this.joints[`${L}Coxa`].angle,
      roll: this.joints[`${L}Coxa_roll`].angle, femur: this.joints[`${L}Femur`].angle,
      tibia: this.joints[`${L}Tibia`].angle,
    };
  }

  // small idle motion so the fly never looks frozen: breathing abdomen, antennae twitch
  idle(t) {
    this.set("LFuniculus", 0.15 * Math.sin(t * 1.7));
    this.set("RFuniculus", 0.15 * Math.sin(t * 1.9 + 1));
    this.set("LWing_pitch", 0.02 * Math.sin(t * 0.8));
  }
}

export function lerpArm(a, b, t) {
  const o = {};
  for (const k of Object.keys(a)) o[k] = a[k] + (b[k] - a[k]) * t;
  return o;
}
