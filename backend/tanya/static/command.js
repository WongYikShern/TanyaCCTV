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

// ---------------------------------------------------------------- voice search
// Chrome's speech recognition turns speech into text using Google's speech service; only the text is used.
(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return;   // the mic buttons stay hidden in browsers without it
  document.querySelectorAll(".mic").forEach(button => {
    button.hidden = false;
    let rec = null;
    button.onclick = () => {
      if (rec) { rec.stop(); return; }
      const input = $(button.dataset.target);
      rec = new Recognition(); rec.lang = navigator.language || "en-US"; rec.interimResults = true; rec.maxAlternatives = 1;
      button.classList.add("listening"); input.placeholder = "Listening… describe what you're looking for";
      rec.onresult = event => {
        input.value = [...event.results].map(r => r[0].transcript).join(" ").trim();
        input.dispatchEvent(new Event("input"));
        if (event.results[event.results.length - 1].isFinal && input.value) setTimeout(() => input.form.requestSubmit(), 350);
      };
      rec.onerror = event => { if (event.error !== "aborted") notice(event.error === "not-allowed" ? "Allow microphone access in the browser to search by voice." : `Voice search stopped (${event.error}).`); };
      rec.onend = () => { button.classList.remove("listening"); input.placeholder = "e.g. a person walking through the lobby"; rec = null; };
      rec.start();
    };
  });
})();

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
  const hide = element("button", v.camera?.hidden ? "Show on wall & map" : "Hide", "ghost small"); hide.type = "button";
  hide.title = "Hidden cameras stay in the library but are left off the camera wall, the map and “All recordings” searches.";
  hide.onclick = async () => {
    hide.disabled = true;
    try { await post(`/api/videos/${v.id}/camera`, {hidden: !v.camera?.hidden}); await library(); }
    catch (error) { notice(error.message); hide.disabled = false; }
  };
  box.append(open, hide, form);
  return box;
};

// ---------------------------------------------------------------- camera wall
window.renderCameraWall = function (box, videos) {
  box.replaceChildren();
  const ready = videos.filter(v => v.status === "done" && !v.camera?.hidden).slice(0, 7);
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

// ---------------------------------------------------------------- evidence boxes
// Boxes come from the AI's own answer ([ymin, xmin, ymax, xmax] on a 0-1000 scale, on a frame it cited).
function boxElement(box) {
  const [y0, x0, y1, x1] = box.box_2d;
  const el = element("span", undefined, "ev-box");
  el.style.left = `${x0 / 10}%`; el.style.top = `${y0 / 10}%`; el.style.width = `${(x1 - x0) / 10}%`; el.style.height = `${(y1 - y0) / 10}%`;
  el.append(element("b", box.label || "match"));
  return el;
}
window.drawEvidenceBoxes = function (pic, review) {
  const first = review.evidence_boxes.find(b => b.frame_url); if (!first) return;
  const frame = element("span", undefined, "box-frame");
  const img = element("img"); img.src = first.frame_url; img.alt = `Frame at ${time(first.timestamp)} with the AI's box`;
  frame.append(img, ...review.evidence_boxes.filter(b => b.timestamp === first.timestamp).map(boxElement));
  pic.querySelector("img")?.remove(); pic.prepend(frame);
};

// ---------------------------------------------------------------- AI incident summary (investigations)
// The draft is shown here; it is saved (as the case description) only when the person presses Save.
let summaryDraft = "";
function typeOut(node, text, done) {
  node.textContent = ""; node.classList.add("typing"); let i = 0;
  const t = setInterval(() => { i += 3; node.textContent = text.slice(0, i); if (i >= text.length) { clearInterval(t); node.textContent = text; node.classList.remove("typing"); done?.(); } }, 14);
}
$("summary-open").onclick = () => { $("summary-panel").hidden = !$("summary-panel").hidden; };
$("summary-consent").onchange = () => { $("summary-run").disabled = !$("summary-consent").checked; };
$("summary-run").onclick = async () => {
  if (!activeCase || !$("summary-consent").checked) return;
  const run = $("summary-run"); run.disabled = true; run.textContent = "Writing…";
  $("summary-actions").hidden = true; $("summary-text").hidden = false; $("summary-text").textContent = "Reading the clips and decisions…";
  try {
    const data = await post(`/api/investigations/${activeCase.id}/summary`, {approve_text_upload: true});
    summaryDraft = data.summary;
    typeOut($("summary-text"), summaryDraft, () => { $("summary-actions").hidden = false; });
  } catch (error) { $("summary-text").textContent = error.message; }
  finally { run.textContent = "Write summary"; $("summary-consent").checked = false; }
};
$("summary-save").onclick = async () => {
  if (!activeCase || !summaryDraft) return;
  try {
    await post(`/api/investigations/${activeCase.id}`, {description: summaryDraft});
    notice("Saved as the case summary. It is included in the report and the change history.");
    $("summary-actions").hidden = true; $("summary-panel").hidden = true;
    await window.refreshInvestigation?.();
  } catch (error) { notice(error.message); }
};
$("summary-discard").onclick = () => { summaryDraft = ""; $("summary-text").hidden = true; $("summary-actions").hidden = true; };

// ---------------------------------------------------------------- follow this person
// Uses the AI's own description of the person as the search for the other cameras. The usual plan and
// approval step follows; matches are "possibly the same person", never an identification.
window.followCtx = null;
window.followPerson = function (hit) {
  const reason = hit.visual_review?.reason || "";
  window.followCtx = {source: {video_id: hit.video_id, filename: hit.filename, start_sec: hit.start_sec, end_sec: hit.end_sec}, reason};
  $("query").value = `The same person as described here (match their appearance, any action): ${reason}`.slice(0, 500);
  location.hash = "#search";
  window.scrollTo({top: 0, behavior: "smooth"});
  notice(`Following the person from ${displayName(hit.filename)}. Check the plan and approve it to search the other cameras.`);
  setTimeout(() => $("search-form").requestSubmit(), 150);   // builds the plan only; nothing is sent until approved
};

function routeStops(follow, byVideo) {
  const stops = [{video_id: follow.source.video_id, start_sec: follow.source.start_sec, end_sec: follow.source.end_sec, likely: true, source: true}];
  for (const [id, e] of Object.entries(byVideo)) {
    const best = [...e.hits].sort((a, b) => (b.likely - a.likely) || (a.start_sec - b.start_sec))[0];
    if (best) stops.push({video_id: Number(id), start_sec: best.start_sec, end_sec: best.end_sec, likely: best.likely});
  }
  return stops.sort((a, b) => a.start_sec - b.start_sec);
}

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

  function start(plan, results, follow) {
    stopFlip();
    const stage = element("section", undefined, "scan-stage"); stage.setAttribute("aria-label", "Search progress");
    const kpis = element("div", undefined, "scan-kpis"); kpis.hidden = true;
    const main = element("div", undefined, "scan-main");
    const viewer = element("div", undefined, "scan-viewer");
    const img = element("img"); img.alt = "Frame from the part being checked";
    const stamp = element("span", "Preparing…", "scan-stamp");
    const boxes = element("div", undefined, "scan-boxes");
    viewer.append(img, boxes, element("div", undefined, "scan-beam"), element("div", undefined, "scan-grid"), stamp);
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

    st = {plan, stage, kpis, main, img, stamp, fill, boxes, checked, likely, maybe, log: logBox, tiles: new Map(), frames: new Map(),
          timer: null, n: {checked: 0, likely: 0, maybe: 0}, byVideo: {}, hitWindows: [], revealed: 0,
          inflight: new Map(), done: new Set(), holdUntil: 0, batchesOf: new Map(), follow: follow || null};
    if (follow) stage.classList.add("following");
    (plan.parts || []).forEach((p, i) => { if (!st.batchesOf.has(p.video_id)) st.batchesOf.set(p.video_id, new Set()); st.batchesOf.get(p.video_id).add(Math.floor(i / PER_BATCH)); });
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

  // Several batches can be in flight at once: the viewer flips through frames from all of them.
  function flip() {
    stopFlip();
    const sequence = [];
    for (const parts of st.inflight.values()) for (const p of parts) for (const f of st.frames.get(p.video_id) || [])
      if (f.timestamp_sec >= p.start_sec && f.timestamp_sec <= p.end_sec) sequence.push([p.video_id, f]);
    let k = 0;
    const show = () => {
      if (Date.now() < st.holdUntil) return;          // a lock-on frame is being shown
      if (st.boxes.classList.contains("on")) { st.boxes.classList.remove("on"); st.boxes.replaceChildren(); }
      if (!sequence.length) return;
      const [id, f] = sequence[k++ % sequence.length];
      st.img.src = f.url; st.stamp.textContent = `${nameOf(id)} · ${time(f.timestamp_sec)}`;
    };
    if (st.inflight.size) { show(); st.timer = setInterval(show, 260); }
  }

  function batchStart(batch) {
    if (!st) return;
    const parts = (st.plan.parts || []).slice(batch * PER_BATCH, (batch + 1) * PER_BATCH);
    const ids = [...new Set(parts.map(p => p.video_id))];
    ids.forEach(id => { if (!st.tiles.get(id)?.classList.contains("hit")) setTile(id, "checking", "Checking…"); });
    log(`Checking ${ids.map(nameOf).join(", ")} · ${parts.map(p => `${time(p.start_sec)}–${time(p.end_sec)}`).join(", ")}`);
    st.fill.classList.add("working");
    st.inflight.set(batch, parts);
    flip();
  }

  function batchDone(batch, result) {
    if (!st) return;
    st.inflight.delete(batch); st.done.add(batch);
    for (const [key, field] of [["hits", "likely"], ["unclear_hits", "maybe"]]) for (const hit of result[key]) {
      const entry = st.byVideo[hit.video_id]; if (!entry) continue;
      entry[field]++; entry.hits.push({start_sec: hit.start_sec, end_sec: hit.end_sec, likely: field === "likely", reason: hit.visual_review?.reason || ""});
      st.hitWindows.push([hit.video_id, hit.start_sec, hit.end_sec]);
      const reason = hit.visual_review?.reason || "";
      log(`${field === "likely" ? "✓" : "?"} ${nameOf(hit.video_id)} ${time(hit.start_sec)}–${time(hit.end_sec)} ${field}${reason ? ": " + reason.slice(0, 70) + (reason.length > 70 ? "…" : "") : ""}`, field === "likely" ? "g" : "a");
    }
    // Lock on: hold the frame the AI cited, with its box, for a moment before flipping resumes.
    const boxed = [...result.hits, ...result.unclear_hits].find(h => h.visual_review?.evidence_boxes?.some(b => b.frame_url));
    if (boxed) {
      const box = boxed.visual_review.evidence_boxes.find(b => b.frame_url);
      st.holdUntil = Date.now() + 2200;
      st.img.onload = () => {
        // The viewer letterboxes the frame (object-fit: contain), so place the layer over the drawn picture.
        const W = st.img.clientWidth, H = st.img.clientHeight, r = Math.min(W / st.img.naturalWidth, H / st.img.naturalHeight);
        const w = st.img.naturalWidth * r, h = st.img.naturalHeight * r;
        Object.assign(st.boxes.style, {left: `${(W - w) / 2}px`, top: `${(H - h) / 2}px`, width: `${w}px`, height: `${h}px`});
        st.boxes.replaceChildren(boxElement(box)); st.boxes.classList.add("on");
        st.img.onload = null;
      };
      st.img.src = box.frame_url;
      st.stamp.textContent = `${nameOf(boxed.video_id)} · ${time(box.timestamp)} · ${boxed.visual_review.verdict === "supported" ? "likely match" : "maybe"}`;
    }
    st.n.checked += result.visual_review?.sampled_frames || 0;
    st.n.likely += result.hits.length; st.n.maybe += result.unclear_hits.length;
    countUp(st.checked, st.n.checked); countUp(st.likely, st.n.likely); countUp(st.maybe, st.n.maybe);
    st.fill.style.width = `${100 * st.done.size / st.plan.max_calls}%`;
    if (!st.inflight.size) st.fill.classList.remove("working");
    // A camera is finished once every batch holding one of its parts has come back.
    for (const [id, batches] of st.batchesOf) {
      if (![...batches].every(b => st.done.has(b))) continue;
      const e = st.byVideo[id];
      if (e.likely) setTile(id, "hit", `${e.likely} likely`);
      else if (e.maybe) setTile(id, "maybe", `${e.maybe} maybe`);
      else setTile(id, "clear", "No match");
    }
    flip();
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
    let route = null;
    if (st.follow) {
      route = routeStops(st.follow, st.byVideo);
      const box = element("div", undefined, "route-card");
      box.append(element("p", route.length > 1 ? "Possible route of this person" : "Not seen on the other cameras", "route-title"));
      const chain = element("div", undefined, "route-chain");
      route.forEach((s, i) => {
        if (i) chain.append(element("span", "→", "route-arrow"));
        const stop = element("button", undefined, "route-stop" + (s.source ? " source" : s.likely ? " likely" : " maybe")); stop.type = "button";
        stop.style.animationDelay = `${0.15 + i * 0.25}s`;
        stop.append(element("b", nameOf(s.video_id)), element("span", `${time(s.start_sec)}–${time(s.end_sec)} · ${s.source ? "start" : s.likely ? "likely" : "maybe"}`));
        stop.onclick = () => openVideo(s.video_id, "", "", s.start_sec, s.end_sec);
        chain.append(stop);
      });
      box.append(chain);
      if (route.length > 1) {
        const go = element("button", "Show route on map"); go.type = "button"; go.prepend(icon("map")); go.onclick = () => { location.hash = "#map"; };
        box.append(go, element("p", "Possibly the same person: check each clip. Ordered by time within each recording, which assumes the recordings cover the same period.", "muted small-note"));
      }
      st.kpis.after(box);
    }
    window.mapFx?.scanFinish({query: st.plan.query, byVideo: st.byVideo, error: !!error, route});
  }

  return {start, batchStart, batchDone, reveal, finish};
})();
