"use strict";
// Command-centre layer: theme switch, camera names, the camera wall, and the visible side of a footage scan.
// Uses helpers from dashboard.js ($, element, icon, api, post, time, displayName, openVideo, notice, library,
// videosCache). The scan effects only display progress and results: every request to Google stays in
// dashboard.js behind the existing approval. All text is set with textContent.

// ---------------------------------------------------------------- theme
const THEME_KEY = "tanya.theme";
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme-toggle").querySelector("span").textContent = theme === "dark" ? "Light" : "Dark";
  window.dispatchEvent(new CustomEvent("tanya:theme", {detail: theme}));
}
try { const saved = localStorage.getItem(THEME_KEY); if (saved === "light" || saved === "dark") applyTheme(saved); } catch (e) { /* storage unavailable */ }
$("theme-toggle").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* storage unavailable */ }
};

// ---------------------------------------------------------------- camera names
window.cameraEditor = function (v) {
  const box = element("div", undefined, "cam-edit");
  const open = element("button", v.camera?.name ? "Rename / place" : "Name this camera", "ghost small"); open.type = "button"; open.prepend(icon("edit"));
  const form = element("form", undefined, "cam-edit-form"); form.hidden = true;
  const name = element("input"); name.className = "input"; name.maxLength = 60; name.placeholder = "Camera name, e.g. Front gate"; name.value = v.camera?.name || ""; name.setAttribute("aria-label", "Camera name");
  const place = element("input"); place.className = "input"; place.maxLength = 80; place.placeholder = "Place, e.g. Block A, Level 1"; place.value = v.camera?.place || ""; place.setAttribute("aria-label", "Place");
  const save = element("button", "Save"), cancel = element("button", "Cancel", "secondary"); cancel.type = "button";
  const row = element("div", undefined, "cam-edit-actions"); row.append(save, cancel);
  form.append(name, place, row);
  open.onclick = () => { form.hidden = false; open.hidden = true; name.focus(); };
  cancel.onclick = () => { form.hidden = true; open.hidden = false; };
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true;
    try { await post(`/api/videos/${v.id}/camera`, {name: name.value, place: place.value}); notice("Camera saved."); await library(); }
    catch (error) { notice(error.message); } finally { save.disabled = false; }
  };
  box.append(open, form);
  return box;
};

// ---------------------------------------------------------------- camera wall
window.renderCameraWall = function (box, videos) {
  box.replaceChildren();
  const ready = videos.filter(v => v.status === "done").slice(0, 7);
  if (videos.length && !ready.length) box.append(element("p", "Your recordings are still being prepared.", "empty"));
  ready.forEach((v, i) => {
    const tile = element("button", undefined, "cam-tile" + (i === 0 ? " big" : "")); tile.type = "button";
    tile.setAttribute("aria-label", `Open ${displayName(v.filename)}`);
    const url = ["playable", "copy_ready"].includes(v.playback?.status) ? v.playback.url : null;
    let media;
    if (url) {
      media = element("video"); media.muted = true; media.loop = true; media.playsInline = true; media.preload = "metadata";
      media.setAttribute("muted", ""); media.src = url; media.play().catch(() => {});
    } else { media = element("img"); media.alt = ""; if (v.thumbnail_url) media.src = v.thumbnail_url; }
    const clock = element("span", time(v.duration_sec), "cam-time");
    tile.append(media, element("span", displayName(v.filename), "cam-name"), element("span", "RECORDED", "cam-tag"), clock);
    if (v.camera?.place) tile.append(element("span", v.camera.place, "cam-place"));
    // Position in the recording, not a wall clock: these are recordings, not live feeds.
    if (url) media.addEventListener("timeupdate", () => { clock.textContent = `${time(media.currentTime)} / ${time(media.duration || v.duration_sec)}`; });
    tile.onclick = () => openVideo(v.id);
    box.append(tile);
  });
};

// ---------------------------------------------------------------- scan experience
window.scanFx = (() => {
  const PER_BATCH = 5;   // windows per Google request (scenario_scan.MAX_CANDIDATES)
  let st = null;
  const nameOf = id => displayName(videosCache.find(v => v.id === id)?.filename || `Recording ${id}`);
  const thumbOf = id => videosCache.find(v => v.id === id)?.thumbnail_url || "";

  async function loadFrames(videoId) {
    const out = [];
    for (let page = 0; page < 20; page++) {
      const data = await api(`/api/videos/${videoId}/frames?page=${page}`);
      out.push(...data.frames);
      if (!data.has_more) break;
    }
    return out;
  }
  function stopFlip() { if (st?.timer) { clearInterval(st.timer); st.timer = null; } }
  function log(text, kind) {
    const line = element("div", text, kind || ""); st.log.prepend(line);
    while (st.log.children.length > 6) st.log.lastChild.remove();
  }
  function countUp(node, to, format = n => String(n)) {
    const from = Number(node.dataset.value || 0); node.dataset.value = to;
    const steps = 18; let i = 0;
    const timer = setInterval(() => { i++; node.textContent = format(Math.round(from + (to - from) * i / steps)); if (i >= steps) clearInterval(timer); }, 28);
  }
  function setTile(id, state, label) {
    const tile = st.tiles.get(id); if (!tile) return;
    tile.className = "sweep-tile " + state;
    tile.querySelector(".sweep-state").textContent = label;
    window.mapFx?.scanUpdate(id, state);
  }

  function start(plan, results) {
    stopFlip();
    const stage = element("section", undefined, "scan-stage"); stage.setAttribute("aria-label", "Search progress");
    const kpis = element("div", undefined, "scan-kpis"); kpis.hidden = true;
    const main = element("div", undefined, "scan-main");
    const viewer = element("div", undefined, "scan-viewer");
    const img = element("img"); img.alt = "Frame from the part being checked";
    const stamp = element("span", "Preparing…", "scan-stamp");
    viewer.append(img, element("div", undefined, "scan-beam"), element("div", undefined, "scan-grid"), stamp);
    const side = element("div", undefined, "scan-side");
    const bar = element("div", undefined, "scan-bar"), fill = element("i"); bar.append(fill);
    const counts = element("div", undefined, "scan-counts");
    const mk = (label, cls) => { const d = element("div", undefined, cls); const b = element("b", "0"); d.append(b, element("span", label)); counts.append(d); return b; };
    const checked = mk("images checked", ""), likely = mk("likely", "g"), maybe = mk("maybe", "a");
    const logBox = element("div", undefined, "scan-log");
    const mini = element("div", undefined, "scan-mini"); mini.hidden = true;
    side.append(element("p", "Looking for", "scan-label"), element("p", `“${plan.query}”`, "scan-query"), bar, counts, logBox, mini);
    main.append(viewer, side);
    const tiles = element("div", undefined, "sweep-row");
    stage.append(kpis, main, tiles);
    results.insertBefore(stage, results.children[1] || null);

    st = {plan, stage, kpis, main, img, stamp, fill, checked, likely, maybe, log: logBox, tiles: new Map(), frames: new Map(),
          timer: null, n: {checked: 0, likely: 0, maybe: 0}, byVideo: {}, hitWindows: [], revealed: 0};
    for (const r of plan.recordings) {
      const tile = element("div", undefined, "sweep-tile waiting");
      const t = element("img"); t.alt = ""; if (thumbOf(r.video_id)) t.src = thumbOf(r.video_id);
      tile.append(t, element("span", nameOf(r.video_id), "sweep-name"), element("span", "Waiting", "sweep-state"), element("div", undefined, "scan-beam"));
      tiles.append(tile); st.tiles.set(r.video_id, tile); st.byVideo[r.video_id] = {likely: 0, maybe: 0, hits: []};
    }
    if (thumbOf(plan.recordings[0]?.video_id)) img.src = thumbOf(plan.recordings[0].video_id);
    log(`Plan: ${plan.windows} part(s) across ${plan.recordings.length} camera(s), up to ${plan.max_images} images.`);
    for (const r of plan.recordings) loadFrames(r.video_id).then(f => st?.frames.set(r.video_id, f)).catch(() => {});
    window.mapFx?.scanStart(plan, mini);
  }

  function batchStart(batch) {
    if (!st) return;
    const parts = (st.plan.parts || []).slice(batch * PER_BATCH, (batch + 1) * PER_BATCH);
    const ids = [...new Set(parts.map(p => p.video_id))];
    ids.forEach(id => setTile(id, "checking", "Checking…"));
    log(`Checking ${ids.map(nameOf).join(", ")} · ${parts.map(p => `${time(p.start_sec)}–${time(p.end_sec)}`).join(", ")}`);
    st.fill.style.width = `${Math.max(3, 100 * batch / st.plan.max_calls)}%`;
    st.fill.classList.add("working");
    // Frames from the parts this request covers, flipped through while Google checks its sample of them.
    const sequence = [];
    for (const p of parts) for (const f of st.frames.get(p.video_id) || [])
      if (f.timestamp_sec >= p.start_sec && f.timestamp_sec <= p.end_sec) sequence.push([p.video_id, f]);
    let k = 0;
    stopFlip();
    const show = () => {
      if (!sequence.length) { st.stamp.textContent = `${ids.map(nameOf).join(", ")} · checking`; return; }
      const [id, f] = sequence[k++ % sequence.length];
      st.img.src = f.url; st.stamp.textContent = `${nameOf(id)} · ${time(f.timestamp_sec)}`;
    };
    show(); st.timer = setInterval(show, 300);
  }

  function batchDone(batch, result) {
    if (!st) return;
    stopFlip();
    const parts = st.plan.parts || [];
    const lastIndex = {}; parts.forEach((p, i) => { lastIndex[p.video_id] = i; });
    for (const [key, field] of [["hits", "likely"], ["unclear_hits", "maybe"]]) for (const hit of result[key]) {
      const entry = st.byVideo[hit.video_id]; if (!entry) continue;
      entry[field]++; entry.hits.push({start_sec: hit.start_sec, end_sec: hit.end_sec, likely: field === "likely", reason: hit.visual_review?.reason || ""});
      st.hitWindows.push([hit.video_id, hit.start_sec, hit.end_sec]);
      const reason = hit.visual_review?.reason || "";
      log(`${field === "likely" ? "✓" : "?"} ${nameOf(hit.video_id)} ${time(hit.start_sec)}–${time(hit.end_sec)} ${field}${reason ? ": " + reason.slice(0, 70) + (reason.length > 70 ? "…" : "") : ""}`, field === "likely" ? "g" : "a");
    }
    st.n.checked += result.visual_review?.sampled_frames || 0;
    st.n.likely += result.hits.length; st.n.maybe += result.unclear_hits.length;
    countUp(st.checked, st.n.checked); countUp(st.likely, st.n.likely); countUp(st.maybe, st.n.maybe);
    st.fill.style.width = `${100 * (batch + 1) / st.plan.max_calls}%`; st.fill.classList.remove("working");
    const doneUpTo = (batch + 1) * PER_BATCH - 1;
    for (const [id, last] of Object.entries(lastIndex)) {
      if (last > doneUpTo) continue;
      const e = st.byVideo[id];
      if (e.likely) setTile(Number(id), "hit", `${e.likely} likely`);
      else if (e.maybe) setTile(Number(id), "maybe", `${e.maybe} maybe`);
      else setTile(Number(id), "clear", "No match");
    }
  }

  function reveal(card) {
    card.classList.add("lock");
    card.style.animationDelay = `${Math.min(st ? st.revealed++ : 0, 6) * 0.12}s`;
    const thumbBox = card.querySelector(".result-thumb");
    if (thumbBox) { const b = element("span", undefined, "brackets"); for (const c of ["tl", "tr", "bl", "br"]) b.append(element("i", undefined, c)); thumbBox.append(b); }
    const reason = card.querySelector(".reason");
    if (reason && reason.textContent) {
      const full = reason.textContent; reason.textContent = ""; reason.classList.add("typing");
      let i = 0;
      setTimeout(() => { const t = setInterval(() => { i += 2; reason.textContent = full.slice(0, i); if (i >= full.length) { clearInterval(t); reason.textContent = full; reason.classList.remove("typing"); } }, 16); }, 450);
    }
  }

  function covered(windows) {   // seconds covered by the union of [start,end] windows, per recording
    const byId = {}; windows.forEach(([id, s, e]) => (byId[id] ||= []).push([s, e]));
    let total = 0;
    for (const list of Object.values(byId)) {
      list.sort((a, b) => a[0] - b[0]);
      let [cs, ce] = list[0];
      for (const [s, e] of list.slice(1)) { if (s <= ce) ce = Math.max(ce, e); else { total += ce - cs; [cs, ce] = [s, e]; } }
      total += ce - cs;
    }
    return total;
  }

  function finish({seconds, images, completed, stopped, error}) {
    if (!st) return;
    stopFlip();
    const footage = st.plan.ranges.reduce((s, r) => s + (r.end_sec - r.start_sec), 0);
    const watch = st.hitWindows.length ? Math.min(footage, covered(st.hitWindows)) : 0;
    const less = footage && watch ? Math.max(0, Math.round(100 * (1 - watch / footage))) : null;
    const k = st.kpis; k.replaceChildren();
    const kpi = (label, cls) => { const d = element("div", undefined, "kpi " + (cls || "")); const b = element("b", "0"); d.append(b, element("span", label)); k.append(d); return b; };
    countUp(kpi("search time", "hot"), Math.max(1, Math.round(seconds)), n => `${n} s`);
    countUp(kpi(`footage from ${st.plan.recordings.length} camera(s)`), Math.round(footage), n => time(n));
    countUp(kpi("likely moments", "g"), st.n.likely);
    if (less !== null) countUp(kpi(`less to watch (${time(watch)} of clips)`, "hot"), less, n => `${n}%`);
    else { const d = element("div", undefined, "kpi"); d.append(element("b", "—"), element("span", st.n.maybe ? "check the “maybe” clips" : "no matching moments")); k.append(d); }
    k.hidden = false;
    st.stage.classList.add(error ? "failed" : "done");
    st.stamp.textContent = error ? "Search stopped" : stopped ? "Stopped early" : `Done · ${images} images checked`;
    for (const tile of st.tiles.values()) if (tile.classList.contains("checking") || tile.classList.contains("waiting")) {
      tile.className = "sweep-tile skipped"; tile.querySelector(".sweep-state").textContent = error || stopped ? "Not checked" : "No match";
    }
    window.mapFx?.scanFinish({query: st.plan.query, byVideo: st.byVideo, error: !!error});
  }

  return {start, batchStart, batchDone, reveal, finish};
})();
