// One machine, five states: request -> await -> install -> done | halt.
//
// The page holds NO recipe. After approval it POSTs its one-time token and
// receives a plan (typed ops + short-lived signed URLs). Telemetry is REACHABLE
// (collapsed rail, auto-opens on failure) but shows verbs, human labels and
// hashes only: never filenames, commands, or property names.
// transport.js pulls in ya-webadb via bare specifiers, so it only resolves
// through the bundler. It is loaded LAZILY at connect time: a missing or
// unbuilt ADB dependency must never stop the page from rendering or the VIN
// from being typed. (A top-level import here silently killed the whole app.)
let _transport = null;
async function transport() {
  if (!_transport) _transport = await import("./transport.js");
  return _transport;
}

const CFG = window.CARAPK;
const $ = (id) => document.getElementById(id);
const API = CFG.API.replace(/\/$/, "");
const stage = $("stage");

const state = { rid: null, token: null, profile: null, plan: null, adb: null,
                resumeFrom: 0, device: "", ops: 0 };

const LABEL = { request: ["VIN", "0 / 17"], await: ["APPROVAL CODE", "AWAITING"],
                install: ["INSTALLING", ""], done: ["COMPLETE", ""], halt: ["STOPPED", ""] };

function setPhase(p) {
  stage.dataset.phase = p;
  const [l, r] = LABEL[p];
  $("corelabel").firstChild.textContent = l;
  $("vin-count").textContent = r;
  // layers that aren't showing must not be focusable
  document.querySelectorAll(".layer").forEach((el) => {
    el.toggleAttribute("inert", !el.classList.contains(`layer--${LAYER[p]}`));
  });
  if (p === "await" || p === "done") scale(1);
  announce(ANNOUNCE[p]);
  if (typeof catPhase === "function") catPhase(p);
}
const LAYER = { request: "vin", await: "code", install: "run", done: "seal", halt: "halt" };
const ANNOUNCE = {
  request: "Enter the vehicle identification number.",
  await: "Request sent. Waiting for approval.",
  install: "Approved. Ready to install.",
  done: "Install complete.",
  halt: "Install stopped.",
};

const scale = (f) => { $("scale-fill").style.width = (f * 100).toFixed(1) + "%"; };
function status(id, msg, kind) {
  const el = $(id);
  el.textContent = msg;
  el.className = "statusline" + (kind === "ok" ? " is-ok" : kind === "err" ? " is-err" : "");
}
let lastSaid = "";
function announce(msg) {
  if (!msg || msg === lastSaid) return;
  lastSaid = msg; $("live").textContent = msg;
}
// telemetry: verbs + human labels + hashes. never commands or filenames.
function tele(msg, cls) {
  const el = $("log");
  const s = document.createElement("span");
  if (cls) s.className = cls;
  s.textContent = msg + "\n";
  el.appendChild(s);
  el.scrollTop = el.scrollHeight;
  $("tele-n").textContent = String(++state.ops);
}

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    let d = r.statusText;
    try { d = (await r.json()).detail || d; } catch { /* ignore */ }
    throw new Error(d);
  }
  return r.json();
}

// --- VIN readout -----------------------------------------------------------
const SLOTS = 17, slotsEl = $("slots"), vin = $("vin");
for (let i = 0; i < SLOTS; i++) {
  const s = document.createElement("span"); s.className = "slot"; slotsEl.appendChild(s);
}
function paintVin() {
  const v = vin.value.toUpperCase();
  // honest caret: follow the real selection, clamped into range
  const focused = document.activeElement === vin;
  const caret = Math.min(vin.selectionStart ?? v.length, SLOTS - 1);
  [...slotsEl.children].forEach((el, i) => {
    el.textContent = v[i] || "";
    el.classList.toggle("on", i < v.length);
    el.classList.toggle("cursor", focused && i === caret);
  });
  $("vin-count").textContent = `${v.length} / 17`;
  scale(v.length / SLOTS);
}
["input", "keyup", "click", "focus", "blur", "select"].forEach((e) =>
  vin.addEventListener(e, () => {
    if (e === "input") vin.value = vin.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
    paintVin();
  }));
document.addEventListener("selectionchange", () => { if (document.activeElement === vin) paintVin(); });
$("layer-vin").addEventListener("click", () => vin.focus());

// --- payment (shown only on the await step, where the user is told to pay) --
// Two wallets (one card each) + a receipt for the amount. PAYMENT.cards maps in
// order: [0] -> Uzcard, [1] -> Humo. The receipt prints CFG.PRICE_TEXT.
const pay = CFG.PAYMENT, con = CFG.CONTACTS;
const cards = (pay && pay.cards) || [];
fillCard("uz", cards[0]);
fillCard("humo", cards[1]);
{ const a = $("receipt-amount"); if (a) a.textContent = CFG.PRICE_TEXT || ""; }
{ const t = $("pay-tg-2"); if (t) t.textContent = con.telegram; }

function fillCard(slot, c) {
  if (!c) return;
  const full = c.number || "";
  const last4 = full.replace(/\s+/g, "").slice(-4);
  const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  set(slot + "-mask", "•••• •••• •••• " + last4);
  set(slot + "-number", full);
}

// Reveal + copy on tap, so the number works on touch (no hover there). Hover
// reveal stays pure CSS; the tap just toggles the same .revealed state.
document.querySelectorAll(".card[data-card]").forEach((card) => {
  card.addEventListener("click", async () => {
    card.classList.add("revealed");
    const num = (card.querySelector(".card-number")?.textContent || "").replace(/\s+/g, "");
    try { await navigator.clipboard.writeText(num); } catch { /* clipboard blocked */ }
    announce("Card number copied.");
  });
});

// The cheque is a link out to the seller's Telegram, where the buyer sends the
// payment receipt. Built from CONTACTS.telegram so there is no hardcoded handle;
// if it is missing the link is disabled rather than pointing somewhere wrong.
{
  const dm = $("receipt-dm");
  const handle = String(con.telegram || "").trim().replace(/^@/, "");
  if (dm && handle) {
    dm.href = "https://t.me/" + encodeURIComponent(handle);
  } else if (dm) {
    dm.removeAttribute("href");
    dm.setAttribute("aria-disabled", "true");
  }
}

// --- vehicle selector ------------------------------------------------------
// Two supported cars. The differences are real and worth showing up front:
// the MAGE is provisioned over a USB cable, the B70 over Wireless ADB. Telling
// the user that here is why the selector exists instead of two text fields.
const CARS = {
  dongfeng_mage: { brand: "Aeolus", model: "MAGE", make: "Dongfeng",
                   os: "11", link: "USB cable", via: "usb",
                   apps: ["back button", "media", "navigation", "antiradar"] },
  faw_b70:       { brand: "FAW", model: "B70", make: "FAW",
                   os: "9", link: "Wireless ADB", via: "relay",
                   apps: ["back button", "media", "Wi-Fi tile", "navigation", "home screen"] },
};
const CAR_IDS = Object.keys(CARS);
const track = $("picker-track");
const opts = [...track.querySelectorAll(".picker-opt")];

function selectCar(id, { focus = false } = {}) {
  const i = CAR_IDS.indexOf(id);
  if (i < 0) return;
  state.car = id;
  track.dataset.sel = String(i);
  opts.forEach((o, n) => {
    const on = n === i;
    o.setAttribute("aria-checked", String(on));
    o.tabIndex = on ? 0 : -1;
    if (on && focus) o.focus();
  });
  const c = CARS[id];
  $("sp-os").textContent = "Android " + c.os;
  $("sp-link").textContent = c.link;
  $("sp-apps").textContent = `${c.apps.length} apps`;
  $("spec").title = c.apps.join(", ");
  // roll the spec over so the change is felt, not just swapped
  const spec = $("spec");
  spec.classList.remove("roll"); void spec.offsetWidth; spec.classList.add("roll");
  announce(`${c.brand} ${c.model} selected. Android ${c.os}, ${c.link}.`);
}
opts.forEach((o) => o.addEventListener("click", () => selectCar(o.dataset.car)));
track.addEventListener("keydown", (e) => {
  const i = CAR_IDS.indexOf(state.car);
  if (e.key === "ArrowRight" || e.key === "ArrowDown") {
    e.preventDefault(); selectCar(CAR_IDS[(i + 1) % CAR_IDS.length], { focus: true });
  } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
    e.preventDefault(); selectCar(CAR_IDS[(i - 1 + CAR_IDS.length) % CAR_IDS.length], { focus: true });
  }
});
selectCar("dongfeng_mage");

$("btn-arm").onclick = requestActivation;
$("btn-copy").onclick = async () => {
  const c = $("code").textContent;
  if (/^[·]+$/.test(c)) return;
  try { await navigator.clipboard.writeText(c); status("wait-status", "Code copied.", "ok"); }
  catch { /* blocked */ }
};
$("btn-connect").onclick = connect;
$("btn-install").onclick = runInstall;
$("btn-again").onclick = () => location.reload();

document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const p = stage.dataset.phase;
  if (p === "request") { e.preventDefault(); requestActivation(); }
  else if ((p === "install" || p === "halt") && !$("btn-install").disabled) {
    e.preventDefault(); runInstall();
  }
});

// --- cat -------------------------------------------------------------------
// Decorative. Mounts only if the lottie runtime AND ./cat.json both resolve;
// any failure is silent so a missing asset can never affect the installer.
let catAnim = null;
const CALM = matchMedia("(prefers-reduced-motion: reduce)").matches;

let catMounting = false;
async function mountCat() {
  const el = $("cat");
  // Guard SYNCHRONOUSLY. Checking catAnim alone races: it is only assigned
  // after several awaits, so two callers both passed and mounted two cats.
  if (!el || catAnim || catMounting) return;
  catMounting = true;
  let data;
  try {
    const r = await fetch("/cat.json");
    if (!r.ok) { console.info("[cat] ./cat.json not found — skipping (app unaffected)"); return; }
    data = await r.json();
  } catch { console.info("[cat] ./cat.json unreadable — skipping"); return; }
  recolourCat(data);                         // draw it in the interface's ink
  // the runtime is a deferred CDN script; wait for it rather than giving up
  for (let i = 0; i < 40 && !window.lottie; i++) await sleep(50);
  if (!window.lottie) { console.info("[cat] lottie runtime unavailable — skipping"); return; }
  try {
    el.replaceChildren();                    // belt and braces against a re-entry
    catAnim = window.lottie.loadAnimation({
      container: el, renderer: "svg", loop: true, autoplay: !CALM, animationData: data,
    });
    if (CALM) catAnim.goToAndStop(0, true);  // a still cat, not a frozen one
    cropCat(el, catAnim);                    // trim margins, keep the full motion
    el.dataset.on = "1";
    stage.classList.add("has-cat");           // reserve headroom for the perch
    catPhase(stage.dataset.phase);
  } catch (e) { console.info("[cat] mount failed:", e.message); }
}
// Repaint the artwork in the interface's own palette. The file ships as a
// pure-black body with amber eyes; black is invisible on this ground and a
// CSS filter can't lift it (brightening #000 is still #000). So the fills are
// rewritten before mount: body -> UI ink, eyes -> the amber accent.
function recolourCat(data) {
  const css = getComputedStyle(document.documentElement);
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  const toRgb = (v) => {                     // resolve any colour token to 0..1 rgb
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "#808080";               // fallback if the token is missing
    ctx.fillStyle = css.getPropertyValue(v).trim() || "#808080";
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0] / 255, d[1] / 255, d[2] / 255];
  };
  const body = toRgb("--edge-hi"), eyes = toRgb("--lume");
  const walk = (o) => {
    if (Array.isArray(o)) return o.forEach(walk);
    if (!o || typeof o !== "object") return;
    if (o.ty === "fl" && o.c && Array.isArray(o.c.k) && o.c.k.length >= 3) {
      const [r, g, b] = o.c.k;
      const dark = r + g + b < 0.3;          // the silhouette
      o.c.k = [...(dark ? body : eyes), o.c.k[3] ?? 1];
    }
    Object.values(o).forEach(walk);
  };
  walk(data.layers || []);
}

// The artwork sits inside a 1495x805 canvas with large empty margins, so the
// cat rendered small and floated off its baseline. Retarget the viewBox to the
// drawn content and anchor it to the bottom, so its feet land on the frame line.
function cropCat(el, anim) {
  const svg = el.querySelector("svg");
  if (!svg) return;
  // lottie clips to the composition box; drop that so nothing is sliced off.
  svg.style.overflow = "visible";
  svg.querySelectorAll("[clip-path]").forEach((n) => n.removeAttribute("clip-path"));

  // Measure the UNION across the timeline, not just frame 0: the tail and
  // head move well outside the first frame's box, and cropping to that box
  // is what was cutting the animation off on the right.
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, got = false;
  const take = () => {
    try {
      const b = svg.getBBox();
      if (b && b.width && b.height) {
        x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
        x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height);
        got = true;
      }
    } catch { /* not measurable yet */ }
  };
  const total = anim?.totalFrames || 0;
  if (total) {
    const steps = 30;
    for (let i = 0; i <= steps; i++) { anim.goToAndStop(Math.round(total * i / steps), true); take(); }
    if (CALM) anim.goToAndStop(0, true); else anim.play();
  } else take();
  if (!got) return;

  const pad = 4;
  const w = x1 - x0 + pad * 2, h = y1 - y0 + pad * 2;
  svg.setAttribute("viewBox", `${x0 - pad} ${y0 - pad} ${w} ${h}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMax meet");
  svg.style.width = "100%";
  svg.style.height = "100%";
  el.style.aspectRatio = `${w} / ${h}`;      // container hugs the full motion
  fillCatWithSky(svg, x0 - pad, y0 - pad, w, h);
}

// Fill the silhouette with a night sky instead of a flat colour, so the cat
// reads as a window onto stars. Three constraints shape this implementation:
//   1. lottie REWRITES each path's fill on animation frames, so overriding
//      fills in the DOM does not survive; we must not fight it for them.
//   2. the art sits inside groups with large transforms, so a userSpaceOnUse
//      pattern applied to those paths resolves far off the visible shape.
//   3. <pattern> content is rasterised and cached, so animation inside a
//      pattern never repaints. The sky therefore lives in the real render
//      tree as a masked group, where its stars genuinely move.
// The sky is masked by the live artwork (a <use> reference, which follows the
// animation), with the eyes re-stamped on top so they keep the amber accent.
//
// It is deliberately lighter than a true night: on this near-black ground an
// authentic near-black sky would make the cat invisible again.
function fillCatWithSky(svg, vx, vy, vw, vh) {
  const NS = "http://www.w3.org/2000/svg";
  if (svg.querySelector("#catsky")) return;
  const art = [...svg.children].find((n) => n.tagName === "g");
  if (!art) return;
  art.id = "catart";

  const defs = document.createElementNS(NS, "defs");

  const grad = document.createElementNS(NS, "radialGradient");
  grad.id = "catsky-grad";
  grad.setAttribute("cx", "50%"); grad.setAttribute("cy", "104%");
  grad.setAttribute("r", "118%");
  [["0%", "oklch(0.56 0.115 305)"],
   ["42%", "oklch(0.37 0.080 298)"],
   ["100%", "oklch(0.24 0.040 285)"]].forEach(([o, c]) => {
    const st = document.createElementNS(NS, "stop");
    st.setAttribute("offset", o); st.setAttribute("stop-color", c);
    grad.appendChild(st);
  });
  defs.appendChild(grad);

  // alpha masking: any opaque pixel of the cat lets the sky through, whatever
  // colour lottie happens to have painted it.
  const mask = document.createElementNS(NS, "mask");
  mask.id = "catmask";
  mask.style.maskType = "alpha";
  mask.setAttribute("maskUnits", "userSpaceOnUse");
  mask.setAttribute("x", vx); mask.setAttribute("y", vy);
  mask.setAttribute("width", vw); mask.setAttribute("height", vh);
  const useArt = document.createElementNS(NS, "use");
  useArt.setAttribute("href", "#catart");
  mask.appendChild(useArt);
  defs.appendChild(mask);

  const style = document.createElementNS(NS, "style");
  style.textContent = `
    @keyframes catTwinkle { 0%,100% { opacity: .12 } 50% { opacity: 1 } }
    @keyframes catDrift   { from { transform: translateY(0) }
                            to   { transform: translateY(${-vh}px) } }
    #catstars { animation: catDrift ${(vh / 70).toFixed(1)}s linear infinite; }
    .catstar  { animation: catTwinkle var(--d) ease-in-out var(--t) infinite; }
    @media (prefers-reduced-motion: reduce) {
      #catstars, .catstar { animation: none; }
    }`;
  defs.appendChild(style);
  svg.insertBefore(defs, svg.firstChild);

  // the sky itself, in the live tree so its animation actually runs
  const sky = document.createElementNS(NS, "g");
  sky.id = "catsky";
  sky.setAttribute("mask", "url(#catmask)");

  const bg = document.createElementNS(NS, "rect");
  bg.setAttribute("x", vx); bg.setAttribute("y", vy);
  bg.setAttribute("width", vw); bg.setAttribute("height", vh);
  bg.setAttribute("fill", "url(#catsky-grad)");
  sky.appendChild(bg);

  // Two identical star tiles stacked vertically, scrolled by exactly one tile
  // height: the loop is seamless because tile B arrives where tile A began.
  const scroll = document.createElementNS(NS, "g");
  scroll.id = "catstars";
  let seed = 20260813;                       // deterministic: same sky each load
  const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  const tile = () => {
    const g = document.createElementNS(NS, "g");
    for (let i = 0; i < 90; i++) {
      const st = document.createElementNS(NS, "circle");
      st.setAttribute("class", "catstar");
      st.setAttribute("cx", (vx + rnd() * vw).toFixed(1));
      st.setAttribute("cy", (vy + rnd() * vh).toFixed(1));
      st.setAttribute("r", (1.4 + rnd() * 3.2).toFixed(2));
      st.setAttribute("fill", "oklch(0.99 0.02 300)");
      st.style.setProperty("--d", (0.9 + rnd() * 1.8).toFixed(2) + "s");
      st.style.setProperty("--t", (-rnd() * 3).toFixed(2) + "s");
      g.appendChild(st);
    }
    return g;
  };
  const a1 = tile();
  const a2 = tile();
  a2.setAttribute("transform", `translate(0 ${vh})`);   // the seam partner
  scroll.append(a1, a2);
  sky.appendChild(scroll);
  svg.appendChild(sky);

  // re-stamp the eyes over the sky; <use> tracks the live animated groups
  const amber = rgbOf("--lume");
  [...art.children].forEach((g, i) => {
    const p = g.querySelector("path");
    if (!p || (p.getAttribute("fill") || "").replace(/\s/g, "") !== amber) return;
    g.id = `cateye${i}`;
    const u = document.createElementNS(NS, "use");
    u.setAttribute("href", `#cateye${i}`);
    svg.appendChild(u);
  });
}

// resolve a CSS colour token to an "rgb(r,g,b)" string
function rgbOf(token) {
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  cx.fillStyle = getComputedStyle(document.documentElement)
    .getPropertyValue(token).trim() || "#808080";
  cx.fillRect(0, 0, 1, 1);
  const d = cx.getImageData(0, 0, 1, 1).data;
  return `rgb(${d[0]},${d[1]},${d[2]})`;
}

// react to what the machine is doing, without competing with it
function catPhase(p) {
  if (!catAnim || CALM) return;
  catAnim.setSpeed(p === "install" ? 0.55 : p === "done" ? 1.3 : 1);
  if (p === "halt") catAnim.pause(); else catAnim.play();
}
mountCat();                                  // guarded + waits for the runtime
addEventListener("load", mountCat, { once: true });

setPhase("request");
paintVin();
vin.focus();

// --- 1 request -------------------------------------------------------------
async function requestActivation() {
  const v = vin.value.trim();
  const car = CARS[state.car];
  const make = car.make, model = car.model;
  if (v.length !== SLOTS) return status("request-status", `A VIN is 17 characters. You have ${v.length}.`, "err");
  if (/[IOQ]/.test(v)) return status("request-status", "A VIN never contains I, O or Q.", "err");

  status("request-status", "Sending…");
  $("btn-arm").disabled = true;
  try {
    const r = await api("/api/request", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ mid: machineId(), vin: v, make, model }),
    });
    state.rid = r.rid; state.vin = v; state.make = make; state.model = model;
    $("code").textContent = r.code;
    setPhase("await");
    pollApproval();
  } catch (e) {
    status("request-status", "Could not send: " + e.message, "err");
    $("btn-arm").disabled = false;
  }
}

// --- 2 await (reports staleness instead of failing silently) ---------------
async function pollApproval() {
  const t0 = Date.now();
  let fails = 0;
  for (;;) {
    try {
      const r = await api(`/api/status?rid=${encodeURIComponent(state.rid)}`);
      fails = 0;
      if (r.status === "approved" && r.token) { state.token = r.token; return onApproved(); }
      if (r.status === "rejected") return status("wait-status", "This request was declined.", "err");
      const mins = Math.floor((Date.now() - t0) / 60000);
      status("wait-status", mins < 1 ? "Send this code with your payment."
        : `Send this code with your payment. Waiting ${mins} min.`);
    } catch {
      if (++fails >= 3) status("wait-status", "Can't reach the server. Retrying…", "err");
    }
    await sleep(3000);
  }
}
function onApproved() {
  status("wait-status", "Approved.", "ok");
  setPhase("install");
  scale(0); $("pct").textContent = "0";
  // tell the user HOW to connect this specific car, before they hunt for it
  const c = CARS[state.car];
  $("phase-idle").textContent = c.link === "USB cable"
    ? "Connect the head unit with a USB cable, then press Connect."
    : "Enable Wireless ADB on the head unit and start the local agent, then press Connect.";
  showHelper(c);
  // Warm the ADB chunk now. requestDevice() needs a live user gesture, and
  // awaiting a cold network fetch inside the click handler spends that window
  // for nothing. Failure is ignored: connect() reports it properly.
  transport().catch(() => { /* connect() surfaces this */ });
}

// A wireless car needs the local bridge, and the buyer must learn that BEFORE
// pressing Connect — finding out from a failure after paying is the worst
// possible moment. USB cars never see this. If the helper file is not actually
// published yet, fall back to asking on Telegram rather than offering a link
// that 404s, which would read as a broken product at the point of sale.
async function showHelper(car) {
  const box = $("helper");
  if (!box) return;
  if (car.via !== "relay") { box.hidden = true; return; }
  box.hidden = false;

  const url = CFG.RELAY_DOWNLOAD || "/AxolotlRelay.exe";
  const dl = $("helper-dl");
  // A 200 is NOT enough. Cloudflare Pages answers any unmatched path with
  // index.html and status 200, so a plain .ok check would happily offer a
  // download that hands the buyer an HTML page renamed .exe — worse than a
  // 404, because they would try to run it. Require a non-HTML content type.
  let ok = false;
  try {
    const r = await fetch(url, { method: "HEAD" });
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    ok = r.ok && !ct.startsWith("text/html");
  } catch { ok = false; }

  if (ok) {
    dl.href = url;
    dl.removeAttribute("aria-disabled");
  } else {
    const tg = String(CFG.CONTACTS?.telegram || "").trim().replace(/^@/, "");
    dl.textContent = tg ? "Ask for the helper on Telegram" : "Helper unavailable";
    if (tg) dl.href = "https://t.me/" + encodeURIComponent(tg);
    else { dl.removeAttribute("href"); dl.setAttribute("aria-disabled", "true"); }
    dl.removeAttribute("download");
    $("helper-note").textContent =
      "The helper download isn't published yet. Message us and we'll send it.";
  }
}

// --- 3 connect -------------------------------------------------------------
async function connect() {
  $("device").dataset.state = "busy";
  $("device-name").textContent = "Linking…";
  $("btn-connect").disabled = true;
  const prev = { profile: state.profile?.id, at: state.resumeFrom || 0,
                 len: state.plan?.ops.length || 0 };
  // Deliberately NOT awaited. Closing sends CLSE packets and waits for replies,
  // so on the dead link we are reconnecting from it can hang forever — freezing
  // the one action that recovers from a freeze.
  state.adb?.close().catch(() => { /* stale link, nothing to close */ });
  state.adb = null;
  try {
    let t;
    try { t = await transport(); }
    catch {
      throw new Error("ADB support isn't built. Run `npm install && npm run build` in webapp/.");
    }
    // Which transport this car uses is known up front; do not guess.
    const via = CARS[state.car]?.via || "usb";
    let adb, link;
    if (via === "usb") {
      if (!navigator.usb) {
        throw new Error("This browser has no WebUSB. Use Chrome or Edge on a computer.");
      }
      tele("linking over usb", "dim");
      adb = await t.connectUsb();
      link = "USB";
    } else {
      tele("linking over the local relay", "dim");
      adb = await t.connectRelay(CFG.RELAY, state.token);
      link = "Wi-Fi";
    }
    state.adb = adb;

    const model = (await adb.getprop("ro.product.model")) || "Head unit";
    const dev = (await adb.getprop("ro.product.device")) || "";
    const android = (await adb.getprop("ro.build.version.release")) || "?";
    state.profile = pickProfile(model, dev);
    state.device = `${friendly(state.profile.id, model)} · Android ${android} · ${link}`;

    $("device").dataset.state = "on";
    $("device-name").textContent = state.device;
    $("btn-connect").textContent = "Relink";
    $("btn-connect").disabled = false;
    tele(`linked · ${state.device}`, "ok");

    // Refetched every link: the signed download URLs inside a plan expire.
    state.plan = await api("/api/plan", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token: state.token, profile: state.profile.id }),
    });
    // Relinking after a dropped Wi-Fi link must not replay everything. The ops
    // are idempotent, but re-pushing ~100 MB over Wi-Fi is not free, and the
    // buyer already watched it once. Same car, same plan shape: keep the cursor.
    state.resumeFrom = prev.profile === state.profile.id
      && prev.len === state.plan.ops.length ? prev.at : 0;
    buildPhases(state.plan);
    if (state.resumeFrom > 0) {
      state.phases.forEach((p) => {
        if (p.ops[p.ops.length - 1] < state.resumeFrom) mark(p.key, "done", "DONE");
      });
      progress(state.resumeFrom / state.plan.ops.length);
      tele(`resuming at operation ${state.resumeFrom + 1}`, "dim");
      $("btn-install").lastChild.textContent = " Resume from this step";
    }
    tele(`plan loaded · ${state.plan.ops.length} operations`, "dim");
    $("btn-install").disabled = false;
    // detection wins over the selection; say so rather than silently diverging
    if (state.car && state.profile.id !== state.car) {
      const picked = CARS[state.car], found = CARS[state.profile.id];
      const name = found ? `${found.brand} ${found.model}` : state.profile.name;
      const article = /^[AEIOU]/i.test(name) ? "an" : "a";
      status("run-status", `You selected ${picked.brand} ${picked.model}, but this is ${article} `
        + `${name}. Installing for what's connected.`, "err");
      tele(`selection ${state.car} != detected ${state.profile.id}`, "er");
    } else {
      status("run-status", "Ready.", "ok");
    }
    announce("Head unit linked. Ready to install.");
  } catch (e) {
    $("device").dataset.state = "off";
    $("device-name").textContent = "Not linked";
    status("run-status", e.message, "err");
    tele("link failed · " + e.message, "er");
    $("btn-connect").disabled = false;
  }
}

function pickProfile(model, dev) {
  const m = (model + " " + dev).toLowerCase();
  if (m.includes("dongfeng") || m.includes("aeolus") || m.includes("spm8675"))
    return { id: "dongfeng_mage", name: "Dongfeng Aeolus MAGE" };
  return { id: "faw_b70", name: "FAW B70" };
}
const friendly = (id, model) =>
  id === "dongfeng_mage" ? "Dongfeng MAGE" : id === "faw_b70" ? "FAW B70" : model;

// --- phases ----------------------------------------------------------------
const PHASE_META = { prepare: "Preparing the head unit", apps: "Installing apps", menu: "Setting up the menu" };
const APP_LABEL = {
  "01_backbutton.apk": "back button", "02_freetube.apk": "media",
  "03_wifishortcut.apk": "Wi-Fi shortcut", "04_yandexnavi.apk": "navigation",
  "05_launcher.apk": "home screen", "df01_freetube.apk": "media",
  "df02_yandexnavi.apk": "navigation",
};
const phaseOf = (op) =>
  op.op === "install" ? "apps"
  : op.op === "sqlite" || op.op === "settings" ? "menu"
  : op.op === "shell" ? (/pm grant/.test(op.cmd) ? "apps" : /force-stop/.test(op.cmd) ? "menu" : "prepare")
  : "prepare";

function buildPhases(plan) {
  const order = [];
  plan.ops.forEach((op, i) => {
    const k = phaseOf(op);
    let e = order.find((x) => x.key === k);
    if (!e) { e = { key: k, ops: [] }; order.push(e); }
    e.ops.push(i);
  });
  state.phases = order;
  const ol = $("phases"); ol.innerHTML = "";
  order.forEach((e, n) => {
    const li = document.createElement("li");
    li.className = "phase"; li.id = `ph-${e.key}`; li.dataset.state = "queued";
    li.innerHTML = `<span class="phase-n">${String(n + 1).padStart(2, "0")}</span>
      <span class="phase-t">${PHASE_META[e.key]}</span><span class="phase-s">WAITING</span>`;
    ol.appendChild(li);
  });
}
const mark = (k, s, l) => { const li = $(`ph-${k}`); if (li) { li.dataset.state = s; li.querySelector(".phase-s").textContent = l; } };

// throttle the live region: milestones only, never per chunk
let saidPct = -1;
function progress(f) {
  scale(f);
  const p = Math.round(f * 100);
  $("pct").textContent = String(p);
  const step = Math.floor(p / 25) * 25;
  if (step !== saidPct) { saidPct = step; announce(`${step} percent.`); }
}

// --- run (resumes from the failed op; never replays completed writes) -------
async function runInstall() {
  $("btn-install").disabled = true;
  $("btn-connect").disabled = true;
  setPhase("install");
  status("run-status", "Keep the head unit connected.");
  const ops = state.plan.ops;

  for (let i = state.resumeFrom; i < ops.length; i++) {
    const key = phaseOf(ops[i]);
    if (i === state.resumeFrom || phaseOf(ops[i - 1]) !== key) mark(key, "active", "WORKING");
    progress(i / ops.length);
    try {
      await execOp(ops[i], i);
    } catch (e) {
      state.resumeFrom = i;                 // resume HERE, not from zero
      mark(key, "failed", "FAILED");
      $("halt-n").textContent = String(i + 1).padStart(2, "0");
      $("halt-t").textContent = String(ops.length).padStart(2, "0");
      setPhase("halt");
      status("run-status", e.message, "err");
      tele("stopped · " + e.message, "er");
      $("tele").open = true;                // surface detail exactly when needed
      // A dead link cannot be resumed over — pressing Resume would only fail
      // again on the same op. Send them to Connect, which now keeps the cursor.
      const gone = !state.adb || state.adb.dead;
      if (gone) {
        $("device").dataset.state = "off";
        $("device-name").textContent = "Not linked";
        $("btn-connect").textContent = "Connect";
        tele("link lost · reconnect to resume from operation " + (i + 1), "er");
      }
      $("btn-install").disabled = gone;
      $("btn-install").lastChild.textContent = " Resume from this step";
      $("btn-connect").disabled = false;
      return;
    }
    const last = state.phases.find((p) => p.key === key).ops.slice(-1)[0];
    if (i === last) mark(key, "done", "DONE");
  }

  progress(1);
  buildRecap();
  setPhase("done");
  try {
    await api("/api/consume", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token: state.token }),
    });
  } catch { /* best effort */ }
  try { await state.adb?.close(); } catch { /* ignore */ }
}

function buildRecap() {
  const rows = [["VIN", state.vin || "—"], ["VEHICLE", `${state.make || ""} ${state.model || ""}`.trim() || "—"],
                ["HEAD UNIT", state.device || "—"], ["OPERATIONS", String(state.plan.ops.length)]];
  $("recap").innerHTML = rows.map(([k, v]) =>
    `<div><dt>${k}</dt><dd>${escapeHtml(v)}</dd></div>`).join("");
}

async function execOp(op, i) {
  const adb = state.adb;
  switch (op.op) {
    case "root": {
      const uid = (await adb.shell("id -u")).stdout.trim();
      if (uid !== "0") throw new Error("The head unit would not allow setup.");
      tele("prepare · unlock · ok", "ok"); return;
    }
    case "setprop": {
      if (!(await adb.setprop(op.key, op.value)))
        throw new Error("The head unit rejected a required setting.");
      tele("prepare · configure · ok", "ok"); return;
    }
    case "install": {
      const label = APP_LABEL[op.file] || "app";
      const bytes = await download(op, i, label);
      tele(`install · ${label} · sha ${op.sha256.slice(0, 8)}`, "dim");
      if (!(await sha256ok(bytes, op.sha256))) {
        tele(`install · ${label} · checksum mismatch`, "er");
        throw new Error(`The ${label} download was corrupted. Nothing was installed.`);
      }
      tele(`install · ${label} · verified ✓`, "ok");
      const res = await adb.install(bytes, op.flags);
      if (!res.ok) throw new Error(`Could not install the ${label}.`);
      tele(`install · ${label} · installed`, "ok"); return;
    }
    case "sqlite":
    case "settings":
    case "shell": {
      const cmd = op.op === "sqlite" ? `sqlite3 ${op.db} ${shq(op.stmt)}`
        : op.op === "settings" ? `settings put ${op.ns} ${op.key} ${op.value}` : op.cmd;
      await adb.shell(cmd);
      tele(op.op === "shell" ? "configure · permission · ok" : "menu · register · ok", "ok");
      return;
    }
    default: throw new Error("Unknown operation.");
  }
}

async function download(op, i, label) {
  const r = await fetch(API + op.url);
  if (!r.ok) throw new Error(`Download failed (${r.status}).`);
  const total = Number(r.headers.get("Content-Length")) || 0;
  const reader = r.body.getReader();
  const chunks = []; let got = 0;
  const base = i / state.plan.ops.length, span = 1 / state.plan.ops.length;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    if (total) progress(base + span * (got / total));
  }
  const out = new Uint8Array(got); let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return out.buffer;
}

// --- utils -----------------------------------------------------------------
async function sha256ok(buf, expected) {
  const d = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("") === expected;
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function shq(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function machineId() {
  let id = localStorage.getItem("carapk_mid");
  if (!id) {
    id = [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("carapk_mid", id);
  }
  return id;
}
