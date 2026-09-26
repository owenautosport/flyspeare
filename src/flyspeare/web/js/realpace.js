// Real-pace mode: plays the fly's attempts at the rate the computer is really making them.
// Every attempt in the stream is consumed in real time: its letters go onto the paper, its
// keys dip on the typewriter, and the counters tick at the true rate. The arms can only be
// drawn so fast, so they strike the latest key roughly ten times a second, and the readout
// says how many real keypresses each stroke stands for.
const ALPHA = "abcdefghijklmnopqrstuvwxyz";

export class RealPace {
  constructor(stage, brain) {
    this.stage = stage;
    this.brain = brain;
    this.reset();
  }

  reset() {
    this.buf = [];                 // attempts received but not yet shown: {word, typed, correct}
    this.lastSeq = -1;
    this.rate = 0;                 // attempts per second, smoothed
    this.keyRate = 0;              // keypresses per second, smoothed
    this.acc = 0;
    this.prev = null;              // previous live snapshot {seq, time}
    this.heat = Object.fromEntries([...ALPHA].map((c) => [c, 0]));
    this.struck = [];              // failed attempts on the current word, newest last
    this.word = -1;
    this.tries = 0;                // attempts on the word being shown
    this.current = "";
    this.shown = 0;                // attempts shown in the last second (for the readout)
    this.strokes = 0;
    this.second = { t: performance.now(), attempts: 0, keys: 0, strokes: 0 };
    this.stats = { attemptsPerS: 0, keysPerS: 0, strokesPerS: 0 };
    this.committed = 0;
  }

  // a live.json snapshot arrived: queue every attempt we have not seen yet
  ingest(live) {
    const st = live.stream;
    if (!st || !st.typed.length) return;
    if (this.lastSeq < 0) this.lastSeq = st.last_seq - Math.min(st.typed.length, 50);  // start near now
    const from = Math.max(0, this.lastSeq + 1 - st.first_seq);
    for (let i = from; i < st.typed.length; i++) {
      this.buf.push({ word: st.word[i], typed: st.typed[i], correct: false });
    }
    for (const i of st.correct) if (i >= from) this.buf[this.buf.length - (st.typed.length - i)].correct = true;
    if (this.prev) {
      const dt = live.time - this.prev.time;
      if (dt > 0.05) {
        const r = (st.last_seq - this.prev.seq) / dt;
        this.rate = this.rate ? 0.7 * this.rate + 0.3 * r : r;
      }
    }
    this.prev = { seq: st.last_seq, time: live.time };
    this.lastSeq = st.last_seq;
    this.live = live;
  }

  // one animation frame: show exactly as many attempts as the fly made in `dt` seconds
  frame(dt, onCommit) {
    if (!this.live) return null;
    const need = this.rate * dt + this.acc;
    let n = Math.floor(need);
    this.acc = need - n;
    // never fall more than ~1 s behind the real fly: skip ahead if the tab was busy
    const lag = this.buf.length - Math.max(20, this.rate * 1.0);
    if (lag > 0) this.buf.splice(0, Math.floor(lag));
    n = Math.min(n, this.buf.length);
    let keys = 0, lastLetter = null, anyCorrect = false;
    for (let k = 0; k < n; k++) {
      const a = this.buf.shift();
      if (a.word !== this.word) {
        // joining mid-word: start from the fly's real count, minus what is still queued
        const l = this.live;
        this.tries = this.word < 0 && l && a.word === l.word
          ? Math.max(0, l.attempts - this.buf.filter((b) => b.word === a.word).length - 1) : 0;
        this.word = a.word; this.struck = [];
      }
      this.tries++;
      for (const c of a.typed) { this.heat[c] += 1; lastLetter = c; }
      keys += a.typed.length;
      if (a.correct) { anyCorrect = true; this.struck = []; this.current = ""; onCommit?.(a); this.committed++; }
      else { this.struck.push(a.typed); if (this.struck.length > 400) this.struck.splice(0, 200); this.current = a.typed; }
    }
    // keys dip in proportion to how often they were hit this instant
    for (const c of ALPHA) {
      this.stage.tw.press(c, Math.min(1, this.heat[c] * 0.6));
      this.heat[c] *= Math.exp(-dt * 14);
    }
    // the arms strike the most recent key as fast as they can be drawn
    if (lastLetter && !this.stage.strike) { this.stage.press(lastLetter, 95); this.strokes++; }
    // the brain map flickers with real recent activity; dopamine follows the outcomes
    const items = this.live.items;
    if (items?.length && n) {
      const it = items[Math.floor(Math.random() * items.length)];
      const i = Math.floor(Math.random() * it.kcs.length);
      this.brain.press(it.pns[i], it.kcs[i]);
      if (anyCorrect) this.brain.dopamine(1); else if (Math.random() < 0.3) this.brain.dopamine(-0.05);
    }
    // per-second readout
    const s = this.second;
    s.attempts += n; s.keys += keys;
    const now = performance.now();
    if (now - s.t >= 1000) {
      const secs = (now - s.t) / 1000;
      this.stats = { attemptsPerS: s.attempts / secs, keysPerS: s.keys / secs, strokesPerS: this.strokes / secs };
      this.second = { t: now, attempts: 0, keys: 0 }; this.strokes = 0;
    }
    return { n, keys };
  }

  // counters that tick at the true rate: the snapshot minus what is still waiting to be shown
  counters() {
    const l = this.live;
    if (!l) return null;
    let pendKeys = 0;
    for (const a of this.buf) pendKeys += a.typed.length;
    return { presses: l.presses - pendKeys, tries: this.tries, word: this.word >= 0 ? this.word : l.word };
  }
}
