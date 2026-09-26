// Debug tool: does any part of the fly pass through the typewriter or the desk?
// Samples points on the fly's meshes (every Nth vertex) and tests them against the solid
// parts of the scene, in each part's own frame. Used by the automated checks, not the page.
import * as THREE from "three";

function solids(stage, exclude = null) {
  const out = [];
  const add = (root) => root.traverse((o) => {
    if (!o.isMesh || o === stage.tw.paper) return;
    if (exclude && isInside(o, exclude)) return;
    o.geometry.computeBoundingBox();
    out.push(o);
  });
  add(stage.tw.group);
  stage.scene.children.forEach((o) => { if (o.isMesh && o.userData.solid) { o.geometry.computeBoundingBox(); out.push(o); } });
  return out;
}
function isInside(o, ancestor) { for (let p = o; p; p = p.parent) if (p === ancestor) return true; return false; }

function flyPoints(fly, filter, step = 25) {
  const pts = [];
  fly.root.updateWorldMatrix(true, true);
  fly.root.traverse((o) => {
    if (!o.isMesh || !filter(o.name)) return;
    const pos = o.geometry.attributes.position;
    for (let i = 0; i < pos.count; i += step) {
      pts.push({ p: new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld), part: o.name });
    }
  });
  return pts;
}

// returns [{part, solid}] for every fly point inside a solid (with a small tolerance)
export function collisions(stage, { parts = () => true, exclude = null, tol = 0.004 } = {}) {
  const hits = [];
  const inv = new THREE.Matrix4(), local = new THREE.Vector3();
  const ss = solids(stage, exclude);
  for (const s of ss) s.updateWorldMatrix(true, false);
  for (const { p, part } of flyPoints(stage.fly, parts)) {
    for (const s of ss) {
      inv.copy(s.matrixWorld).invert();
      local.copy(p).applyMatrix4(inv);
      const b = s.geometry.boundingBox;
      if (local.x > b.min.x + tol && local.x < b.max.x - tol && local.y > b.min.y + tol &&
          local.y < b.max.y - tol && local.z > b.min.z + tol && local.z < b.max.z - tol) {
        hits.push({ part, solid: s.name || s.geometry.type });
        break;
      }
    }
  }
  return hits;
}

// Play every keypress (from rest and from every other key) through the real strike
// animation, checking for collisions at many moments, and where the foot lands.
export function checkAllStrikes(stage, samples = 14) {
  const ALPHA = "abcdefghijklmnopqrstuvwxyz";
  const f = stage.fly, report = { wrongKey: [], clips: [], worstMiss: 0 };
  const legParts = (n) => /F(Coxa|Femur|Tibia|Tarsus)/.test(n);
  const starts = [null, ...ALPHA];
  for (const ch of ALPHA) {
    for (const from of starts) {
      // start from rest, or from where the arm ends after pressing `from`
      stage.arm.L = { ...f.rest.L }; stage.arm.R = { ...f.rest.R };
      if (from) { const p = stage.solveStrike(from); stage.arm[p.side] = p.hover; }
      const st = stage.solveStrike(ch);
      if (from && stage.solveStrike(from).side !== st.side) continue; // other arm: independent
      for (let k = 0; k <= samples; k++) {
        const t = k / samples;
        const pose = stage.strikePose(st, t);
        f.setArm(st.side, pose.arm);
        f.setArm(st.side === "L" ? "R" : "L", f.rest[st.side === "L" ? "R" : "L"]);
        f.apply();
        // the foot may rest on the key it is pressing while pressing it
        const touching = t >= 0.45 && t <= 0.75;
        const hits = collisions(stage, { parts: legParts, exclude: touching ? stage.tw.keys[ch] : null });
        if (hits.length) { report.clips.push({ key: ch, from, t: +t.toFixed(2), n: hits.length, what: hits[0] }); break; }
      }
      if (from === null) {
        f.setArm(st.side, st.hit); f.apply();
        const foot = f.footWorld(st.side);
        let best = null, bd = 1e9;
        for (const k of ALPHA) { const d = foot.distanceTo(stage.tw.keyTop(k)); if (d < bd) { bd = d; best = k; } }
        const onTarget = foot.distanceTo(stage.tw.keyTop(ch));
        (report.dist ||= {})[ch] = +onTarget.toFixed(3);
        if (best !== ch || onTarget > 0.06) report.wrongKey.push({ key: ch, landed: best, mm: +onTarget.toFixed(3) });
        report.worstMiss = Math.max(report.worstMiss, onTarget);
      }
    }
  }
  f.setArm("L", f.rest.L); f.setArm("R", f.rest.R); f.apply();
  stage.arm.L = { ...f.rest.L }; stage.arm.R = { ...f.rest.R };
  report.restPose = collisions(stage).slice(0, 5);   // whole fly at rest vs everything
  report.worstMiss = +report.worstMiss.toFixed(3);
  return report;
}
