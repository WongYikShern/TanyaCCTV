// Records each scene of the demo film from the running app (http://127.0.0.1:5001) at 1920x1080 using
// Chrome's screencast. Each segment is saved as timestamped JPEG frames plus a list of sound cues.
// Usage: node record.mjs [segment ...]   (no arguments = all segments)
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = "http://127.0.0.1:5001/";
const CARDS = "file://" + path.join(HERE, "cards.html");
const CCTV = "file://" + path.join(HERE, "cctv.html");
const W = 1920, H = 1080;
const sleep = ms => new Promise(r => setTimeout(r, ms));

const profile = path.join(HERE, ".chrome-profile");
rmSync(profile, {recursive: true, force: true});
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", ["--headless=new", "--disable-gpu-vsync",
  "--no-proxy-server", "--remote-debugging-port=9350", `--user-data-dir=${profile}`, "--autoplay-policy=no-user-gesture-required",
  "--allow-file-access-from-files", "--hide-scrollbars", `--window-size=${W},${H}`, "about:blank"], {stdio: "ignore"});
let targets;
for (let i = 0; i < 60; i++) { try { targets = await (await fetch("http://127.0.0.1:9350/json")).json(); break; } catch { await sleep(250); } }
const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map(); let rec = null; const problems = [];
ws.addEventListener("message", e => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Page.screencastFrame") {
    send("Page.screencastFrameAck", {sessionId: m.params.sessionId});
    if (rec) { const n = rec.frames.length; const file = `f${String(n).padStart(5, "0")}.jpg`;
      writeFileSync(path.join(rec.dir, file), Buffer.from(m.params.data, "base64")); rec.frames.push([file, m.params.metadata.timestamp]); }
  }
  if (m.method === "Runtime.exceptionThrown") problems.push((m.params.exceptionDetails.exception?.description || "").split("\n")[0]);
});
const send = (method, params = {}) => new Promise(r => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({id: n, method, params})); });
const ev = async expr => { const r = await send("Runtime.evaluate", {expression: expr, awaitPromise: true, returnByValue: true});
  if (r.result?.exceptionDetails) problems.push("EVAL " + (r.result.exceptionDetails.exception?.description || "").split("\n")[0]); return r.result?.result?.value; };
await send("Page.enable"); await send("Runtime.enable");
// Recording browser only: let the scene scripts add their own styles to the app's pages.
await send("Page.setBypassCSP", {enabled: true});
await send("Emulation.setDeviceMetricsOverride", {width: W, height: H, deviceScaleFactor: 1, mobile: false});

// App pages render at 1440x810 CSS px, scaled 1.333 to 1920x1080, so the interface reads larger on video.
async function go(url, wait = 2500) {
  const app = url.startsWith(APP);
  await send("Emulation.setDeviceMetricsOverride", app ? {width: 1440, height: 810, deviceScaleFactor: W / 1440, mobile: false} : {width: W, height: H, deviceScaleFactor: 1, mobile: false});
  await send("Page.navigate", {url}); await sleep(wait);
}
async function start(name) {
  const dir = path.join(HERE, "segments", name); rmSync(dir, {recursive: true, force: true}); mkdirSync(dir, {recursive: true});
  rec = {name, dir, frames: [], cues: [], t0: Date.now() / 1000};
  await send("Page.startScreencast", {format: "jpeg", quality: 92, maxWidth: W, maxHeight: H, everyNthFrame: 1});
}
const cue = sound => rec && rec.cues.push([sound, Date.now() / 1000]);
async function stop() {
  await send("Page.stopScreencast");
  const r = rec; rec = null;
  writeFileSync(path.join(r.dir, "meta.json"), JSON.stringify({frames: r.frames, cues: r.cues, end: Date.now() / 1000}));
  console.log(`${r.name}: ${r.frames.length} frames, ${(Date.now() / 1000 - r.t0).toFixed(1)} s, cues ${r.cues.map(c => c[0]).join(",") || "-"}`);
}
// Alerts appearing on the live monitor become sound cues.
async function watchAlerts() {
  await ev(`(() => { window._cues = []; new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
    if (n.classList?.contains("mon-alert")) window._cues.push([[...n.classList].find(c => ["notice","warning","alarm"].includes(c)), Date.now() / 1000]); })))
    .observe(document.getElementById("mon-alerts"), {childList: true}); })()`);
}
async function collectAlerts() { for (const c of (await ev("window._cues || []")) || []) rec.cues.push(c); await ev("window._cues = []"); }
async function card(idName, seconds, extra = "") {
  await go(`${CARDS}#${idName}`, 800); if (extra) await ev(extra);
  await start(idName === "history" ? "history" : "card-" + idName); await ev(`window.show(${JSON.stringify(idName)})`); cue("whoosh");
  await sleep(seconds * 1000); await stop();
}
const MONITOR_CSS = `
  .mon-layout { grid-template-columns: minmax(0,1fr) 400px !important; }
  .mon-grid { grid-template-columns: 1fr !important; }
  .mon-tile { display: none !important; } .mon-tile.focus { display: block !important; }
  .mon-tile.focus .mon-stage { aspect-ratio: 16/9 !important; }
  .page-head .muted { display: none; } footer { display: none; } #notice { display: none !important; }`;
async function monitorFocus(camera, from) {
  await go(APP + "#monitor", 5500);
  await ev(`(() => { const s = document.createElement("style"); s.textContent = ${JSON.stringify(MONITOR_CSS)}; document.head.append(s);
    document.querySelectorAll(".mon-tile").forEach(t => { const v = t.querySelector("video"); const me = t.textContent.includes(${JSON.stringify(camera)});
      t.classList.toggle("focus", me); if (v) { v.pause(); if (me) v.currentTime = ${from}; } });
    document.getElementById("mon-clear").click(); window.scrollTo(0, 0); })()`);
  await sleep(400); await ev(`window.dispatchEvent(new Event("resize"))`);   // re-fit the zone overlay to the resized tile
  await sleep(1100); await watchAlerts();
}
const playFocus = () => ev(`document.querySelector(".mon-tile.focus video").play()`);
const seekFocus = t => ev(`(() => { const v = document.querySelector(".mon-tile.focus video"); v.currentTime = ${t}; v.play(); })()`);
const CLEAN = `(() => { const s = document.createElement("style"); s.textContent = "footer{display:none} #notice{display:none!important}"; document.head.append(s); })()`;

const SEGMENTS = {
  async intro() { await card("intro", 3.2); },
  async elmina() { await card("elmina", 5.3); },
  async fall() {
    await go(`${CCTV}?src=${encodeURIComponent(APP + "media/videos/9")}&t=19&clock=19:42:05`, 2500);
    await start("fall"); cue("heartbeat"); await ev("go()");
    await sleep(8800); await ev("nobody(true)"); cue("impact"); await sleep(5200); await stop();
  },
  async lobby() {
    await monitorFocus("Lobby", 24.5); await start("lobby"); await playFocus();
    for (let i = 0; i < 15; i++) { await sleep(1000); await collectAlerts(); } await stop();
  },
  async history() {
    const thumbs = await (await fetch(APP + "api/videos")).json();
    const urls = thumbs.videos.filter(v => v.thumbnail_url).map(v => APP + v.thumbnail_url.slice(1));
    await card("history", 22.2, `buildWall(${JSON.stringify(urls)})`);
  },
  async mission() { await card("mission", 8.3); },
  async bukitraja() { await card("bukitraja", 4.6); },
  async parking1() { await monitorFocus("Parking", 0); await start("parking1"); await playFocus();
    for (let i = 0; i < 21; i++) { await sleep(1000); await collectAlerts(); } await stop(); },
  async parking2() { await monitorFocus("Parking", 48.6); await start("parking2"); await playFocus();
    for (let i = 0; i < 7; i++) { await sleep(1000); await collectAlerts(); } await stop(); },
  async parking3() {
    await go(APP + "#watch/16?t=48.6&end=59.6&bt=51.6&bx=430,540,680,850&bl=motorbike", 4500); await ev(CLEAN);
    await ev(`(() => { const p = document.getElementById("player"); p.pause(); p.currentTime = 48.6; window.scrollTo(0, 60); })()`); await sleep(1500);
    await start("parking3"); await ev(`document.getElementById("player").play()`); await sleep(9500); await stop();
  },
  async morning() { await card("morning", 5.3); },
  async search() {
    await go(APP + "#dashboard", 3000); await ev(CLEAN);
    await start("search"); await sleep(1200);
    const q = "a man stealing a motorbike";
    await ev(`document.getElementById("dash-query").focus()`);
    for (const ch of q) { await ev(`(() => { const i = document.getElementById("dash-query"); i.value += ${JSON.stringify(ch)}; i.dispatchEvent(new Event("input")); })()`); cue("key"); await sleep(85); }
    await sleep(700); await ev(`document.getElementById("dash-search").requestSubmit()`); cue("whoosh");
    await sleep(4200); await ev(`window.scrollTo({top: 360, behavior: "smooth"})`); await sleep(3800);
    await ev(`[...document.querySelectorAll("#results .result")].find(c => /Garage/.test(c.textContent)).querySelector(".actions button").click()`);
    await sleep(3500); await ev(CLEAN); await ev(`window.scrollTo(0, 60)`); await sleep(5500); await stop();
  },
  async hoodie() {
    await go(APP + "#watch/13?t=8&end=30&bt=9&bx=480,300,900,480&bl=man%20in%20dark%20hoodie", 4500); await ev(CLEAN);
    await ev(`(() => { const p = document.getElementById("player"); p.pause(); p.currentTime = 8; p.playbackRate = 2; window.scrollTo(0, 60); })()`); await sleep(1500);
    await start("hoodie"); await ev(`document.getElementById("player").play()`); await sleep(11500); await stop();
  },
  async mapcard() { await card("map", 7.0); },
  async map() {
    await go(APP + "#map", 4500); await ev(CLEAN);
    await ev(`document.querySelector('[data-style="hybrid"]').click()`); await sleep(2500);
    await start("map"); await sleep(1500);
    await ev(`(() => { const cor = videosCache.find(v => v.filename.includes("1cor")).id, fr = videosCache.find(v => v.filename.includes("1front")).id;
      const s0 = new Date(videosCache.find(v => v.id === fr).camera.started_at), s1 = new Date(videosCache.find(v => v.id === cor).camera.started_at);
      const route = [{video_id: fr, start_sec: 9, end_sec: 11, likely: true, source: true, at: new Date(s0.getTime() + 9000)}, {video_id: cor, start_sec: 9, end_sec: 13, likely: true, at: new Date(s1.getTime() + 9000)}]; route.clocked = true;
      window.mapFx.scanUpdate(fr, "hit"); window.mapFx.scanUpdate(cor, "hit");
      window.mapFx.scanFinish({query: "follow", byVideo: {[cor]: {likely: 1, maybe: 0, hits: [{start_sec: 6, end_sec: 15, span: {start_sec: 9, end_sec: 13}, likely: true}]}}, route});
      location.hash = "#search"; setTimeout(() => location.hash = "#map", 50); })()`);
    await sleep(6000);
    await ev(`(() => { const el = [...document.querySelectorAll(".cam-pin-label")].find(x => x.textContent === "Corridor")?.closest(".leaflet-marker-icon"); el?.dispatchEvent(new MouseEvent("mouseover", {bubbles: true})); })()`);
    await sleep(600); await ev(`(() => { const v = document.querySelector(".cam-pop video"); if (v) { v.muted = true; v.currentTime = 8; v.play(); } })()`);
    await sleep(4800); await stop();
  },
  async bag() { await monitorFocus("Departure", 0); await start("bag"); await playFocus();
    for (let i = 0; i < 9; i++) { await sleep(1000); await collectAlerts(); } await stop(); },
  async evidence() {
    await go(APP + "#investigations", 3500); await ev(CLEAN);
    await ev(`window.openInvestigation(2)`); await sleep(3000);
    await start("evidence"); await sleep(5000);
    await ev(`window.scrollTo({top: 300, behavior: "smooth"})`); await sleep(11000); await stop();
  },
  async evidencecard() { await card("evidence", 8.7); },
  async outcome() { await card("outcome", 9.7); },
  async pillars() { await card("pillars", 13.8); },
  async logo() { await card("logo", 12); },
  // v2 pitch cards
  async problem() {
    const thumbs = await (await fetch(APP + "api/videos")).json();
    const urls = thumbs.videos.filter(v => v.thumbnail_url).map(v => APP + v.thumbnail_url.slice(1));
    await card("problem", 12, `buildWall2(${JSON.stringify(urls)})`);
  },
  async solution() { await card("solution", 8); },
  async secprevent() { await card("sec-prevent", 3); },
  async secfind() { await card("sec-find", 3); },
  async secpeople() { await card("sec-people", 3); },
  async sectownship() { await card("sec-township", 3.5); },
  async stat40() { await card("stat40", 5); },
  async stathours() { await card("stathours", 5); },
  async why() { await card("why", 10); },
  async whynow() { await card("whynow", 11); },
  async ask() { await card("ask", 8); },
  async final() { await card("final", 11); },
};
const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SEGMENTS);
for (const name of wanted) await SEGMENTS[name]();
console.log(problems.length ? "PROBLEMS:\n" + problems.join("\n") : "no errors");
ws.close(); chrome.kill(); await sleep(800); try { rmSync(profile, {recursive: true, force: true}); } catch { /* Chrome may still be closing */ }
