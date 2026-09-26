// flyspeare viewer: plays back the watched fly's real attempts — every key it presses, the
// neurons that fired, the dopamine it got — and lets you run, pause, save and load rooms.
import { BrainMap } from "./brain.js";
import { loadCrowd } from "./crowd.js";
import { loadFly } from "./fly.js";
import { RealPace } from "./realpace.js";
import { Stage } from "./stage.js";

const $ = (id) => document.getElementById(id);
const ALPHA = "abcdefghijklmnopqrstuvwxyz";
const api = async (path, body, method) => {
  const r = await fetch("/api/" + path, method ? { method } : body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (n) => Number(n).toLocaleString("en-GB");
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 2600); }
function flyTime(presses) {
  const s = presses * 0.3;
  return s < 3600 ? `${(s / 60).toFixed(0)} min` : s < 86400 * 2 ? `${(s / 3600).toFixed(1)} h` : s < 86400 * 730 ? `${(s / 86400).toFixed(1)} d` : `${(s / 86400 / 365).toFixed(1)} yr`;
}

const S = {
  room: localStorage.getItem("room") || null, fly: Number(localStorage.getItem("fly") || 0),
  follow: localStorage.getItem("follow") !== "0", status: null, rooms: [],
  lastSeq: -1, queue: [], skipped: 0, word: -1, struck: [], paper: null, speed: "real", paused: false,
  run: { base: 0, at: 0 },   // training time from the room, ticked locally between polls
};
// at max speed the stream plays at its true rate; at real fly speed every key is animated
const realPaceOn = () => S.speed === "max" && !S.paused;
const waitWhilePaused = async () => { while (S.paused) await sleep(100); };

// ---------------------------------------------------------------- setup
const [fly, fw] = await Promise.all([loadFly(), api("flywire")]);
const stage = new Stage($("scene"), fly);
const brain = new BrainMap($("brain"), fw);
const pace = new RealPace(stage, brain);
const crowd = await loadCrowd(stage);
let paperDirty = 0;
stage.onFrame = (dt) => {
  brain.draw(dt);
  // z z z above its head while it sleeps
  const z = $("zzz");
  if (stage.rest.kind === "sleep" && stage.rest.blend > 0.5) {
    const p = stage.headOnScreen();
    z.hidden = !p.visible; z.style.left = `${p.x + 40}px`; z.style.top = `${p.y - 110}px`;
  } else z.hidden = true;
  renderMode();
  if (!realPaceOn()) return;
  const r = pace.frame(dt, () => { paperDirty++; });
  const c = pace.counters();
  if (c) showWord(c.word, c.tries);
  renderPacePaper();
  // the right-hand panel shows a real, very recent keypress about ten times a second
  const items = S.live?.items;
  if (items?.length && performance.now() - (stage.onFrame.panelT || 0) > 100) {
    stage.onFrame.panelT = performance.now();
    const it = items[items.length - 1 - Math.floor(Math.random() * Math.min(10, items.length))];
    const i = Math.floor(Math.random() * it.typed.length);
    $("kcCount").textContent = it.kcs[i].length;
    showDopamine(it);
  }
  const s = pace.stats;
  $("paceInfo").innerHTML = `every attempt shown · <b>${fmt(Math.round(s.attemptsPerS))}</b>/s · ` +
    `<b>${fmt(Math.round(s.keysPerS * 0.3))}×</b> a real fly`;
};
window.flyspeare = { stage, fly, brain, S, pace, crowd }; // for debugging from the console
stage.start();

function showWord(word, tries) {
  const n = S.paper?.n_words ?? 988342;
  $("word").textContent = `${fmt(word + 1)} / ${fmt(n)}`;
  $("pct").textContent = `word · ${(100 * word / n).toFixed(3)}% of Shakespeare`;
  $("tries").textContent = fmt(tries);
}
function showDopamine(it) {
  const d = $("dopa"), hits = it.dopamine.filter((x) => x > 0).length;
  d.className = "dopa " + (it.correct || hits ? "pam" : "ppl1");
  d.textContent = it.correct ? "reward · word right" : hits ? `reward ×${hits}` : "punished";
}

// ---------------------------------------------------------------- controls
document.querySelectorAll("[data-cam]").forEach((b) => b.onclick = () => {
  if (b.dataset.cam === "hall") stage.viewAt(crowd.overview()); else stage.view(b.dataset.cam);
  document.querySelectorAll("[data-cam]").forEach((x) => x.classList.toggle("on", x === b));
});
document.querySelectorAll("[data-speed]").forEach((b) => b.onclick = () => control({ speed: b.dataset.speed }));
$("pause").onclick = async () => {
  const r = S.rooms.find((x) => x.name === S.room);
  if (r && !r.running) {   // a stopped room: load it back, brains and progress restored
    await api(`rooms/${S.room}/load`, { speed: r.speed || "max" });
    toast(`Loading ${S.room}…`);
    return setTimeout(() => selectRoom(S.room), 2500);
  }
  control({ paused: !S.paused });
};
$("menuBtn").onclick = (e) => { e.stopPropagation(); $("menu").classList.toggle("open"); };
document.addEventListener("click", (e) => { if (!$("menu").contains(e.target)) $("menu").classList.remove("open"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("menu").classList.remove("open"); });
$("roomSel").onchange = () => selectRoom($("roomSel").value);
$("save").onclick = async () => { await control({ save: true }); toast("Saved"); };
$("stop").onclick = async () => { if (!S.room) return; await api(`rooms/${S.room}/stop`, {}); toast(`Stopping ${S.room} — saving first`); setTimeout(refreshRooms, 2000); };
// delete asks twice: the first click arms it for a few seconds, the second deletes
$("del").onclick = async () => {
  const r = S.rooms.find((x) => x.name === S.room);
  if (!r) return;
  if (r.running) return toast("Stop the room before deleting it");
  if (!$("del").dataset.armed) {
    $("del").dataset.armed = "1"; $("del").textContent = `Click again to delete “${r.name}”`; $("del").classList.add("danger");
    return setTimeout(() => { delete $("del").dataset.armed; $("del").textContent = "Delete room…"; $("del").classList.remove("danger"); }, 4000);
  }
  try { await api(`rooms/${r.name}`, undefined, "DELETE"); } catch (e) { return toast(e.message); }
  toast(`Deleted ${r.name}`);
  delete $("del").dataset.armed; $("del").textContent = "Delete room…"; $("del").classList.remove("danger");
  S.room = null; localStorage.removeItem("room");
  await refreshRooms();
  const next = S.rooms.find((x) => x.running) || S.rooms[0];
  if (next) selectRoom(next.name); else renderControls();
};
$("follow").onclick = () => { S.follow = !S.follow; localStorage.setItem("follow", S.follow ? "1" : "0"); $("follow").classList.toggle("on", S.follow); };
$("follow").classList.toggle("on", S.follow);
$("watchFly").onclick = () => { S.follow = false; $("follow").classList.remove("on"); watch(Number($("flyId").value)); };
$("newRoom").onclick = async () => {
  const name = $("newName").value.trim();
  if (!name) return toast("Give the room a name");
  try {
    await api("rooms", { name, flies: Number($("newFlies").value), speed: $("newSpeed").value });
    toast(`Starting ${name}…`);
    setTimeout(() => selectRoom(name), 2500);
  } catch (e) { toast(e.message); }
};

async function control(body) {
  if (!S.room) return toast("Pick a room first");
  const c = await api(`rooms/${S.room}/control`, body);
  S.speed = c.speed; S.paused = c.paused;
  renderControls();
}

function renderControls() {
  renderMode();
  const r = S.rooms.find((x) => x.name === S.room);
  const running = !!r?.running;
  document.querySelectorAll("[data-speed]").forEach((b) => b.classList.toggle("on", running && b.dataset.speed === S.speed));
  $("pause").textContent = !r ? "–" : !running ? "Load" : S.paused ? "Resume" : "Pause";
  const live = running && !S.paused;
  $("state").classList.toggle("live", live);
  $("stateText").textContent = !r ? "no room" : !running ? "stopped" : S.paused ? "paused" :
    `fly #${S.fly}${S.follow && r.flies > 1 ? " (leader)" : ""} · ${S.speed === "real" ? "real fly speed" : "max speed"}${S.live?.asleep_until ? " · asleep" : S.live?.eating_until ? " · eating" : ""}`;
  $("stop").disabled = !running;
  $("del").disabled = running;
  $("hallBtn").hidden = !(r && r.flies > 1);
}

// training time ticks every second while running and not paused
const fmtDur = (s) => {
  s = Math.floor(s);
  const d = Math.floor(s / 86400), h = Math.floor(s / 3600) % 24, m = Math.floor(s / 60) % 60, x = s % 60;
  return d ? `${d}d ${h}h ${m}m` : h ? `${h}h ${m}m ${x}s` : `${m}m ${x}s`;
};
setInterval(() => {
  const r = S.rooms.find((x) => x.name === S.room);
  const live = r?.running && !S.paused;
  $("runTime").textContent = r ? fmtDur(S.run.base + (live ? (performance.now() - S.run.at) / 1000 : 0)) : "–";
}, 1000);

async function refreshRooms() {
  try { S.rooms = await api("rooms"); } catch { return; }
  $("roomSel").innerHTML = S.rooms.map((r) =>
    `<option value="${r.name}" ${r.name === S.room ? "selected" : ""}>${r.name} · ${r.flies} ${r.flies === 1 ? "fly" : "flies"}${r.running ? "" : " (stopped)"}</option>`).join("")
    || `<option>no rooms</option>`;
  $("empty").hidden = S.rooms.some((r) => r.running);
  renderControls();
}

async function selectRoom(name) {
  S.room = name; localStorage.setItem("room", name);
  S.lastSeq = -1; S.queue = []; S.word = -1;
  await refreshRooms();
  await pollStatus();
  await watch(S.follow && S.status ? S.status.leader : S.fly);
}

function renderMode() {
  if (!realPaceOn()) $("paceInfo").textContent = S.paused ? "paused" : S.speed === "real" ? "real fly speed · every key shown" : "";
}

async function watch(id) {
  if (!S.room) return;
  pace.reset();
  S.fly = id; localStorage.setItem("fly", id); $("flyId").value = id;
  S.lastSeq = -1; S.queue = []; S.word = -1; S.struck = [];
  resetPaper();
  await api(`rooms/${S.room}/control`, { watch: [id] }).catch(() => {});
  $("flyLabel").textContent = `Fly #${id}`;
  try { brain.setChannels((await api(`rooms/${S.room}/fly/${id}/brain`)).flywire.channel_to_pn); } catch { brain.setChannels(null); }
  refreshPaper();
}

// ---------------------------------------------------------------- the sim clock
// The fly's own time, running at its sped-up rate and ticking smoothly through typing, meals and
// sleep alike. While it rests, its saved clock already reads the moment it will wake, so the
// display counts up to it; while it types, it runs on from the last reading.
function measureRate(prev, live) {
  const c = (l) => l?.inner?.clock_s ?? l?.inner?.awake_s;
  if (prev && c(prev) != null && c(live) != null && live.time > prev.time && c(live) >= c(prev) && S.fly === S.rateFly && S.room === S.rateRoom) {
    const r = (c(live) - c(prev)) / (live.time - prev.time);
    S.measuredRate = S.measuredRate ? S.measuredRate * 0.8 + r * 0.2 : r;
  } else if (S.fly !== S.rateFly || S.room !== S.rateRoom) S.measuredRate = 0;
  S.rateFly = S.fly; S.rateRoom = S.room;
}

function simClock() {
  const l = S.live, inner = l?.inner;
  if (!inner) return null;
  // rooms started before the clock existed report only time awake, and no rate: measure it
  const rate = l.sim_rate || S.measuredRate || (S.speed === "real" ? 1 : 0);
  const now = Date.now() / 1000;
  const restUntil = l.rest_until || l.asleep_until || l.eating_until;   // its clock already counts the whole rest
  let clock = inner.clock_s ?? inner.awake_s ?? 0;
  if (restUntil && restUntil > now) clock -= (restUntil - now) * rate;
  // after the snapshot (or after a rest it already counted) time runs on at its rate
  else if (!S.paused && rate) clock += Math.max(0, Math.min(2, now - Math.max(l.time, restUntil || 0))) * rate;
  // never run the shown clock backwards when a new snapshot lands a little behind the estimate
  const key = `${S.room}/${S.fly}`;
  if (simClock.key === key && clock < simClock.last && simClock.last - clock < 6 * 3600) clock = simClock.last;
  simClock.key = key; simClock.last = clock;
  const t = 8 * 3600 + clock;
  return { day: Math.floor(t / 86400) + 1, hour: (t % 86400) / 3600, rate };
}
const hhmm = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.floor((h % 1) * 60)).padStart(2, "0")}`;
setInterval(() => {
  const c = simClock(), r = S.rooms.find((x) => x.name === S.room);
  $("simBig").hidden = !c || !r?.running;
  if (!c || !r?.running || S.paused) return;
  $("simTime").textContent = `Day ${fmt(c.day)} · ${hhmm(c.hour)}`;
  $("simRate").textContent = c.rate > 1.5 ? `sim time · ×${fmt(Math.round(c.rate))} real` : "sim time · real fly speed";
  const night = c.hour >= 21 || c.hour < 6;
  $("simSky").textContent = night ? "☾" : c.hour < 8 || c.hour >= 19 ? "◐" : "☀";
  if (S.live?.asleep_until) $("dayNote").textContent = `Asleep · ${hhmm(c.hour)} → 08:00 sim time`;
}, 100);

// the rest animation follows its live feed: asleep, then eating. A meal shows for at least
// 0.8 s (at max speed a 20-minute meal lasts a fraction of a second); breakfast starts when it wakes
let mealEndAt = 0, mealSeen = 0;
function showMealFor(end) { mealEndAt = Math.max(mealEndAt, end); }
function driveRest(live) {
  const now = Date.now() / 1000;
  if (live?.eating_until && live.eating_until !== mealSeen) {
    mealSeen = live.eating_until;
    showMealFor(Math.max(live.eating_until, Math.max(now, live.asleep_until || 0) + 0.8));
  }
  if (live?.asleep_until && live.asleep_until > now) stage.setRest("sleep");
  else if (now < mealEndAt) {
    if (stage.rest.kind !== "eat") {
      stage.setRest("eat");
      const meal = [...(live?.events || [])].reverse().find((e) => e.type === "meal");
      toast(meal?.meal === "dinner" ? "Dinner — sugar water, 20 sim-minutes" : "Breakfast — sugar water, 20 sim-minutes");
    }
  } else if (stage.rest.kind) stage.setRest(null);
}
setInterval(() => driveRest(S.live), 100);

// ---------------------------------------------------------------- its day: nights and meals
let lastEventKey = null, nightTimer = null;
function showDay(live) {
  const asleep = !!live.asleep_until;
  const left = (until) => {
    const s = Math.max(0, Math.round(until - Date.now() / 1000));
    return s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
  };
  if (asleep) {
    stage.nightGoal = 1;
    $("dayNote").hidden = false;
    $("dayNote").textContent = `Asleep · wakes at 08:00 fly time · in ${left(live.asleep_until)}`;
  } else if (live.eating_until) {
    const meal = [...(live.events || [])].reverse().find((e) => e.type === "meal");
    $("dayNote").hidden = false;
    $("dayNote").textContent = `Eating ${meal ? meal.meal : ""} · 20 fly-minutes · back in ${left(live.eating_until)}`;
    nightTimer = nightTimer || setTimeout(() => { nightTimer = null; }, 400);
  }
  const evs = live.events || [];
  const last = evs[evs.length - 1];
  const key = last ? `${last.type}:${last.clock_s}` : null;
  if (lastEventKey === null) { lastEventKey = key; if (!asleep) { stage.nightGoal = 0; $("dayNote").hidden = true; } return; }
  if (key === lastEventKey) { if (!asleep && !live.eating_until && !nightTimer) { stage.nightGoal = 0; $("dayNote").hidden = true; } return; }
  // every new event since the last poll (at max speed a whole night can pass between polls)
  const fresh = evs.slice(evs.findIndex((e) => `${e.type}:${e.clock_s}` === lastEventKey) + 1);
  lastEventKey = key;
  const night = [...fresh].reverse().find((e) => e.type === "sleep");
  if (night && !asleep && !live.eating_until) {
    stage.nightGoal = 1;
    $("dayNote").hidden = false;
    $("dayNote").textContent = `Night — slept ${Math.round(night.hours)} h, replayed ${fmt(night.replayed)} sweet moments into long-term memory`;
    clearTimeout(nightTimer);
    nightTimer = setTimeout(() => { stage.nightGoal = 0; $("dayNote").hidden = true; nightTimer = null; }, 1800);
  }
  // a meal that came and went between polls (breakfast is announced with the night, above)
  const meal = [...fresh].reverse().find((e) => e.type === "meal");
  if (meal && !asleep && !live.eating_until) showMealFor(Date.now() / 1000 + 0.8);
}

// ---------------------------------------------------------------- how the fly feels
const pct = (x) => `${Math.round(x * 100)}%`;
const bar01 = (g) => g.value;
const GAUGES = [
  // built up over its whole life (inner.py)
  ["fatigue", (g) => pct(g.value), bar01, () => "neg"],
  ["sleep_pressure", (g) => pct(g.value), bar01, () => "neg"],
  ["hunger", (g) => pct(g.value), bar01, () => "neg"],
  ["stress", (g) => pct(g.value), bar01, () => "neg"],
  ["helplessness", (g) => pct(g.value), bar01, () => "neg"],
  ["satisfaction", (g) => pct(g.value), bar01, () => "pos"],
  ["habituation", (g) => pct(g.value), bar01, () => ""],
  ["tone", (g) => (g.value >= 0 ? "+" : "") + g.value.toFixed(3), (g) => Math.min(1, Math.abs(g.value) * 8), (g) => (g.value < 0 ? "neg" : "pos")],
  ["memory_short", (g) => pct(g.value), bar01, () => "neg"],
  ["memory_long", (g) => `${(g.value * 100).toFixed(1)}%`, (g) => Math.min(1, g.value * 5), () => "pos"],
  // this moment
  ["reward", (g) => pct(g.value), bar01, () => "pos"],
  ["punishment", (g) => pct(g.value), bar01, () => "neg"],
  ["frustration", (g) => `${fmt(g.value)}× usual`, (g) => Math.min(1, Math.log10(1 + g.value) / 4), () => "neg"],
  ["certainty", (g) => pct(g.value), bar01, () => ""],
  ["age", (g) => `${g.value.toFixed(1)} days · ${g.lifespans.toFixed(2)} lives`, (g) => Math.min(1, g.lifespans), () => ""],
  ["clock", (g) => `${String(Math.floor(g.value)).padStart(2, "0")}:${String(Math.floor((g.value % 1) * 60)).padStart(2, "0")}${g.asleep ? " · sleep time" : ""}`, (g) => g.value / 24, () => ""],
  ["left_arm", (g) => `left ${pct(g.value)} · right ${pct(1 - g.value)}`, bar01, () => ""],
];
const BUILT = new Set(["fatigue", "sleep_pressure", "hunger", "stress", "helplessness", "satisfaction", "habituation", "tone", "memory_short", "memory_long"]);
// "How do you feel?" captures one moment: the fly's state when you click. It does not update.
async function askFeelings() {
  if (!S.room) return;
  $("feelSummary").innerHTML = `<div class="vl" style="opacity:.6">Listening…</div>`;
  $("feelGauges").innerHTML = "";
  let f;
  try { f = await api(`rooms/${S.room}/fly/${S.fly}/feelings`); } catch (e) { $("feelSummary").textContent = e.message; return; }
  const when = new Date((f.captured_at || Date.now() / 1000) * 1000).toLocaleTimeString("en-GB");
  $("feelTitle").textContent = `Fly #${S.fly} said, at ${when}`;
  $("feelAge").textContent = `word ${fmt(f.word + 1)} “${f.target}”, try ${fmt(f.attempts)}`;
  $("feelSummary").innerHTML = f.voice.map((l, i) =>
    `<div class="vl" title="${esc(l.because)}" style="animation-delay:${i * 0.35}s">${esc(l.text)}</div><div class="why">${esc(l.because)}</div>`).join("");
  const card = ([k, show, fill, cls]) => {
    const g = f.gauges[k];
    return `<div class="gauge"><div class="top"><span>${g.label}</span><b>${show(g)}</b></div>
      <div class="bar"><i class="${cls(g)}" style="width:${Math.max(1, fill(g) * 100)}%"></i></div><small>${g.source}</small></div>`;
  };
  const have = GAUGES.filter(([k]) => f.gauges[k]);
  const built = have.filter(([k]) => BUILT.has(k)), now = have.filter(([k]) => !BUILT.has(k));
  $("feelGauges").innerHTML =
    (built.length ? `<h5>Built up over its whole life</h5>${built.map(card).join("")}` :
      `<h5>Built up over its whole life</h5><small class="span2">Not recorded yet: this room was started before these states existed. Stop and Load it once to begin.</small>`) +
    `<h5>This moment</h5>${now.map(card).join("")}`;
  $("feelNote").textContent = f.disclaimer;
}
$("askBtn").onclick = () => { $("feel").hidden = false; askFeelings(); };
$("askAgain").onclick = () => askFeelings();
$("whyBtn").onclick = () => { $("feelSummary").classList.toggle("show-why"); $("whyBtn").classList.toggle("on"); };
$("feelClose").onclick = () => { $("feel").hidden = true; };
$("feel").onclick = (e) => { if (e.target === $("feel")) $("feel").hidden = true; };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("feel").hidden = true; });

// ---------------------------------------------------------------- polling
async function pollStatus() {
  if (!S.room) return;
  try {
    const st = await api(`rooms/${S.room}/status`);
    S.status = st; S.speed = st.speed; S.paused = st.paused;
    S.run = { base: st.run_seconds || 0, at: performance.now() - Math.max(0, Date.now() / 1000 - st.updated) * 1000 };
    renderControls();
    crowd.setFlies(st.flies.length);
    crowd.update(st.flies, S.fly);
    if (S.follow && st.leader != null && st.leader !== S.fly) await watch(st.leader);
    const top = [...st.flies].sort((a, b) => b.word - a.word || a.presses - b.presses).slice(0, 10);
    $("flies").innerHTML = top.map((f, i) => `<button data-fly="${f.id}" class="${f.id === S.fly ? "on" : ""}">
      <span>${i + 1}. fly ${f.id}</span><small>word ${fmt(f.word)}</small></button>`).join("");
    $("rate").textContent = fmt(Math.round(st.presses_per_s || 0));
    $("flies").querySelectorAll("[data-fly]").forEach((b) => b.onclick = () => { S.follow = false; $("follow").classList.remove("on"); watch(Number(b.dataset.fly)); });
  } catch { /* room not started yet */ }
}

async function pollLive() {
  if (!S.room) return;
  let live;
  try { live = await api(`rooms/${S.room}/fly/${S.fly}/live`); } catch { return; }
  if (S.paused) return;      // paused: nothing new to show, and nothing moves
  showDay(live);
  measureRate(S.live, live);
  S.live = live;
  pace.ingest(live);
  if (realPaceOn()) return;  // real pace plays the stream; slow-mo plays whole attempts below
  const fresh = live.items.filter((it) => it.seq > S.lastSeq);
  if (!fresh.length) return;
  S.lastSeq = fresh[fresh.length - 1].seq;
  if (S.lastSeq - fresh[0].seq + 1 > fresh.length) S.skipped += 1;
  S.queue.push(...fresh);
  // at max speed the fly types far faster than anyone can watch: keep only the newest few
  const keep = S.speed === "max" ? 2 : 8;
  if (S.queue.length > keep) { S.skipped += S.queue.length - keep; S.queue.splice(0, S.queue.length - keep); }
}

// the written text: one buffer from P.start to P.end (character offsets into the works),
// grown at the end as words are committed and at the start as you scroll back
const P = { start: 0, end: 0, text: "", gap: "", loading: false };
function resetPaper() { Object.assign(P, { start: 0, end: 0, text: "", gap: "" }); $("written").textContent = ""; }
async function refreshPaper() {
  if (!S.room) return;
  let t;
  try { t = await api(`rooms/${S.room}/fly/${S.fly}/paper?size=4000`); } catch { return; }
  S.paper = t;
  if (!P.text || t.start > P.end || t.end < P.end) Object.assign(P, { start: t.start, end: t.end, text: t.text });
  else if (t.end > P.end) { P.text += t.text.slice(P.end - t.start); P.end = t.end; }
  P.gap = t.gap;
  drawWritten();
  if (!realPaceOn()) renderPaper("");
}
function drawWritten() {
  const el = $("scroll"), stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  const full = P.text + P.gap;
  if ($("written").textContent !== full) $("written").textContent = full;
  $("begin").hidden = P.start > 0; $("older").hidden = P.start === 0;
  if (stick) el.scrollTop = el.scrollHeight;
  $("jump").hidden = stick;
}
$("scroll").addEventListener("scroll", async () => {
  const el = $("scroll");
  $("jump").hidden = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  if (el.scrollTop > 200 || P.start === 0 || P.loading || !S.room) return;
  P.loading = true;
  try {
    const t = await api(`rooms/${S.room}/fly/${S.fly}/paper?before=${P.start}&size=20000`);
    const h = el.scrollHeight;
    P.text = t.text + P.text; P.start = t.start;
    drawWritten();
    el.scrollTop += el.scrollHeight - h;     // keep your place while older text appears above
  } finally { P.loading = false; }
});
$("jump").onclick = () => { const el = $("scroll"); el.scrollTop = el.scrollHeight; $("jump").hidden = true; };

// real pace: the torrent of failed tries under the text; the 3D sheet a little less often
let lastPaperDraw = 0;
function renderPacePaper() {
  const now = performance.now();
  if (now - lastPaperDraw < 33) return;          // ~30 updates a second is plenty for text
  lastPaperDraw = now;
  renderTries(pace.struck.slice(-120), pace.current);
  if (now - (renderPacePaper.tex || 0) > 120) {
    renderPacePaper.tex = now;
    stage.tw.drawPaper(paperLines(P.text + P.gap, 5, 30), pace.current, pace.struck.slice(-3));
  }
}
function renderTries(struck, attempt, flash) {
  const cls = flash === "good" ? "ok" : "now";
  $("triesText").innerHTML = `<span>${struck.map((s) => `<s>${esc(s)}</s>`).join(" ")} <span class="${cls}">${esc(attempt)}▏</span></span>`;
}

setInterval(pollStatus, 1500);
setInterval(pollLive, 250);
setInterval(() => { if (realPaceOn() && paperDirty) { paperDirty = 0; refreshPaper(); } }, 500);
setInterval(refreshPaper, 4000);
setInterval(refreshRooms, 8000);

// ---------------------------------------------------------------- the paper
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
function paperLines(text, n, width) {
  // wrap at word boundaries, keeping the text's own line breaks
  const out = [];
  for (const raw of text.split("\n")) {
    let line = "";
    for (const w of raw.trim().split(/\s+/)) {
      if (line && (line + " " + w).length > width) { out.push(line); line = w; }
      else line = line ? line + " " + w : w;
    }
    out.push(line);
  }
  while (out.length && out[out.length - 1] === "" && !text.endsWith("\n")) out.pop();
  return out.slice(-n);
}
function renderPaper(attempt, flash) {
  renderTries(S.struck.slice(-8), attempt, flash);
  stage.tw.drawPaper(paperLines(P.text + P.gap, 5, 30), attempt, S.struck, flash);
}

// ---------------------------------------------------------------- playback
async function playAttempt(it) {
  if (it.word !== S.word) { S.word = it.word; S.struck = []; }
  showWord(it.word, S.live?.word === it.word ? S.live.attempts : 0);
  const perKey = S.speed === "real" ? 300 : 180;
  let typed = "";
  for (let i = 0; i < it.typed.length; i++) {
    await waitWhilePaused();
    brain.press(it.pns[i], it.kcs[i]);
    $("kcCount").textContent = it.kcs[i].length;
    stage.tw.setColumn(i);
    await stage.press(it.typed[i], perKey);
    typed += it.typed[i];
    renderPaper(typed);
  }
  const reward = Math.max(0, ...it.dopamine), punish = Math.min(0, ...it.dopamine);
  showDopamine(it);
  if (it.correct) {
    brain.dopamine(1);
    renderPaper(typed, "good");
    await sleep(perKey * 1.6);
    S.struck = [];
    await refreshPaper();
  } else {
    if (reward > 0) brain.dopamine(reward);
    if (punish < 0) brain.dopamine(punish);
    S.struck.push(typed);
    renderPaper("", "bad");
    await sleep(perKey * 0.8);
  }
  stage.tw.setColumn(0);
}

(async function player() {
  for (;;) {
    if (realPaceOn() || S.paused) { if (!S.paused) S.queue.length = 0; await sleep(120); continue; }
    const it = S.queue.shift();
    if (!it) { await sleep(120); continue; }
    try { await playAttempt(it); } catch (e) { console.error(e); await sleep(500); }
  }
})();

// ---------------------------------------------------------------- start
await refreshRooms();
if (S.room && S.rooms.some((r) => r.name === S.room)) selectRoom(S.room);
else {
  const running = S.rooms.find((r) => r.running);
  if (running) selectRoom(running.name);
  else renderControls();
}
