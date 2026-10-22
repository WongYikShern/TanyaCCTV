"use strict";
// Live monitor: recordings play as live feeds; early-warning events found on this computer
// (POST /api/videos/<id>/sentinel) are raised as alerts when playback reaches them. Rules (zones, items to
// protect, watch hours) are drawn per camera in the rule editor. Uses helpers from dashboard.js.
(() => {
  const RANK = {notice: 1, warning: 2, alarm: 3};
  const TEXT = {0: ["All clear", "No warnings in the last 20 seconds"], 1: ["Notice", "Movement where it was not expected"],
                2: ["Warning", "Something needs checking now"], 3: ["ALARM", "A protected item has moved"]};
  let feeds = [], recent = [], sound = true, threatTimer = 0, editing = null;

  const cams = () => videosCache.filter(v => v.status === "done" && !v.camera?.hidden);
  const playable = v => ["playable", "copy_ready"].includes(v.playback?.status) ? v.playback.url : null;
  function boxStyle(el, b) { const [y0, x0, y1, x1] = b; Object.assign(el.style, {top: `${y0 / 10}%`, left: `${x0 / 10}%`, height: `${(y1 - y0) / 10}%`, width: `${(x1 - x0) / 10}%`}); }
  function clockFor(v, t) {
    const start = v.camera?.started_at;
    if (!start) return `${time(t)} in recording`;
    const at = new Date(new Date(start).getTime() + t * 1000);
    return Number.isNaN(at.getTime()) ? time(t) : at.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
  }
  function beep(level) {
    if (!sound || level === "notice") return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const notes = level === "alarm" ? [0, .18, .36, .54] : [0, .22];
      notes.forEach((at, i) => { const o = ctx.createOscillator(), g = ctx.createGain(); o.type = "square";
        o.frequency.value = level === "alarm" ? (i % 2 ? 660 : 990) : 880; g.gain.value = .05; o.connect(g).connect(ctx.destination);
        o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + .14); });
      setTimeout(() => ctx.close(), 1200);
    } catch (e) { /* sound is optional */ }
  }

  // ---- threat level: the highest alert in the last 20 seconds
  function updateThreat() {
    const now = Date.now(); recent = recent.filter(r => now - r.at < 20000);
    const level = recent.reduce((m, r) => Math.max(m, RANK[r.level]), 0);
    const names = ["normal", "notice", "warning", "alarm"];
    $("threat").className = "threat level-" + names[level];
    $("threat-text").textContent = TEXT[level][0];
    $("threat-sub").textContent = level ? `${TEXT[level][1]} · ${recent.length} alert(s) in the last 20 s` : TEXT[0][1];
  }

  // ---- raising one alert
  function raise(feed, e) {
    const v = feed.video, at = Date.now();
    recent.push({level: e.level, at}); updateThreat(); beep(e.level);
    window.mapFx?.scanUpdate(v.id, e.level === "alarm" ? "alarm" : e.level === "warning" ? "maybe" : "checking");
    // On the feed: a flashing box where it happened.
    const mark = element("span", undefined, "mon-flash " + e.level); boxStyle(mark, e.box_2d); mark.append(element("b", e.message));
    feed.layer.append(mark); setTimeout(() => mark.remove(), 4500);
    feed.tile.classList.remove("lvl-notice", "lvl-warning", "lvl-alarm"); void feed.tile.offsetWidth; feed.tile.classList.add("lvl-" + e.level);
    // In the list.
    const list = $("mon-alerts"); list.querySelector(".empty")?.remove();
    const li = element("li", undefined, "mon-alert " + e.level);
    const head = element("div", undefined, "mon-alert-head");
    head.append(element("span", e.level.toUpperCase(), "lvl"), element("strong", displayName(v.filename)), element("span", clockFor(v, e.t), "mono"));
    const watch = element("button", "Watch clip", "small"); watch.type = "button"; watch.prepend(icon("play"));
    watch.onclick = () => openVideo(v.id, v.filename, v.video_url, Math.max(0, e.t - 3), Math.min(v.duration_sec, e.t + 8), {t: e.t, box: e.box_2d, label: e.target});
    const dismiss = element("button", "Dismiss", "secondary small"); dismiss.type = "button"; dismiss.onclick = () => li.remove();
    const acts = element("div", undefined, "mon-alert-acts"); acts.append(watch, dismiss);
    li.append(head, element("p", e.message), acts);
    list.prepend(li);
    while (list.children.length > 30) list.lastChild.remove();
  }

  // ---- feeds
  function overlay(feed) {
    feed.layer.replaceChildren();
    const r = feed.video.camera?.rules; if (!r) return;
    for (const z of r.zones) { const el = element("span", undefined, "mon-zone"); boxStyle(el, z.box_2d); el.append(element("b", z.name)); feed.layer.append(el); }
    for (const i of r.items) { const el = element("span", undefined, "mon-item " + i.mode); boxStyle(el, i.box_2d); el.append(element("b", (i.mode === "theft" ? "🔒 " : "👜 ") + i.name)); feed.layer.append(el); }
  }
  function fitLayer(feed) {   // keep the drawing layer exactly over the letterboxed picture
    const m = feed.media, W = m.clientWidth, H = m.clientHeight, vw = m.videoWidth || m.naturalWidth, vh = m.videoHeight || m.naturalHeight;
    if (!vw || !vh) return;
    const s = Math.min(W / vw, H / vh), w = vw * s, h = vh * s;
    Object.assign(feed.layer.style, {left: `${(W - w) / 2}px`, top: `${(H - h) / 2}px`, width: `${w}px`, height: `${h}px`});
  }
  async function arm(feed) {
    feed.events = []; feed.fired = new Set(); feed.status.textContent = "Watching…";
    if (!feed.video.camera?.rules) { feed.status.textContent = "No rules yet"; feed.tile.classList.add("unarmed"); return; }
    feed.tile.classList.remove("unarmed");
    try { feed.events = (await post(`/api/videos/${feed.video.id}/sentinel`, {})).events; feed.status.textContent = "Armed"; }
    catch (error) { feed.status.textContent = error.message; }
  }
  function build() {
    const grid = $("mon-grid"); grid.replaceChildren(); feeds = [];
    for (const v of cams()) {
      const url = playable(v);
      const tile = element("div", undefined, "mon-tile");
      const stage = element("div", undefined, "mon-stage");
      const media = url ? element("video") : element("img");
      if (url) { media.muted = true; media.loop = true; media.playsInline = true; media.setAttribute("muted", ""); media.preload = "auto"; media.src = url; }
      else if (v.thumbnail_url) media.src = v.thumbnail_url;
      const layer = element("div", undefined, "mon-layer");
      stage.append(media, layer, element("span", "LIVE FEED (recording)", "mon-tag"));
      const clock = element("span", "", "mon-clock"); stage.append(clock);
      const foot = element("div", undefined, "mon-foot"), status = element("span", "", "mon-status");
      const setup = element("button", v.camera?.rules ? "Edit rules" : "Set up warnings", "secondary small"); setup.type = "button"; setup.onclick = () => openEditor(v);
      foot.append(element("strong", displayName(v.filename)), status, setup);
      tile.append(stage, foot); grid.append(tile);
      const feed = {video: v, tile, media, layer, status, clock, events: [], fired: new Set(), last: 0};
      feeds.push(feed); overlay(feed);
      if (url) {
        media.addEventListener("loadedmetadata", () => fitLayer(feed));
        media.addEventListener("timeupdate", () => {
          const t = media.currentTime;
          if (t < feed.last - 1) feed.fired.clear();            // looped: the same events can fire again
          feed.last = t; clock.textContent = clockFor(v, t);
          feed.events.forEach((e, i) => { if (!feed.fired.has(i) && e.t <= t) { feed.fired.add(i); if (e.t > t - 1.5) raise(feed, e); } });
        });
        media.play().catch(() => {});
      } else media.addEventListener("load", () => fitLayer(feed));
    }
    if (!feeds.length) grid.append(element("p", "No cameras yet. Add footage under Cameras.", "empty"));
    (async () => { for (const feed of feeds) await arm(feed); })();   // one analysis at a time
  }
  window.addEventListener("resize", () => feeds.forEach(fitLayer));
  window.showMonitor = function () {
    build(); clearInterval(threatTimer); threatTimer = setInterval(updateThreat, 1000); updateThreat();
  };
  window.leaveMonitor = function () {
    clearInterval(threatTimer);
    feeds.forEach(f => { if (f.media.pause) f.media.pause(); }); feeds = [];
    $("mon-grid")?.replaceChildren();
  };
  $("mon-restart").onclick = () => feeds.forEach(f => { if (f.media.pause) { f.media.currentTime = 0; f.fired.clear(); f.media.play().catch(() => {}); } });
  $("mon-clear").onclick = () => { $("mon-alerts").replaceChildren(element("li", "No alerts yet. Feeds with rules are being watched.", "empty")); recent = []; updateThreat(); };
  $("mon-sound").onclick = () => { sound = !sound; $("mon-sound").textContent = sound ? "Sound on" : "Sound off"; $("mon-sound").setAttribute("aria-pressed", String(sound)); };

  // ---- rule editor
  let tool = "zone", drag = null, draft = null;
  function openEditor(v) {
    const r = v.camera?.rules || {};
    editing = {video: v, zones: [...(r.zones || [])], items: [...(r.items || [])]};
    $("re-title").textContent = `Set up warnings · ${displayName(v.filename)}`;
    $("re-frame").src = v.thumbnail_url || "";
    $("re-hours-on").checked = !!r.hours; $("re-from").value = r.hours?.from || "22:00"; $("re-to").value = r.hours?.to || "06:00";
    $("rule-editor").hidden = false; renderEditor();
  }
  function renderEditor() {
    const layer = $("re-layer"); layer.replaceChildren();
    const list = $("re-list"); list.replaceChildren();
    const add = (entry, kind, idx) => {
      const el = element("span", undefined, kind === "zone" ? "mon-zone" : "mon-item " + entry.mode); boxStyle(el, entry.box_2d); el.append(element("b", entry.name)); layer.append(el);
      const li = element("li"); li.append(element("span", kind === "zone" ? "Zone" : entry.mode === "theft" ? "Protect from theft" : "Watch for unattended", "badge " + (kind === "zone" ? "info" : "pending")), element("strong", entry.name));
      const del = element("button", "Remove", "ghost small"); del.type = "button"; del.onclick = () => { (kind === "zone" ? editing.zones : editing.items).splice(idx, 1); renderEditor(); };
      li.append(del); list.append(li);
    };
    editing.zones.forEach((z, i) => add(z, "zone", i)); editing.items.forEach((it, i) => add(it, "item", i));
    if (!editing.zones.length && !editing.items.length) list.append(element("li", "Nothing set yet: drag a box on the picture.", "muted"));
    if (draft) layer.append(draft);
  }
  document.querySelectorAll(".re-tools button").forEach(b => b.onclick = () => {
    tool = b.dataset.tool; document.querySelectorAll(".re-tools button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  });
  const at = ev => { const r = $("re-layer").getBoundingClientRect(); return [Math.min(1000, Math.max(0, (ev.clientY - r.top) / r.height * 1000)), Math.min(1000, Math.max(0, (ev.clientX - r.left) / r.width * 1000))]; };
  $("re-layer").addEventListener("pointerdown", ev => { ev.preventDefault(); $("re-layer").setPointerCapture(ev.pointerId); drag = at(ev); draft = element("span", undefined, "re-draft"); boxStyle(draft, [...drag, drag[0] + 1, drag[1] + 1]); $("re-layer").append(draft); });
  $("re-layer").addEventListener("pointermove", ev => { if (!drag) return; const [y, x] = at(ev); boxStyle(draft, [Math.min(drag[0], y), Math.min(drag[1], x), Math.max(drag[0], y), Math.max(drag[1], x)]); });
  $("re-layer").addEventListener("pointerup", ev => {
    if (!drag) return;
    const [y, x] = at(ev), box = [Math.min(drag[0], y), Math.min(drag[1], x), Math.max(drag[0], y), Math.max(drag[1], x)].map(Math.round);
    drag = null; draft?.remove(); draft = null;
    if (box[2] - box[0] < 12 || box[3] - box[1] < 12) { notice("Drag a bigger box."); return; }
    const suggestion = tool === "zone" ? "Entrance" : tool === "theft" ? "motorbike" : "bag";
    const name = (window.prompt(tool === "zone" ? "Name this zone (e.g. Driveway)" : "What is this item? (e.g. motorbike, bag)", suggestion) || "").trim();
    if (!name) return;
    if (tool === "zone") editing.zones.push({name: name.slice(0, 40), box_2d: box});
    else editing.items.push({name: name.slice(0, 40), box_2d: box, mode: tool});
    renderEditor();
  });
  $("re-close").onclick = () => { $("rule-editor").hidden = true; editing = null; };
  async function saveRules(rules) {
    try {
      await post(`/api/videos/${editing.video.id}/camera`, {rules});
      $("rule-editor").hidden = true; editing = null; notice(rules ? "Rules saved. This feed is now armed." : "Rules removed.");
      await library(); window.showMonitor();
    } catch (error) { notice(error.message); }
  }
  $("re-save").onclick = () => {
    if (!editing.zones.length && !editing.items.length) { notice("Draw at least one zone or item, or press Remove all rules."); return; }
    saveRules({zones: editing.zones, items: editing.items, hours: $("re-hours-on").checked ? {from: $("re-from").value, to: $("re-to").value} : null});
  };
  $("re-clear").onclick = () => saveRules(null);
  document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !$("rule-editor").hidden) $("re-close").click(); });
})();
