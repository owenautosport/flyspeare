// Live map of the fly's brain on real FlyWire v783 neuron positions: a faint whole-brain
// outline, the right mushroom body's Kenyon cells, its projection neurons, dopamine neurons
// and output neurons. Each keypress lights the PNs and KCs that were really active in the
// model; dopamine flashes the real PAM (reward) or PPL1 (punishment) cells.

export class BrainMap {
  constructor(canvas, fw) {
    this.c = canvas;
    this.g = canvas.getContext("2d");
    this.fw = fw;
    const all = fw.brain_pos;
    // centre and scale on the whole brain
    const mean = [0, 1, 2].map((k) => all.reduce((s, p) => s + p[k], 0) / all.length);
    // scale to the bulk of the brain (98th percentile), not a few stray outlying neurons
    const xs = all.map((p) => Math.abs(p[0] - mean[0])).sort((a, b) => a - b);
    const span = xs[Math.floor(xs.length * 0.98)] * 1.08;
    this.norm = (p) => [(p[0] - mean[0]) / span, (p[1] - mean[1]) / span, (p[2] - mean[2]) / span];
    this.brain = all.map(this.norm);
    this.kc = fw.kc_pos.map(this.norm);
    this.pn = fw.pn_pos.map(this.norm);
    this.dan = fw.dan_pos.map(this.norm);
    this.pam = fw.dan_type.map((t) => t.startsWith("PAM"));
    this.mbon = fw.mbon_pos.map(this.norm);
    this.kcGlow = new Float32Array(this.kc.length);
    this.pnGlow = new Float32Array(this.pn.length);
    this.reward = 0; this.punish = 0;
    this.angle = 0;
    this.channelToPn = null;
    // view: drag to rotate (yaw/pitch), wheel to zoom, double-click to reset.
    // It turns slowly on its own until you touch it, and again after a while idle.
    this.yaw = 0; this.pitch = 0; this.zoom = 1; this.lastTouch = -1e9;
    let drag = null;
    canvas.style.cursor = "grab";
    canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); canvas.style.cursor = "grabbing"; });
    canvas.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.yaw += (e.clientX - drag.x) * 0.01;
      this.pitch = Math.max(-1.5, Math.min(1.5, this.pitch + (e.clientY - drag.y) * 0.01));
      drag = { x: e.clientX, y: e.clientY };
      this.lastTouch = performance.now();
    });
    const end = () => { drag = null; canvas.style.cursor = "grab"; };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.zoom = Math.max(0.6, Math.min(6, this.zoom * Math.exp(-e.deltaY * 0.0015)));
      this.lastTouch = performance.now();
    }, { passive: false });
    canvas.addEventListener("dblclick", () => { this.yaw = 0; this.pitch = 0; this.zoom = 1; this.lastTouch = -1e9; });
  }

  setChannels(channelToPn) { this.channelToPn = channelToPn; }

  // one keypress: the active input channels (-> real PNs) and active Kenyon cells
  press(pns, kcs) {
    for (const k of kcs) this.kcGlow[k] = 1;
    if (this.channelToPn) for (const c of pns) this.pnGlow[this.channelToPn[c]] = 1;
    this.activeKcs = kcs.length;
  }

  dopamine(signal) {
    if (signal > 0) this.reward = Math.min(1, this.reward + Math.max(0.35, signal));
    else if (signal < 0) this.punish = Math.min(1, this.punish + 0.5);
  }

  draw(dt) {
    const { c, g } = this;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== c.clientWidth * dpr) { c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr; }
    const W = c.width, H = c.height;
    if (performance.now() - this.lastTouch > 8000) this.yaw += dt * 0.2;   // idle: slow turn
    const cy_ = Math.cos(this.yaw), sy_ = Math.sin(this.yaw), cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const s = W * 0.46 * this.zoom, cx = W / 2, cy = H * 0.5;
    // brain coordinates: x across, y down (ventral), z front-back. Yaw about the vertical
    // axis, then pitch about the horizontal one.
    const P = (p) => {
      const x1 = p[0] * cy_ + p[2] * sy_, z1 = -p[0] * sy_ + p[2] * cy_;
      return [cx + x1 * s, cy + (p[1] * cp - z1 * sp) * s];
    };
    g.clearRect(0, 0, W, H);
    g.globalCompositeOperation = "lighter";
    g.fillStyle = "rgba(70,140,255,0.16)";
    for (const p of this.brain) { const [x, y] = P(p); g.fillRect(x, y, 1.4 * dpr, 1.4 * dpr); }
    // Kenyon cells: dim at rest, bright cyan while active
    for (let i = 0; i < this.kc.length; i++) {
      const glow = this.kcGlow[i];
      const [x, y] = P(this.kc[i]);
      if (glow > 0.02) {
        g.fillStyle = `rgba(120,240,255,${0.25 + 0.75 * glow})`;
        const r = (1.5 + 2.5 * glow) * dpr; g.fillRect(x - r / 2, y - r / 2, r, r);
        this.kcGlow[i] = glow * Math.exp(-dt * 3.5);
      } else {
        g.fillStyle = "rgba(90,170,255,0.22)"; g.fillRect(x, y, 1.2 * dpr, 1.2 * dpr);
      }
    }
    for (let i = 0; i < this.pn.length; i++) {
      const glow = this.pnGlow[i];
      const [x, y] = P(this.pn[i]);
      g.fillStyle = `rgba(200,120,255,${0.25 + 0.75 * glow})`;
      const r = (1.8 + 3 * glow) * dpr; g.fillRect(x - r / 2, y - r / 2, r, r);
      this.pnGlow[i] = glow * Math.exp(-dt * 3);
    }
    for (let i = 0; i < this.dan.length; i++) {
      const [x, y] = P(this.dan[i]);
      const on = this.pam[i] ? this.reward : this.punish;
      g.fillStyle = this.pam[i] ? `rgba(90,255,140,${0.2 + 0.8 * on})` : `rgba(255,80,70,${0.2 + 0.8 * on})`;
      const r = (1.8 + 4 * on) * dpr; g.fillRect(x - r / 2, y - r / 2, r, r);
    }
    g.fillStyle = "rgba(255,210,90,0.8)";
    for (const p of this.mbon) { const [x, y] = P(p); g.fillRect(x - dpr, y - dpr, 2.2 * dpr, 2.2 * dpr); }
    g.globalCompositeOperation = "source-over";
    this.reward *= Math.exp(-dt * 2.2); this.punish *= Math.exp(-dt * 2.2);
  }
}
