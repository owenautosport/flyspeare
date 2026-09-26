// A fly-sized typewriter, modelled on a 1930s portable: QWERTY keys on stems that press down,
// a typebar basket, ribbon spools, and a carriage that steps along with the sheet of paper
// showing what the fly is typing. Units are millimetres, like the fly; x runs away from the
// fly, z is up.
//
// The body is built from parts whose own bounding boxes fit them closely (a thin sloped key
// bed, thin side panels, the hood...), because the clipping check tests the fly against each
// part's box. The keys' places are what the fly's reach was calibrated on: do not move them.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
export const PITCH = 0.25;          // key spacing: a keyboard a fly can span with its front legs
const KEY_R = 0.1, KEY_TRAVEL = 0.05;
const ROW_DEPTH = 0.22;             // front-to-back spacing of the rows
const rowX = (r) => 0.75 - r * ROW_DEPTH;
const rowZ = (r) => 0.42 - r * 0.07;
// the key bed under the keys: a plate sloping up towards the back
const BED_SLOPE = 0.133;
const bedTop = (x) => 0.08 + (x - 0.1) * BED_SLOPE;

function glyph(label) {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#0e0f12"; g.beginPath(); g.arc(64, 64, 63, 0, Math.PI * 2); g.fill();
  const shine = g.createRadialGradient(46, 40, 4, 64, 64, 64);   // the domed glass over the legend
  shine.addColorStop(0, "rgba(255,255,255,.16)"); shine.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = shine; g.fillRect(0, 0, 128, 128);
  g.strokeStyle = "#d8b56a"; g.lineWidth = 3; g.beginPath(); g.arc(64, 64, 55, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "#f4efe2"; g.textAlign = "center"; g.textBaseline = "middle";
  const size = label.length === 1 ? 72 : label.length <= 3 ? 36 : 26;
  g.font = `bold ${size}px Georgia, serif`;
  g.translate(64, 64); g.rotate(-Math.PI / 2);  // upright as seen from the fly's seat
  g.fillText(label.toUpperCase(), 0, 5);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function canvasTexture(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

const nameplate = () => canvasTexture(1024, 146, (g) => {
  g.fillStyle = "#d8b56a"; g.font = "600 100px Georgia, 'Times New Roman', serif";
  g.textAlign = "center"; g.textBaseline = "middle";
  g.shadowColor = "rgba(0,0,0,.6)"; g.shadowBlur = 6;
  g.fillText("F L Y S P E A R E", 512, 78);
});

// the margin scale on the paper bail: 0 to 90, a tick for every character
const scale = () => canvasTexture(2048, 64, (g, w, h) => {
  g.fillStyle = "#e9e4d6"; g.fillRect(0, 0, w, h);
  g.fillStyle = "#1a1a1a"; g.font = "bold 22px Georgia, serif"; g.textAlign = "center";
  for (let i = 0; i <= 90; i++) {
    const x = 40 + i * ((w - 80) / 90);
    const big = i % 10 === 0;
    g.fillRect(x - 1, 0, 2, big ? 26 : i % 5 === 0 ? 18 : 11);
    if (big) g.fillText(String(i), x, 52);
  }
});

// the side panel's outline (x, z): low at the front, the keyboard slope, the hood, the raised
// basket, then down to the carriage deck at the back
function sideShape() {
  const s = new THREE.Shape();
  s.moveTo(0.02, 0.03);
  s.lineTo(0.02, 0.15);
  s.quadraticCurveTo(0.02, 0.22, 0.1, 0.23);
  s.lineTo(0.92, 0.36);
  s.quadraticCurveTo(1.08, 0.38, 1.1, 0.46);
  s.lineTo(1.0, 0.86);
  s.quadraticCurveTo(0.99, 0.94, 1.08, 0.94);
  s.lineTo(1.3, 0.94);
  s.quadraticCurveTo(1.42, 0.94, 1.44, 0.84);
  s.lineTo(1.47, 0.74);
  s.lineTo(1.88, 0.74);
  s.quadraticCurveTo(1.97, 0.74, 1.97, 0.65);
  s.lineTo(1.97, 0.03);
  s.lineTo(0.02, 0.03);
  return s;
}

// a thin bar from a to b (group coordinates)
function bar(a, b, thick, mat) {
  const d = new THREE.Vector3().subVectors(b, a);
  const m = new THREE.Mesh(new THREE.BoxGeometry(d.length(), thick, thick), mat);
  m.position.copy(a).add(b).multiplyScalar(0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), d.normalize());
  return m;
}

export class Typewriter {
  constructor() {
    this.group = new THREE.Group();
    this.keys = {};
    // glossy black enamel, gold trim, chrome: the look of a 1930s portable
    const enamel = new THREE.MeshPhysicalMaterial({ color: 0x0c0d11, roughness: 0.32, metalness: 0.15, clearcoat: 1, clearcoatRoughness: 0.08 });
    const crinkle = new THREE.MeshStandardMaterial({ color: 0x111216, roughness: 0.85, metalness: 0.2 });   // matt inner parts
    const gold = new THREE.MeshStandardMaterial({ color: 0xc9a45a, roughness: 0.28, metalness: 1 });
    const chrome = new THREE.MeshStandardMaterial({ color: 0xdfe4ec, roughness: 0.12, metalness: 1 });
    const steel = new THREE.MeshStandardMaterial({ color: 0x9aa1ab, roughness: 0.35, metalness: 1 });
    const rubber = new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.9 });
    const ribbonMat = new THREE.MeshStandardMaterial({ color: 0x5a0d10, roughness: 0.8 });
    const well = new THREE.MeshStandardMaterial({ color: 0x040405, roughness: 1 });
    const add = (mesh, name, shadow = true, parent = this.group) => {
      mesh.name = name; mesh.castShadow = shadow; mesh.receiveShadow = true; parent.add(mesh); return mesh;
    };
    const W = 3.26;   // inner width between the side panels

    // ---- the body
    // side panels, with a gold line following their outline
    const side = new THREE.ExtrudeGeometry(sideShape(), { depth: 0.08, bevelEnabled: true, bevelSize: 0.015,
      bevelThickness: 0.015, bevelSegments: 3, curveSegments: 16 });
    const stripePts = sideShape().getPoints(24).slice(1, -3)
      .map((p) => new THREE.Vector3(p.x, 0, p.y));
    for (const s of [1, -1]) {
      const panel = add(new THREE.Mesh(side, enamel), "side panel");
      panel.rotation.x = Math.PI / 2;                 // shape (x, z); extruded towards -y
      panel.position.y = s > 0 ? 1.72 : -1.72 + 0.08;
      const inset = stripePts.map((p) => new THREE.Vector3(p.x + 0.05, s * 1.737, p.z - 0.05));
      const line = add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(inset.filter((p) => p.z > 0.1 && p.x < 1.9)),
        160, 0.007, 6), gold), "trim", false);
      line.userData.trim = true;
    }
    // base plate and front apron with its pinstripe
    add(new THREE.Mesh(new RoundedBoxGeometry(1.95, W, 0.06, 2, 0.02), crinkle), "base").position.set(0.995, 0, 0.06);
    add(new THREE.Mesh(new RoundedBoxGeometry(0.07, 3.44, 0.18, 3, 0.025), enamel), "apron").position.set(0.055, 0, 0.12);
    add(new THREE.Mesh(new THREE.BoxGeometry(0.006, 3.3, 0.01), gold), "trim", false).position.set(0.018, 0, 0.17);
    add(new THREE.Mesh(new THREE.BoxGeometry(0.006, 3.3, 0.006), gold), "trim", false).position.set(0.018, 0, 0.08);
    // the key bed: a matt plate sloping up under the keys
    const bed = add(new THREE.Mesh(new RoundedBoxGeometry(1.0, W, 0.05, 2, 0.02), crinkle), "key bed");
    const bedAngle = Math.atan(BED_SLOPE);
    bed.rotation.y = -bedAngle;
    bed.position.set(0.58 + Math.sin(bedAngle) * 0.025, 0, bedTop(0.58) - Math.cos(bedAngle) * 0.025);
    // the hood: leaning forward over the keys, carrying the nameplate
    const hoodBot = new THREE.Vector3(1.12, 0, 0.42), hoodTop = new THREE.Vector3(0.99, 0, 0.9);
    const hoodLen = hoodBot.distanceTo(hoodTop), hoodAngle = Math.atan2(hoodTop.x - hoodBot.x, hoodTop.z - hoodBot.z);
    const hoodMid = hoodBot.clone().add(hoodTop).multiplyScalar(0.5);
    const hoodUp = new THREE.Vector3(Math.sin(hoodAngle), 0, Math.cos(hoodAngle));
    const hoodOut = new THREE.Vector3(-Math.cos(hoodAngle), 0, Math.sin(hoodAngle));   // facing the fly
    const hood = add(new THREE.Mesh(new RoundedBoxGeometry(0.05, W, hoodLen, 3, 0.02), enamel), "hood");
    hood.rotation.y = hoodAngle; hood.position.copy(hoodMid);
    const onHood = (mesh, along, out = 0.028) => {
      mesh.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(new THREE.Vector3(0, -1, 0), hoodUp, hoodOut));
      mesh.position.copy(hoodMid).addScaledVector(hoodUp, along).addScaledVector(hoodOut, out);
      return mesh;
    };
    add(onHood(new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.2),
      new THREE.MeshStandardMaterial({ map: nameplate(), transparent: true, roughness: 0.3, metalness: 0.6 })), 0.02), "nameplate", false);
    for (const a of [0.17, -0.13]) add(onHood(new THREE.Mesh(new THREE.PlaneGeometry(3.1, 0.012), gold), a), "trim", false);
    // the raised part carrying the typebar basket, the top between it and the hood, and the
    // low back of the body that the carriage rides on
    add(new THREE.Mesh(new RoundedBoxGeometry(0.26, W, 0.54, 3, 0.04), enamel), "basket housing").position.set(1.23, 0, 0.665);
    add(new THREE.Mesh(new RoundedBoxGeometry(0.3, W, 0.04, 2, 0.015), enamel), "top").position.set(1.12, 0, 0.915);
    add(new THREE.Mesh(new RoundedBoxGeometry(0.88, W, 0.71, 3, 0.05), enamel), "rear body").position.set(1.53, 0, 0.385);
    // vents across the back, and a gold line round the rear
    for (let i = 0; i < 6; i++) {
      add(new THREE.Mesh(new THREE.BoxGeometry(0.012, 1.6, 0.025), chrome), "vent", false).position.set(1.972, 0, 0.2 + i * 0.07);
    }
    add(new THREE.Mesh(new THREE.BoxGeometry(0.006, 3.1, 0.008), gold), "trim", false).position.set(1.973, 0, 0.64);
    // rubber feet
    for (const [x, y] of [[0.2, 1.5], [0.2, -1.5], [1.8, 1.5], [1.8, -1.5]]) {
      const f = add(new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.11, 0.06, 20), rubber), "foot", false);
      f.rotation.x = Math.PI / 2; f.position.set(x, y, 0.0);
    }

    // ---- the typebar basket: a fan of bars in a dark well, converging on the type guide
    const guide = new THREE.Vector3(1.38, 0, 0.95);
    const wellDisc = add(new THREE.Mesh(new THREE.CircleGeometry(0.46, 48, Math.PI / 2, Math.PI), well), "basket well", false);
    wellDisc.position.set(guide.x, 0, 0.937);
    for (let i = 0; i < 36; i++) {
      const a = Math.PI * (0.6 + 0.8 * (i / 35));          // a half-fan opening towards the keys
      const r = 0.3;
      const b = add(new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.012, 0.008), steel), "typebar", false);
      b.position.set(guide.x + Math.cos(a) * r, Math.sin(a) * r, guide.z);
      b.rotation.z = a;
      const slug = add(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.018, 0.016), chrome), "typebar", false);
      slug.position.set(guide.x + Math.cos(a) * 0.18, Math.sin(a) * 0.18, guide.z + 0.004);
    }
    const seg = add(new THREE.Mesh(new THREE.TorusGeometry(0.44, 0.016, 8, 48, Math.PI * 0.84), gold), "segment", false);
    seg.position.set(guide.x, 0, guide.z - 0.012); seg.rotation.z = Math.PI * 0.58;
    // type guide, ribbon vibrator and card holder at the printing point, in front of the platen
    add(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.16, 0.06), chrome), "type guide", false).position.set(1.36, 0, 0.97);
    add(new THREE.Mesh(new THREE.BoxGeometry(0.008, 0.5, 0.08), chrome), "card holder", false).position.set(1.35, 0, 1.06);
    add(new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.012, 0.04), new THREE.MeshStandardMaterial({ color: 0xb3261e })), "index", false)
      .position.set(1.345, 0, 1.06);

    // ---- ribbon spools on either side of the basket, and the ribbon running to the vibrator
    for (const s of [1, -1]) {
      const y = s * 1.2;
      const cup = add(new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.2, 0.06, 40, 1, true), chrome), "spool", false);
      cup.rotation.x = Math.PI / 2; cup.position.set(1.16, y, 0.965);
      const disc = add(new THREE.Mesh(new THREE.CircleGeometry(0.2, 40), steel), "spool", false);
      disc.position.set(1.16, y, 0.94);
      const coil = add(new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.05, 40), ribbonMat), "ribbon", false);
      coil.rotation.x = Math.PI / 2; coil.position.set(1.16, y, 0.965);
      const hub = add(new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.07, 16), chrome), "spool", false);
      hub.rotation.x = Math.PI / 2; hub.position.set(1.16, y, 0.975);
      add(bar(new THREE.Vector3(1.16 + 0.16, y - s * 0.02, 0.975), new THREE.Vector3(1.355, s * 0.08, 0.99), 0.022, ribbonMat), "ribbon", false);
    }
    add(new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.16, 0.035), ribbonMat), "ribbon", false).position.set(1.352, 0, 0.99);

    // ---- keys: staggered QWERTY rows stepping up towards the back, each on a chrome stem whose
    // lever runs back into the machine
    const capTop = new THREE.MeshPhysicalMaterial({ roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.04 });
    const capSide = new THREE.MeshStandardMaterial({ color: 0x15171c });
    const makeKey = (label, x, y, z, name) => {
      const key = new THREE.Group();
      key.position.set(x, y, z);
      const len = z - 0.025 - bedTop(x) + 0.02;               // down into the key bed
      const s = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, len, 10), chrome);
      s.rotation.x = Math.PI / 2; s.position.z = -0.025 - len / 2;
      const top = capTop.clone(); top.map = glyph(label);
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(KEY_R, KEY_R, 0.05, 32), [chrome, top, capSide]);
      cap.rotation.x = Math.PI / 2;   // cylinder axis to +z; top face shows the legend
      cap.rotation.y = -Math.PI / 2;  // legend upright for the fly (and the camera behind it)
      const ring = new THREE.Mesh(new THREE.TorusGeometry(KEY_R, 0.012, 8, 32), chrome);
      ring.position.z = 0.026;
      cap.castShadow = true; cap.name = name; s.name = `stem ${label}`; ring.name = `ring ${label}`;
      key.add(s, cap, ring);
      key.userData = { rest: z, down: 0 };
      this.group.add(key);
      // the key lever along the bed, back to the machine
      const a = new THREE.Vector3(x, y, bedTop(x) + 0.012), b = new THREE.Vector3(1.1, y, bedTop(1.1) + 0.012);
      add(bar(a, b, 0.014, steel), "key lever", false);
      return key;
    };
    ROWS.forEach((row, r) => {
      [...row].forEach((ch, i) => {
        // centred rows, each lower row stepped a little to the right, as on a real typewriter
        const y = ((row.length - 1) / 2 - i) * PITCH - r * 0.07;
        this.keys[ch] = makeKey(ch, rowX(r), y, rowZ(r), `key ${ch}`);
      });
    });
    // the rest of a real keyboard (the fly only uses the letters): figures, shift, lock,
    // tab, margin release and backspace. They are fixed in place.
    [..."234567890-"].forEach((ch, i) => makeKey(ch, rowX(-1), (4.5 - i) * PITCH + 0.07, rowZ(-1), `other key ${ch}`));
    for (const [label, r, y] of [["shift", 2, 0.61 + 0.3], ["shift", 2, -0.89 - 0.3], ["lock", 1, 0.93 + 0.27],
      ["tab", 0, 1.125 + 0.27], ["mar", -1, 1.195 + 0.25], ["⌫", -1, -1.055 - 0.25]]) {
      makeKey(label, rowX(r), y, rowZ(r), `other key ${label}`);
    }
    // space bar on two arms
    const space = add(new THREE.Mesh(new RoundedBoxGeometry(0.09, 1.5, 0.05, 3, 0.024), chrome), "spacebar");
    space.position.set(0.75 - 3 * ROW_DEPTH + 0.05, 0, 0.26);
    for (const y of [0.6, -0.6]) {
      add(bar(new THREE.Vector3(0.15, y, 0.24), new THREE.Vector3(0.32, y, bedTop(0.32) + 0.01), 0.018, chrome), "spacebar arm", false);
    }

    // ---- carriage: rides above the back of the body; platen and paper step one character
    // per keypress
    for (const y of [1.5, -1.5]) {   // the posts and fixed rail it runs on
      add(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.1), steel), "carriage post", false).position.set(1.88, y, 0.78);
    }
    add(new THREE.Mesh(new THREE.BoxGeometry(0.05, 3.2, 0.05), steel), "carriage rail", false).position.set(1.88, 0, 0.845);
    this.carriage = new THREE.Group();
    this.carriage.position.set(1.6, 0, 1.0);
    const platen = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 4.3, 48),
      new THREE.MeshStandardMaterial({ color: 0x101114, roughness: 0.75 }));
    platen.castShadow = true; platen.name = "platen";
    const axle = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 4.9, 12), chrome);
    // knurled knobs at both ends, outside enamelled end plates
    const knob = () => {
      const g = new THREE.Group();
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.27, 0.14, 40), rubber));
      const ridges = [];                         // knurling, as one mesh
      for (let i = 0; i < 40; i++) {
        const a = (i / 40) * Math.PI * 2;
        ridges.push(new THREE.BoxGeometry(0.02, 0.12, 0.02).rotateY(-a).translate(Math.cos(a) * 0.272, 0, Math.sin(a) * 0.272));
      }
      g.add(new THREE.Mesh(mergeGeometries(ridges), rubber));
      for (const dy of [-0.07, 0.07]) {
        const rim = new THREE.Mesh(new THREE.TorusGeometry(0.27, 0.02, 8, 40), chrome);
        rim.rotation.x = Math.PI / 2; rim.position.y = dy; g.add(rim);
      }
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.16, 20), chrome);
      g.add(cap);
      return g;
    };
    const knobL = knob(); knobL.position.y = 2.32;
    const knobR = knob(); knobR.position.y = -2.32;
    const ends = [2.18, -2.18].flatMap((y) => {   // round end plates, each with an arm back to the rail
      const e = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.05, 40), enamel);
      e.position.set(0, y, 0);
      const arm = new THREE.Mesh(new RoundedBoxGeometry(0.34, 0.05, 0.14, 2, 0.02), enamel);
      arm.position.set(0.2, y, -0.09);
      return [e, arm];
    });
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.06, 4.4, 0.06), chrome);
    rail.position.set(0.28, 0, -0.1);
    // paper bail with its rollers, carrying the margin scale
    const scaleMat = new THREE.MeshStandardMaterial({ map: scale(), roughness: 0.5, metalness: 0.2 });
    const bail = new THREE.Mesh(new THREE.BoxGeometry(0.008, 3.4, 0.06), [chrome, scaleMat, chrome, chrome, chrome, chrome]);  // scale faces the fly
    bail.position.set(-0.26, 0, 0.18);
    const rollers = [0.8, -0.8].map((y) => {
      const r = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.12, 16), rubber);
      r.position.set(-0.23, y, 0.2); return r;
    });
    const bailArms = [1.72, -1.72].map((y) => bar(new THREE.Vector3(-0.26, y, 0.18), new THREE.Vector3(0.02, y * 1.05, 0.26), 0.025, chrome));
    // paper table behind the sheet, leaning back with it
    const table = new THREE.Mesh(new RoundedBoxGeometry(0.025, 3.0, 1.3, 2, 0.01), enamel);
    table.rotation.y = 0.12; table.position.set(0.02, 0, 0.95);
    const tableEdge = new THREE.Mesh(new THREE.BoxGeometry(0.03, 3.02, 0.02), chrome);
    tableEdge.rotation.y = 0.12; tableEdge.position.set(0.1, 0, 1.6);
    // carriage return lever, and the paper release lever at the other end
    const lever = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 2.4, 0.1), new THREE.Vector3(-0.2, 2.55, 0.28), new THREE.Vector3(-0.6, 2.65, 0.4),
      new THREE.Vector3(-0.95, 2.65, 0.42)]), 24, 0.025, 8), chrome);
    const leverTip = new THREE.Mesh(new THREE.SphereGeometry(0.06, 16, 12), rubber);
    leverTip.position.set(-0.95, 2.65, 0.42);
    const release = bar(new THREE.Vector3(0.15, -2.1, 0.12), new THREE.Vector3(0.28, -2.1, 0.34), 0.03, chrome);
    const releaseTip = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 10), chrome);
    releaseTip.position.set(0.28, -2.1, 0.34);
    this.carriage.add(platen, axle, knobL, knobR, ...ends, rail, bail, ...rollers, ...bailArms, table, tableEdge,
      lever, leverTip, release, releaseTip);
    this.carriage.traverse((o) => { if (o.isMesh) o.receiveShadow = true; });

    // many small fixed parts, one draw call per kind
    for (const name of ["typebar", "key lever", "vent", "spool", "ribbon"]) this._merge(name);

    this.paperCanvas = document.createElement("canvas");
    this.paperCanvas.width = 1024; this.paperCanvas.height = 1024;
    this.paperTex = new THREE.CanvasTexture(this.paperCanvas);
    this.paperTex.colorSpace = THREE.SRGBColorSpace;
    this.paperTex.anisotropy = 8;
    const paper = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 3.4),
      new THREE.MeshStandardMaterial({ map: this.paperTex, roughness: 0.9, side: THREE.DoubleSide }));
    // stand the sheet up out of the platen, facing the fly (-x): text runs along -y, up is +z
    paper.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(-1, 0, 0)));
    paper.rotateX(-0.12); // leaning back a little, like a real sheet
    paper.position.set(0.05, 0, 1.75);
    this.paper = paper;
    this.carriage.add(paper);
    this.group.add(this.carriage);
    this.column = 0;
    this.drawPaper(["", "", ""], "");
  }

  // Merge the group's direct children called `name` into one mesh per material.
  _merge(name) {
    const byMat = new Map();
    for (const m of this.group.children.filter((o) => o.isMesh && o.name === name && !Array.isArray(o.material))) {
      m.updateMatrix();
      const g = m.geometry.index ? m.geometry.toNonIndexed() : m.geometry.clone();
      for (const k of Object.keys(g.attributes)) if (!["position", "normal", "uv"].includes(k)) g.deleteAttribute(k);
      if (!byMat.has(m.material)) byMat.set(m.material, { geos: [], shadow: m.castShadow });
      byMat.get(m.material).geos.push(g.applyMatrix4(m.matrix));
      this.group.remove(m);
    }
    for (const [mat, { geos, shadow }] of byMat) {
      const merged = new THREE.Mesh(mergeGeometries(geos), mat);
      merged.name = name; merged.castShadow = shadow; merged.receiveShadow = true;
      this.group.add(merged);
    }
  }

  keyTop(ch, out = new THREE.Vector3()) {
    const k = this.keys[ch];
    k.updateWorldMatrix(true, false);
    return out.set(0, 0, 0.04).applyMatrix4(k.matrixWorld);
  }

  press(ch, amount) {
    const k = this.keys[ch];
    if (!k) return;
    k.userData.down = amount;
    k.position.z = k.userData.rest - KEY_TRAVEL * amount;
  }

  // carriage moves one step per character, returns to the start of the word on a retry
  setColumn(col) {
    this.column = col;
    this.carriage.position.y = 0.9 - Math.min(col, 12) * 0.14;
  }

  // lines: committed text (last few lines), attempt: the word being typed now, struck: failed tries
  drawPaper(lines, attempt, struck = [], flash = null) {
    const g = this.paperCanvas.getContext("2d");
    const W = this.paperCanvas.width, H = this.paperCanvas.height;
    g.fillStyle = "#f4efe2"; g.fillRect(0, 0, W, H);
    g.fillStyle = "rgba(0,0,0,0.04)";
    for (let y = 0; y < H; y += 6) g.fillRect(0, y, W, 1);
    g.font = "44px 'Special Elite', 'Courier New', monospace";
    g.textBaseline = "alphabetic";
    const lh = 58, left = 70;
    let y = H - 330 - lh * (lines.length - 1);
    g.fillStyle = "#23201b";
    for (const line of lines) { g.fillText(line, left, y); y += lh; }
    y = H - 330 + lh;
    let x = left;
    g.fillStyle = "#6d6a64";
    for (const s of struck.slice(-4)) {
      g.fillText(s, x, y);
      const w = g.measureText(s).width;
      g.strokeStyle = "#b3261e"; g.lineWidth = 4;
      g.beginPath(); g.moveTo(x - 4, y - 14); g.lineTo(x + w + 4, y - 14); g.stroke();
      x += w + 26;
    }
    g.fillStyle = flash === "good" ? "#1d7a3a" : flash === "bad" ? "#b3261e" : "#111";
    g.fillText(attempt + "▏", x, y);
    this.paperTex.needsUpdate = true;
  }
}
