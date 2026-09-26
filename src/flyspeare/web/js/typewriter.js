// A fly-sized typewriter: QWERTY keys that press down, a carriage that steps along, and a
// sheet of paper that shows what the fly is typing. Units are millimetres, like the fly.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];
export const PITCH = 0.25;          // key spacing: a keyboard a fly can span with its front legs
const KEY_R = 0.1, KEY_TRAVEL = 0.05;
const ROW_DEPTH = 0.22;             // front-to-back spacing of the three rows

function glyph(ch) {
  const c = document.createElement("canvas");
  c.width = c.height = 64;  // (drawn at 64 px: plenty for a key 0.2 mm across)
  const g = c.getContext("2d");
  g.fillStyle = "#101114"; g.beginPath(); g.arc(32, 32, 31, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#d8b56a"; g.lineWidth = 2; g.beginPath(); g.arc(32, 32, 27, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "#f4efe2"; g.font = "bold 36px Georgia, serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.translate(32, 32); g.rotate(-Math.PI / 2);  // upright as seen from the fly's seat
  g.fillText(ch.toUpperCase(), 0, 3);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function nameplate() {
  const c = document.createElement("canvas");
  c.width = 1024; c.height = 146;
  const g = c.getContext("2d");
  g.fillStyle = "#d8b56a"; g.font = "600 100px Georgia, 'Times New Roman', serif";
  g.textAlign = "center"; g.textBaseline = "middle";
  g.shadowColor = "rgba(0,0,0,.6)"; g.shadowBlur = 6;
  g.fillText("F L Y S P E A R E", 512, 78);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class Typewriter {
  constructor() {
    this.group = new THREE.Group();
    this.keys = {};
    // glossy black enamel, gold trim, chrome: the look of a 1930s portable
    const enamel = new THREE.MeshPhysicalMaterial({ color: 0x0c0d11, roughness: 0.32, metalness: 0.15, clearcoat: 1, clearcoatRoughness: 0.08 });
    const gold = new THREE.MeshStandardMaterial({ color: 0xc9a45a, roughness: 0.28, metalness: 1 });
    const chrome = new THREE.MeshStandardMaterial({ color: 0xdfe4ec, roughness: 0.12, metalness: 1 });
    const rubber = new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.9 });
    const add = (mesh, name, shadow = true) => { mesh.name = name; mesh.castShadow = shadow; mesh.receiveShadow = true; this.group.add(mesh); return mesh; };

    // body: a sloped deck under the keys and a raised back housing the carriage (rounded,
    // enamelled). Their sizes and places are what the arms' reach was checked against.
    const deck = add(new THREE.Mesh(new RoundedBoxGeometry(1.0, 3.2, 0.25, 4, 0.06), enamel), "deck");
    deck.position.set(0.55, 0, 0.05);
    deck.rotation.y = -0.18;
    const back = add(new THREE.Mesh(new RoundedBoxGeometry(0.8, 3.8, 0.95, 5, 0.12), enamel), "housing");
    back.position.set(1.45, 0, 0.42);
    // gold pinstripes along the housing front and the deck's front edge
    for (const [z, len] of [[0.7, 3.62], [0.5, 3.62], [0.86, 3.5]]) {
      add(new THREE.Mesh(new THREE.BoxGeometry(0.012, len, 0.012), gold), "trim", false).position.set(1.048, 0, z);
    }
    const lip = add(new THREE.Mesh(new THREE.BoxGeometry(0.012, 3.0, 0.012), gold), "trim", false);
    lip.position.set(0.06, 0, 0.1); lip.rotation.y = -0.18;
    // nameplate
    const plate = add(new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.2),
      new THREE.MeshStandardMaterial({ map: nameplate(), transparent: true, roughness: 0.3, metalness: 0.6 })), "nameplate", false);
    plate.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(-1, 0, 0)));
    plate.position.set(1.043, 0, 0.6);
    // rubber feet
    for (const [x, y] of [[0.15, 1.45], [0.15, -1.45], [1.75, 1.7], [1.75, -1.7]]) {
      const f = add(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.1, 0.07, 16), rubber), "foot", false);
      f.rotation.x = Math.PI / 2; f.position.set(x, y, -0.04);
    }
    // the typebar basket: a fan of bars converging on the type guide in front of the platen
    const guide = new THREE.Vector3(1.38, 0, 0.93);
    for (let i = 0; i < 26; i++) {
      const a = Math.PI * (0.62 + 0.76 * (i / 25));          // a half-fan opening towards the keys
      const bar = add(new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.014, 0.01), chrome), "typebar", false);
      const r = 0.34;
      bar.position.set(guide.x + Math.cos(a) * r, guide.y + Math.sin(a) * r, guide.z);
      bar.rotation.z = a;
    }
    const seg = add(new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.018, 8, 40, Math.PI * 0.8), gold), "segment", false);
    seg.position.copy(guide).setZ(guide.z - 0.02); seg.rotation.z = Math.PI * 0.6;
    // ribbon spools and the ribbon between them
    for (const y of [1.35, -1.35]) {
      const spool = add(new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.05, 32), chrome), "spool", false);
      spool.rotation.x = Math.PI / 2; spool.position.set(1.5, y, 0.93);
      const ribbon = add(new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.19, 0.06, 32),
        new THREE.MeshStandardMaterial({ color: 0x5a0d10, roughness: 0.8 })), "ribbon", false);
      ribbon.rotation.x = Math.PI / 2; ribbon.position.set(1.5, y, 0.95);
    }
    const band = add(new THREE.Mesh(new THREE.BoxGeometry(0.02, 2.5, 0.06),
      new THREE.MeshStandardMaterial({ color: 0x5a0d10, roughness: 0.8 })), "ribbon", false);
    band.position.set(1.62, 0, 0.98);

    // keys, staggered QWERTY rows rising towards the back, each on a chrome stem
    ROWS.forEach((row, r) => {
      const x = 0.75 - r * ROW_DEPTH, z = 0.42 - r * 0.07;
      [...row].forEach((ch, i) => {
        // centred rows, each lower row stepped a little to the right, as on a real typewriter
        const y = ((row.length - 1) / 2 - i) * PITCH - r * 0.07;
        const key = new THREE.Group();
        key.position.set(x, y, z);
        const s = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 0.26, 10), chrome);
        s.rotation.x = Math.PI / 2; s.position.z = -0.13;
        const cap = new THREE.Mesh(
          new THREE.CylinderGeometry(KEY_R, KEY_R, 0.05, 32),
          [chrome, new THREE.MeshStandardMaterial({ map: glyph(ch), roughness: 0.35 }), new THREE.MeshStandardMaterial({ color: 0x15171c })],
        );
        cap.rotation.x = Math.PI / 2;   // cylinder axis to +z; top face shows the glyph
        cap.rotation.y = -Math.PI / 2;  // letters upright for the fly (and the camera behind it)
        const ring = new THREE.Mesh(new THREE.TorusGeometry(KEY_R, 0.012, 8, 32), chrome);
        ring.position.z = 0.026;
        cap.castShadow = true; cap.name = `key ${ch}`; s.name = `stem ${ch}`; ring.name = `ring ${ch}`;
        key.add(s, cap, ring);
        key.userData = { rest: z, down: 0 };
        this.group.add(key);
        this.keys[ch] = key;
      });
    });
    const space = add(new THREE.Mesh(new RoundedBoxGeometry(0.09, 1.5, 0.05, 3, 0.02), chrome), "spacebar");
    space.position.set(0.75 - 3 * ROW_DEPTH + 0.05, 0, 0.26);
    for (const y of [0.6, -0.6]) {
      const arm = add(new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.02, 0.02), chrome), "spacebar arm", false);
      arm.position.set(0.19, y, 0.2); arm.rotation.y = 0.5;
    }

    // carriage: platen roller and paper, stepping one character per keypress
    this.carriage = new THREE.Group();
    this.carriage.position.set(1.6, 0, 1.0);
    const platen = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 4.3, 48),
      new THREE.MeshStandardMaterial({ color: 0x101114, roughness: 0.75 }));
    platen.castShadow = true; platen.name = "platen";
    // knurled knobs, the carriage rail, the paper bail with its rollers, the return lever
    const knob = () => {
      const g = new THREE.Group();
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.27, 0.14, 40), rubber));
      for (const dy of [-0.07, 0.07]) {
        const rim = new THREE.Mesh(new THREE.TorusGeometry(0.27, 0.02, 8, 40), chrome);
        rim.rotation.x = Math.PI / 2; rim.position.y = dy; g.add(rim);
      }
      return g;
    };
    const knobL = knob(); knobL.position.y = 2.22;
    const knobR = knob(); knobR.position.y = -2.22;
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.06, 4.6, 0.06), chrome);
    rail.position.set(0.28, 0, -0.1);
    const bail = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 3.2, 12), chrome);
    bail.position.set(-0.26, 0, 0.18);
    const rollers = [0.7, -0.7].map((y) => {
      const r = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.12, 16), rubber);
      r.position.set(-0.26, y, 0.18); return r;
    });
    const lever = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 2.3, 0.1), new THREE.Vector3(-0.2, 2.45, 0.28), new THREE.Vector3(-0.6, 2.55, 0.4),
      new THREE.Vector3(-0.95, 2.55, 0.42)]), 24, 0.025, 8), chrome);
    const leverTip = new THREE.Mesh(new THREE.SphereGeometry(0.06, 16, 12), rubber);
    leverTip.position.set(-0.95, 2.55, 0.42);
    this.carriage.add(platen, knobL, knobR, rail, bail, ...rollers, lever, leverTip);

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
