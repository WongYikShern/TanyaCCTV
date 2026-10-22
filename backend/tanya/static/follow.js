"use strict";
// Follow a person or object in the video player. A square comes from the AI's box on a search result, or
// from the person dragging one on the paused video; the recording is then tracked on this computer
// (POST /api/videos/<id>/track, nothing is sent elsewhere) and the square moves with playback. Where the
// tracker loses the target the square turns grey and says so. Uses helpers from dashboard.js.
(() => {
  const player = $("player"), layer = $("track-layer"), boxEl = $("track-box"), draft = $("track-draft");
  let follow = null, drawing = false, drag = null, frame = 0, token = 0;

  // The video is letterboxed inside its frame: keep the drawing layer exactly over the picture.
  function fitLayer() {
    const W = player.clientWidth, H = player.clientHeight, vw = player.videoWidth, vh = player.videoHeight;
    if (!vw || !vh) return false;
    const s = Math.min(W / vw, H / vh), w = vw * s, h = vh * s;
    Object.assign(layer.style, {left: `${player.offsetLeft + (W - w) / 2}px`, top: `${player.offsetTop + (H - h) / 2}px`, width: `${w}px`, height: `${h}px`});
    return true;
  }
  function status(text, kind) { $("track-status").textContent = text || ""; $("track-status").className = "track-status " + (kind || ""); }
  function place(el, box) {
    const [y0, x0, y1, x1] = box;
    Object.assign(el.style, {left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%`});
  }

  // Position at the current playback time, interpolated between tracked points.
  function render() {
    cancelAnimationFrame(frame);
    if (!follow?.points?.length) { boxEl.hidden = true; return; }
    fitLayer();
    const t = player.currentTime, pts = follow.points;
    let box = null, lost = false, hidden = false;
    if (t >= pts[0].t && t <= pts[pts.length - 1].t) {
      let i = 0; while (i < pts.length - 2 && pts[i + 1].t <= t) i++;
      const a = pts[i], b = pts[i + 1] || a, f = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 0;
      box = a.box_2d.map((c, k) => c + (b.box_2d[k] - c) * f);
      hidden = (f < .5 ? a : b).seen === false;   // tracker still has a place, but the target doesn't look like it
    } else if (follow.lost_after !== null && t > pts[pts.length - 1].t && t < follow.lost_after + 3) { box = pts[pts.length - 1].box_2d; lost = true; }
    else if (follow.lost_before !== null && t < pts[0].t && t > follow.lost_before - 3) { box = pts[0].box_2d; lost = true; }
    boxEl.hidden = !box;
    if (box) { place(boxEl, box); boxEl.classList.toggle("lost", lost || hidden); $("track-label").textContent = lost ? `${follow.label} · lost` : hidden ? `${follow.label} · not visible` : follow.label; }
    if (!player.paused) frame = requestAnimationFrame(render);
  }
  ["timeupdate", "seeked", "play", "pause", "loadedmetadata"].forEach(e => player.addEventListener(e, render));
  window.addEventListener("resize", render);

  async function start(videoId, t, box, label) {
    const mine = ++token;
    follow = null; boxEl.hidden = true; $("track-clear").hidden = false;
    status("Following… tracking the target on this computer (about 10 seconds)", "busy");
    try {
      const result = await post(`/api/videos/${videoId}/track`, {timestamp: t, box_2d: box});
      if (mine !== token) return;
      follow = {...result, label: label || "target"};
      const lost = result.lost_after !== null ? ` Lost from ${time(result.lost_after)}.` : "";
      status(`Following “${follow.label}” ${time(result.from)}–${time(result.to)}.${lost}`, "on");
      render();
    } catch (error) { if (mine === token) { status(error.message, "warn"); $("track-clear").hidden = true; } }
  }
  window.clearFollow = function () { token++; follow = null; boxEl.hidden = true; draft.hidden = true; status(""); $("track-clear").hidden = true; stopDrawing(); };

  // From a search result: #watch/<id>?t=..&bt=<box time>&bx=y0,x0,y1,x1&bl=<label>
  window.followFromRoute = function (params) {
    if (!params.has("bx")) return;
    const box = params.get("bx").split(",").map(Number), t = Number(params.get("bt")), label = params.get("bl") || "target";
    const videoId = activeVideo;
    if (box.length !== 4 || box.some(n => !Number.isFinite(n)) || !Number.isFinite(t)) return;
    start(videoId, t, box, label);
  };

  // Drawing a square by hand.
  function stopDrawing() { drawing = false; drag = null; layer.classList.remove("drawing"); $("track-draw").textContent = "Follow someone"; }
  $("track-draw").onclick = () => {
    if (drawing) { stopDrawing(); status(""); return; }
    if (!player.getAttribute("src") || !fitLayer()) { notice("Wait for the video to load first."); return; }
    player.pause(); drawing = true; layer.classList.add("drawing"); $("track-draw").textContent = "Cancel";
    status("Drag a square around the person or object to follow.", "busy");
  };
  $("track-clear").onclick = () => window.clearFollow();
  const at = event => {
    const r = layer.getBoundingClientRect();
    return [Math.min(1000, Math.max(0, (event.clientY - r.top) / r.height * 1000)), Math.min(1000, Math.max(0, (event.clientX - r.left) / r.width * 1000))];
  };
  layer.addEventListener("pointerdown", event => {
    if (!drawing) return;
    event.preventDefault(); layer.setPointerCapture(event.pointerId);
    drag = at(event); draft.hidden = false; place(draft, [drag[0], drag[1], drag[0] + 1, drag[1] + 1]);
  });
  layer.addEventListener("pointermove", event => {
    if (!drawing || !drag) return;
    const [y, x] = at(event);
    place(draft, [Math.min(drag[0], y), Math.min(drag[1], x), Math.max(drag[0], y), Math.max(drag[1], x)]);
  });
  layer.addEventListener("pointerup", event => {
    if (!drawing || !drag) return;
    const [y, x] = at(event), box = [Math.min(drag[0], y), Math.min(drag[1], x), Math.max(drag[0], y), Math.max(drag[1], x)].map(Math.round);
    draft.hidden = true; stopDrawing();
    if (box[2] - box[0] < 15 || box[3] - box[1] < 15) { status("That square is too small. Press Follow someone and drag a bigger one.", "warn"); return; }
    start(activeVideo, player.currentTime, box, "your selection");
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && drawing) { stopDrawing(); draft.hidden = true; status(""); } });
})();
