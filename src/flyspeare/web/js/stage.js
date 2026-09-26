// The 3D set: a dark stage with a glowing platform, the fly on a stool, and the typewriter.
// Also the key-strike animation: which front leg reaches, and when the key goes down.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { lerpArm } from "./fly.js";
import { Typewriter } from "./typewriter.js";

const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

export const CAMERAS = {
  front: { pos: [-6.6, -5.6, 4.4], target: [-0.1, 0, 1.3] },
  close: { pos: [-2.8, -2.9, 2.9], target: [0.3, 0, 1.0] },
  side: { pos: [-0.6, -7.4, 2.1], target: [-0.3, 0, 1.3] },
  paper: { pos: [-3.0, -1.8, 3.5], target: [1.6, 0, 2.6] },
};

export class Stage {
  constructor(canvas, fly) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0f1a);
    this.scene.fog = new THREE.Fog(0x0b0f1a, 14, 30);
    // soft studio reflections so the chrome, gold and enamel actually shine
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.45;
    this.camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.05, 600);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.view("front", true);

    // lights: cool key light, warm rim, soft fill
    this.hemi = new THREE.HemisphereLight(0x9fb7ff, 0x1a1422, 0.9);
    this.scene.add(this.hemi);
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    this.keyLight = key;
    key.position.set(-4, -5, 9);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5 });
    this.scene.add(key);
    const rim = new THREE.PointLight(0x5ad8ff, 18, 12);
    rim.position.set(3, 3, 3);
    this.scene.add(rim);

    // floor grid and the glowing platform
    const grid = new THREE.GridHelper(40, 80, 0x2a4a7a, 0x16233d);
    grid.rotation.x = Math.PI / 2;
    this.scene.add(grid);
    const plat = new THREE.Mesh(new THREE.BoxGeometry(7.5, 7.5, 0.18),
      new THREE.MeshStandardMaterial({ color: 0x3a4152, roughness: 0.55, metalness: 0.3 }));
    plat.position.z = -0.09;
    plat.receiveShadow = true;
    this.scene.add(plat);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(7.52, 7.52, 0.2)),
      new THREE.LineBasicMaterial({ color: 0x5ff3ff }));
    edge.position.z = -0.09;
    this.scene.add(edge);

    // the stool the fly sits on
    const stool = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.62, 0.48, 32),
      new THREE.MeshStandardMaterial({ color: 0x252a36, roughness: 0.4, metalness: 0.5 }));
    stool.rotation.x = Math.PI / 2;
    stool.position.set(-1.35, 0, 0.24);
    stool.castShadow = stool.receiveShadow = true;
    stool.userData.solid = true; stool.name = "stool";
    this.scene.add(stool);

    this.tw = new Typewriter();
    this.tw.group.position.set(-0.45, 0, 0.35);
    this.scene.add(this.tw.group);
    // raise the typewriter onto a small desk block
    const desk = new THREE.Mesh(new THREE.BoxGeometry(2.2, 4.4, 0.35),
      new THREE.MeshStandardMaterial({ color: 0x2c3342, roughness: 0.5, metalness: 0.3 }));
    desk.position.set(0.85, 0, 0.17);   // front edge under the keys, clear of the fly's feet
    desk.castShadow = desk.receiveShadow = true;
    desk.userData.solid = true; desk.name = "desk";
    this.scene.add(desk);

    this.fly = fly;
    // sit upright on the stool: pivot about the thorax, pitch nose-up until the body is
    // nearly vertical, abdomen tip resting on the seat
    this.flyHolder = new THREE.Group();
    fly.root.position.set(0, 0, -1.2);          // thorax centre to the pivot
    this.flyHolder.add(fly.root);
    this.flyHolder.rotation.set(0, -1.25, 0);
    this.flyHolder.position.set(-1.25, 0, 1.95);
    this.hoverHeight = 0.2;   // how high the foot lifts above the keys between presses
    fly.root.traverse((o) => { if (o.isMesh) o.castShadow = true; });
    this.scene.add(this.flyHolder);

    // rest the abdomen exactly on the seat: lift the fly until its lowest abdomen point is
    // on the stool top
    this.flyHolder.updateWorldMatrix(true, true);
    let low = Infinity;
    const v = new THREE.Vector3();
    fly.root.traverse((m) => {
      if (!m.isMesh || !/^A\d/.test(m.name)) return;
      const pos = m.geometry.attributes.position;
      for (let i = 0; i < pos.count; i += 3) low = Math.min(low, v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld).z);
    });
    const lift = 0.48 + 0.01 - low;
    this.flyHolder.position.z += lift;
    this.flyHolder.updateWorldMatrix(true, true);
    // the desk and typewriter rise with the fly, so the keys stay at the same reach
    this.tw.group.position.z += lift;
    desk.scale.z = (0.35 + lift) / 0.35;
    desk.position.z = (0.35 + lift) / 2;
    this.tw.group.updateWorldMatrix(true, true);
    // middle feet on the seat edge, hind legs hanging down in front of the stool, as when sitting
    this.flyHolder.updateWorldMatrix(true, true);
    const seatTop = 0.48 + 0.025;
    for (const [side, s] of [["L", 1], ["R", -1]]) {
      fly.reach(side, new THREE.Vector3(-0.62, 0.36 * s, 0.03), 60, "H");   // hind feet down in front of the stool
      fly.reach(side, new THREE.Vector3(-0.95, 0.5 * s, seatTop), 60, "M");
    }
    this.strike = null;      // the key press being animated
    this.arm = { L: { ...fly.rest.L }, R: { ...fly.rest.R } };
    this.clock = new THREE.Clock();
    this.night = 0; this.nightGoal = 0;   // 0 = day, 1 = night (lights down)
    this.onFrame = null;
    window.addEventListener("resize", () => this.resize());
    this.resize();
  }

  view(name, instant = false) {
    const c = CAMERAS[name] || CAMERAS.front;
    this._camGoal = { pos: new THREE.Vector3(...c.pos), target: new THREE.Vector3(...c.target) };
    if (instant) {
      this.camera.position.copy(this._camGoal.pos);
      this.controls.target.copy(this._camGoal.target);
      this._camGoal = null;
    }
  }

  viewAt(c) {
    this._camGoal = { pos: new THREE.Vector3(...c.pos), target: new THREE.Vector3(...c.target) };
  }

  resize() {
    const c = this.renderer.domElement;
    const w = c.clientWidth, h = c.clientHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // frame the subject in the open space left of the brain panel, above the paper
    this.camera.updateProjectionMatrix();
  }

  // Work out one keypress: which front leg, and its poses above and on the key. Only the
  // arm moves; the body stays seated.
  solveStrike(ch) {
    const f = this.fly;
    const side = this.tw.keys[ch].position.y >= 0 ? "L" : "R";
    const top = this.tw.keyTop(ch);
    const start = { ...this.arm[side] };
    f.setArm(side, f.rest[side]);
    const hit = f.reach(side, top.clone().add(new THREE.Vector3(0, 0, -0.015)), 40);
    const miss = f.footWorld(side).distanceTo(top);
    const hover = f.reach(side, top.clone().add(new THREE.Vector3(-0.03, 0, this.hoverHeight)), 30);
    f.setArm(side, start);
    f.apply();
    return { ch, side, start, hover, hit, miss };
  }

  // The pose at time t (0..1) through a strike: up from where the arm was, over to above
  // the key, down onto it, hold, back up. `down` is how far the key is pressed.
  strikePose(st, t) {
    if (t < 0.45) return { arm: lerpArm(st.start, st.hover, ease(t / 0.45)), down: 0 };
    if (t < 0.6) { const u = ease((t - 0.45) / 0.15); return { arm: lerpArm(st.hover, st.hit, u), down: u }; }
    if (t < 0.7) return { arm: st.hit, down: 1 };
    const u = ease((t - 0.7) / 0.3);
    return { arm: lerpArm(st.hit, st.hover, u), down: 1 - u };
  }

  // Animate one keypress over `ms`. Resolves when the arm is back above the key.
  press(ch, ms) {
    return new Promise((resolve) => {
      if (!this.tw.keys[ch]) return resolve();
      this.strike = { ...this.solveStrike(ch), t0: performance.now(), ms, resolve };
    });
  }

  _animateStrike(now) {
    const s = this.strike;
    if (!s) return;
    const t = Math.min(1, (now - s.t0) / s.ms);
    const { arm, down } = this.strikePose(s, t);
    this.arm[s.side] = arm;
    this.fly.setArm(s.side, arm);
    this.tw.press(s.ch, down);
    if (t >= 1) {
      this.tw.press(s.ch, 0);
      this.strike = null;
      s.resolve();
    }
  }

  start() {
    const loop = () => {
      requestAnimationFrame(loop);
      const dt = Math.min(this.clock.getDelta(), 0.1);
      const now = performance.now();
      if (this._camGoal) {
        this.camera.position.lerp(this._camGoal.pos, 0.08);
        this.controls.target.lerp(this._camGoal.target, 0.08);
        if (this.camera.position.distanceTo(this._camGoal.pos) < 0.01) this._camGoal = null;
      }
      this.fly.idle(now / 1000);
      this.night += (this.nightGoal - this.night) * Math.min(1, dt * 3);
      this.hemi.intensity = 0.9 * (1 - 0.75 * this.night);
      this.keyLight.intensity = 2.4 * (1 - 0.85 * this.night);
      this.renderer.toneMappingExposure = 1.1 * (1 - 0.35 * this.night);
      this._animateStrike(now);
      if (!this.strike) {
        // resting arms drift back to the ready pose between presses
        for (const side of ["L", "R"]) {
          this.arm[side] = lerpArm(this.arm[side], this.fly.rest[side], 0.04);
          this.fly.setArm(side, this.arm[side]);
        }
      }
      this.fly.apply();
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      if (this.onFrame) this.onFrame(dt);
    };
    loop();
  }
}
