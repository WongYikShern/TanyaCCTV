"use strict";
// Watch mode: while this page is open, each NEW recording (uploaded, or copied into the video folder) is
// checked against one rule, e.g. "a person lying on the floor". The person approves the rule once, with a
// cap on images per recording; longer recordings are skipped, not sent. Matches raise an on-screen alert.
// Uses helpers from dashboard.js; all text is set with textContent.
(() => {
  const MAX_IMAGES_PER_RECORDING = 60;   // about 50 s of footage at 6 images per 12 s part
  const POLL_MS = 6000;
  let watching = null;                   // {rule, seen: Set, timer, checking}

  const fmtClock = () => new Date().toLocaleTimeString();
  function status(text) { $("watch-status").textContent = text; }
  function log(text, kind) {
    const li = element("li", `${fmtClock()} · ${text}`, kind || "");
    $("watch-log").prepend(li);
    while ($("watch-log").children.length > 6) $("watch-log").lastChild.remove();
  }
  function controls() {
    const on = !!watching;
    $("watch-rule").disabled = on; $("watch-consent").disabled = on;
    $("watch-start").textContent = on ? "Stop watching" : "Start watching";
    $("watch-start").classList.toggle("secondary", on);
    $("watch-start").disabled = !on && !($("watch-rule").value.trim() && $("watch-consent").checked);
    $("watch-card").classList.toggle("on", on);
  }

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.22].forEach(at => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "square"; o.frequency.value = 880; g.gain.value = 0.06;
        o.connect(g).connect(ctx.destination); o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.14);
      });
      setTimeout(() => ctx.close(), 800);
    } catch (e) { /* sound is optional */ }
  }

  function alertFor(video, hit, rule) {
    const review = hit.visual_review || {};
    const box = element("div", undefined, "watch-alert " + (review.verdict === "supported" ? "likely" : "maybe"));
    box.setAttribute("role", "alert");
    const pic = element("div", undefined, "watch-alert-pic");
    const frame = review.evidence_boxes?.find(b => b.frame_url);
    if (frame) window.drawEvidenceBoxes?.(pic, review);
    else if (hit.thumbnail_url) { const img = element("img"); img.src = hit.thumbnail_url; img.alt = ""; pic.append(img); }
    const text = element("div");
    text.append(element("strong", `Watch alert · ${displayName(video.filename)}`),
                element("span", `“${rule}” · ${time(hit.start_sec)}–${time(hit.end_sec)} · ${review.verdict === "supported" ? "likely" : "maybe"} (AI suggestion: check the clip)`),
                element("p", review.reason || "", "muted"));
    const acts = element("div", undefined, "watch-alert-acts");
    const play = element("button", "Play clip"); play.type = "button"; play.prepend(icon("play"));
    const span = review.evidence_span;
    const first = review.evidence_boxes?.[0];
    const follow = first ? {t: first.timestamp, box: first.box_2d, label: first.label} : null;
    play.onclick = () => { openVideo(video.id, video.filename, video.video_url, span?.start_sec ?? hit.start_sec, span?.end_sec ?? hit.end_sec, follow); box.remove(); };
    const map = element("button", "On map", "secondary"); map.type = "button"; map.onclick = () => { location.hash = "#map"; box.remove(); };
    const close = element("button", "Dismiss", "secondary"); close.type = "button"; close.onclick = () => box.remove();
    acts.append(play, map, close); text.append(acts);
    box.append(pic, text);
    $("watch-alerts").prepend(box);
    window.mapFx?.scanUpdate(video.id, review.verdict === "supported" ? "hit" : "maybe");
    beep();
  }

  async function check(video) {
    const rule = watching.rule;
    log(`New recording: ${displayName(video.filename)}. Checking…`);
    status(`Checking ${displayName(video.filename)}…`);
    let plan;
    try { plan = await post("/api/search/scan/plan", {query: rule, video_ids: [video.id]}); }
    catch (error) { log(`Could not plan a check (${error.message}). Will try again.`, "warn"); return false; }
    if (plan.max_images > MAX_IMAGES_PER_RECORDING) {
      post("/api/search/scan/cancel", {scan_id: plan.scan_id}).catch(() => {});
      log(`Skipped ${displayName(video.filename)}: it needs ${plan.max_images} images, over the ${MAX_IMAGES_PER_RECORDING}-image limit you approved. Search it by hand instead.`, "warn");
      return true;
    }
    let found = 0;
    try {
      for (let batch = 0; batch < plan.max_calls && watching; batch++) {
        const result = await post("/api/search/scan/batch", {scan_id: plan.scan_id, batch, approve_frame_upload: true});
        for (const hit of [...result.hits, ...result.unclear_hits]) { alertFor(video, hit, rule); found++; }
      }
      log(found ? `${displayName(video.filename)}: ${found} possible match(es). Alert raised.` : `${displayName(video.filename)}: no match.`, found ? "hit" : "");
    } catch (error) {
      log(`${displayName(video.filename)}: check stopped (${error.message}).`, "warn");
    } finally { post("/api/search/scan/cancel", {scan_id: plan.scan_id}).catch(() => {}); }
    return true;
  }

  async function tick() {
    if (!watching || watching.checking || operationRunning) return;
    watching.checking = true;
    try {
      let data = await api("/api/videos");
      if (data.waiting_files.length) {   // footage copied straight into the folder: add it first
        log(`${data.waiting_files.length} new file(s) in the video folder. Adding…`);
        await post("/api/index"); data = await api("/api/videos");
      }
      const fresh = data.videos.filter(v => v.status === "done" && !v.camera?.hidden && !watching.seen.has(v.id));
      if (fresh.length) await library().catch(() => {});
      for (const v of fresh) { if (!watching) break; if (await check(v)) watching.seen.add(v.id); }
      if (watching) status(`Watching for “${watching.rule}” · ${watching.seen.size} recording(s) known · checked ${fmtClock()}`);
    } catch (error) { status(`Watching (last check failed: ${error.message})`); }
    finally { if (watching) watching.checking = false; }
  }

  $("watch-rule").addEventListener("input", controls);
  $("watch-consent").onchange = controls;
  $("watch-start").onclick = async () => {
    if (watching) { clearInterval(watching.timer); watching = null; status("Not watching."); log("Stopped watching."); controls(); return; }
    const rule = $("watch-rule").value.trim();
    if (!rule || !$("watch-consent").checked) return;
    let data;
    try { data = await api("/api/videos"); } catch (error) { notice(error.message); return; }
    // Only footage that arrives from now on is checked.
    watching = {rule, seen: new Set(data.videos.map(v => v.id)), timer: null, checking: false};
    watching.timer = setInterval(tick, POLL_MS);
    log(`Watching for “${rule}”. New recordings will be checked automatically while this page is open.`);
    status(`Watching for “${rule}”…`); controls();
  };
  controls();
})();
