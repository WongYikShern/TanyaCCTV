"use strict";
// Camera map ("global view"): an operations map with camera view cones, site zones, live previews on
// hover, scan status and an animated route for "Follow this person". Locations, headings and sites are
// set by people (drag a pin, rotate, or type a place); nothing is inferred from footage. Map pictures
// come from Esri's public tile service (no key); only tile requests go to it. Uses helpers from
// dashboard.js; all names are set with textContent.
(() => {
  const DEMO_CENTRE = [3.1478, 101.7130], FOV = 70;   // demo placement centre (Kuala Lumpur); cone width in degrees
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  const tile = name => `${ESRI}${name}/MapServer/tile/{z}/{y}/{x}`;
  // [url, deepest zoom the service draws]
  const STYLES = {
    dark: [[tile("Canvas/World_Dark_Gray_Base"), 16], [tile("Canvas/World_Dark_Gray_Reference"), 16]],
    light: [[tile("World_Street_Map"), 19]],
    satellite: [[tile("World_Imagery"), 19]],
    hybrid: [[tile("World_Imagery"), 19], [tile("Reference/World_Transportation"), 19], [tile("Reference/World_Boundaries_and_Places"), 19]],
  };
  const ATTRIBUTION = 'Tiles &copy; <a href="https://www.esri.com/">Esri</a> and its data providers';
  const STATE_TEXT = {hit: "Match found", maybe: "Maybe", clear: "No match", checking: "Checking…", skipped: "Not checked"};
  let map = null, base = null, style = "street", placing = null, mini = null, zones = null, routeLayer = null, traveller = null;
  const markers = new Map(), miniMarkers = new Map(), scanState = new Map();
  let lastScan = null;

  const located = v => Number.isFinite(v.camera?.lat) && Number.isFinite(v.camera?.lng);
  const cameras = () => videosCache.filter(v => v.status === "done" && !v.camera?.hidden);
  const site = v => (v.camera?.place || "").split(" · ")[0].trim();
  const styleKey = () => style === "street" ? (document.documentElement.dataset.theme === "light" ? "light" : "dark") : style;
  function tiles(target) {
    return L.layerGroup(STYLES[styleKey()].map(([url, native]) => L.tileLayer(url, {attribution: ATTRIBUTION, maxZoom: 19, maxNativeZoom: native}))).addTo(target);
  }

  // ---- pins: camera glyph, status ring, view cone, label
  function pin(v, small) {
    const state = scanState.get(v.id) || "";
    const el = element("div", undefined, "cam-pin " + state + (small ? " small" : ""));
    if (Number.isFinite(v.camera?.heading)) {
      const cone = element("span", undefined, "cam-fov");
      cone.style.setProperty("--heading", `${v.camera.heading - FOV / 2}deg`);
      el.append(cone);
    }
    const dot = element("span", undefined, "cam-pin-dot"); dot.append(icon("library"));
    el.append(dot, element("span", displayName(v.filename), "cam-pin-label"));
    return L.divIcon({html: el, className: "cam-pin-wrap", iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -16]});
  }
  function preview(v) {
    const box = element("div", undefined, "cam-pop");
    const media = element("div", undefined, "cam-pop-media");
    const url = ["playable", "copy_ready"].includes(v.playback?.status) ? v.playback.url : null;
    if (url) { const vid = element("video"); vid.muted = true; vid.loop = true; vid.playsInline = true; vid.autoplay = true; vid.setAttribute("muted", ""); vid.src = url; media.append(vid); vid.play().catch(() => {}); }
    else if (v.thumbnail_url) { const img = element("img"); img.src = v.thumbnail_url; img.alt = ""; media.append(img); }
    media.append(element("span", "RECORDED", "cam-pop-tag"));
    box.append(media, element("strong", displayName(v.filename)));
    if (v.camera?.place) box.append(element("span", v.camera.place, "muted"));
    const state = scanState.get(v.id);
    if (state) box.append(element("span", STATE_TEXT[state] || "", "cam-pop-state " + state));
    const found = lastScan?.byVideo[v.id];
    const acts = element("div", undefined, "cam-pop-acts");
    if (found?.hits.length) {
      const best = found.hits.find(h => h.likely) || found.hits[0];
      const s = best.span?.start_sec ?? best.start_sec, e = best.span?.end_sec ?? best.end_sec;
      const play = element("button", `Play match ${time(s)}–${time(e)}`); play.type = "button"; play.prepend(icon("play"));
      play.onclick = () => openVideo(v.id, v.filename, v.video_url, s, e); acts.append(play);
    }
    const open = element("button", "Open camera", "secondary"); open.type = "button"; open.onclick = () => openVideo(v.id); acts.append(open);
    box.append(acts);
    return box;
  }
  async function save(id, data) {
    try { await post(`/api/videos/${id}/camera`, data); await library(); render(); }
    catch (error) { notice(error.message); }
  }
  function hint(text) { $("map-hint").textContent = text || ""; $("map-canvas").classList.toggle("placing", !!placing); }

  // ---- site zones: cameras sharing the first part of their place ("Mall · Lobby") form a labelled area
  function drawZones() {
    zones?.remove();
    const groups = {};
    for (const v of cameras().filter(located)) { const s = site(v); if (s) (groups[s] ||= []).push(v); }
    const layers = [];
    for (const [name, list] of Object.entries(groups)) {
      if (list.length < 2) continue;
      const lat = list.reduce((a, v) => a + v.camera.lat, 0) / list.length, lng = list.reduce((a, v) => a + v.camera.lng, 0) / list.length;
      const radius = 30 + Math.max(...list.map(v => map.distance([lat, lng], [v.camera.lat, v.camera.lng])));
      const zone = L.circle([lat, lng], {radius, className: "site-zone", interactive: false});
      zone.bindTooltip(`${name.toUpperCase()} · ${list.length} cameras`, {permanent: true, direction: "top", className: "site-label", offset: [0, -4]});
      layers.push(zone);
    }
    zones = L.layerGroup(layers).addTo(map);
  }

  // ---- route: glowing path, clock-time chips and a dot travelling from stop to stop
  function drawRoute() {
    routeLayer?.remove(); routeLayer = null; cancelAnimationFrame(traveller?.frame || 0); traveller = null;
    const stops = (lastScan?.route || []).map(s => ({s, v: videosCache.find(v => v.id === s.video_id)})).filter(x => x.v && located(x.v) && !x.v.camera?.hidden);
    if (stops.length < 2) return;
    const pts = stops.map(x => L.latLng(x.v.camera.lat, x.v.camera.lng));
    const dot = L.marker(pts[0], {icon: L.divIcon({html: element("span", undefined, "route-dot"), className: "route-dot-wrap", iconSize: [18, 18], iconAnchor: [9, 9]}), interactive: false, keyboard: false});
    const chips = stops.map((x, i) => L.marker(pts[i], {interactive: false, keyboard: false, icon: L.divIcon({className: "route-chip-wrap", iconSize: [0, 0],
      html: element("span", `${i + 1} · ${window.routeTime(x.s)}`, "route-chip" + (x.s.source ? " source" : ""))})}));
    routeLayer = L.layerGroup([
      L.polyline(pts, {className: "route-glow", weight: 14, opacity: .22, color: "#3DD68C", interactive: false}),
      L.polyline(pts, {className: "route-line", weight: 4, color: "#3DD68C", interactive: false}),
      ...chips, dot]).addTo(map);
    // Move the dot along each leg in turn, pausing briefly at each camera. Each drawing has its own loop,
    // which stops as soon as the route is redrawn.
    const LEG_MS = 1600, PAUSE_MS = 500;
    const run = {frame: 0, start: performance.now()};
    traveller = run;
    const total = (pts.length - 1) * (LEG_MS + PAUSE_MS);
    const step = now => {
      if (traveller !== run) return;
      const t = Math.max(0, now - run.start) % (total + 900);   // a frame's timestamp can precede run.start
      if (t > total) { dot.setLatLng(pts[pts.length - 1]); run.frame = requestAnimationFrame(step); return; }
      const leg = Math.min(pts.length - 2, Math.floor(t / (LEG_MS + PAUSE_MS)));
      const f = Math.min(1, (t - leg * (LEG_MS + PAUSE_MS)) / LEG_MS), ease = f < .5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2;
      const a = pts[leg], b = pts[leg + 1];
      dot.setLatLng([a.lat + (b.lat - a.lat) * ease, a.lng + (b.lng - a.lng) * ease]);
      run.frame = requestAnimationFrame(step);
    };
    run.frame = requestAnimationFrame(step);
  }

  function render() {
    if (!map) return;
    markers.forEach(m => m.remove()); markers.clear();
    for (const v of cameras().filter(located)) {
      const m = L.marker([v.camera.lat, v.camera.lng], {icon: pin(v), draggable: true, keyboard: true, title: displayName(v.filename), riseOnHover: true});
      m.bindPopup(() => preview(v), {className: "cam-popup", minWidth: 260, maxWidth: 300, autoPan: true});
      m.on("mouseover", () => m.openPopup());
      m.on("dragend", () => save(v.id, {lat: m.getLatLng().lat, lng: m.getLatLng().lng}));
      m.addTo(map); markers.set(v.id, m);
    }
    drawZones(); drawRoute();
    renderList(); renderHud();
  }
  function renderHud() {
    const list = cameras();
    $("hud-cams").textContent = String(list.filter(located).length);
    $("hud-sites").textContent = String(new Set(list.filter(located).map(site).filter(Boolean)).size);
    $("hud-hits").textContent = String([...scanState.values()].filter(s => s === "hit" || s === "maybe").length);
    const banner = $("map-scan");
    banner.hidden = !lastScan;
    if (lastScan) {
      const found = Object.entries(lastScan.byVideo).filter(([, e]) => e.likely || e.maybe);
      const name = id => displayName(videosCache.find(v => v.id === Number(id))?.filename);
      banner.textContent = lastScan.route?.length > 1
        ? "Possible route: " + lastScan.route.map(s => `${name(s.video_id)} ${window.routeTime(s)}`).join(" → ") + " · possibly the same person, check each clip"
        : `Latest search “${lastScan.query}”: ` + (found.length ? found.map(([id, e]) => `${name(id)} (${e.likely ? e.likely + " likely" : e.maybe + " maybe"})`).join(", ") : "no matching moments")
          + (lastScan.error ? " · search did not finish" : "");
    }
  }
  function renderList() {
    const list = $("map-list"); list.replaceChildren();
    if (!cameras().length) list.append(element("p", "Add footage first, then place each camera here.", "empty"));
    for (const v of cameras()) {
      const row = element("div", undefined, "map-row" + (placing === v.id ? " active" : ""));
      const t = element("img"); t.alt = ""; if (v.thumbnail_url) t.src = v.thumbnail_url;
      const text = element("div", undefined, "map-row-text");
      text.append(element("strong", displayName(v.filename)), element("span", located(v) ? (v.camera.place || "On the map") : "Not on the map yet", "muted"));
      const state = scanState.get(v.id); if (state) text.append(element("span", STATE_TEXT[state] || "", "map-state " + state));
      const acts = element("div", undefined, "map-row-acts");
      const btn = (label, title, fn, cls = "secondary small") => { const b = element("button", label, cls); b.type = "button"; b.title = title; b.setAttribute("aria-label", title); b.onclick = fn; acts.append(b); return b; };
      btn(located(v) ? "Move" : "Place", "Choose this camera, then click the map", () => { placing = placing === v.id ? null : v.id; hint(placing ? `Click on the map where “${displayName(v.filename)}” is.` : ""); renderList(); });
      if (located(v)) {
        btn("Show", "Fly to this camera", () => { map.flyTo([v.camera.lat, v.camera.lng], 18, {duration: .8}); setTimeout(() => markers.get(v.id)?.openPopup(), 850); });
        btn("↺", "Turn the view cone 30° left", () => save(v.id, {heading: ((v.camera.heading ?? 0) - 30 + 360) % 360}));
        btn("↻", "Turn the view cone 30° right", () => save(v.id, {heading: ((v.camera.heading ?? 0) + 30) % 360}));
        btn("✕", "Remove from the map", () => save(v.id, {lat: null, lng: null}), "secondary small danger");
      }
      row.onmouseenter = () => markers.get(v.id)?.getElement()?.classList.add("hover");
      row.onmouseleave = () => markers.get(v.id)?.getElement()?.classList.remove("hover");
      row.append(t, text, acts); list.append(row);
    }
  }
  function fit(target, list, animate = true) {
    const points = list.filter(located).map(v => [v.camera.lat, v.camera.lng]);
    if (points.length > 1) target.fitBounds(points, {padding: [70, 70], maxZoom: 18, animate});
    else if (points.length) target.setView(points[0], 17, {animate});
    else target.setView(DEMO_CENTRE, 15, {animate});
  }
  // Points of a route not yet shown, so the map can zoom to it (nearby cameras otherwise overlap).
  function pendingRoute() {
    if (!(lastScan?.route?.length > 1) || lastScan.routeShown) return null;
    const pts = lastScan.route.map(r => videosCache.find(v => v.id === r.video_id)).filter(v => v && located(v)).map(v => [v.camera.lat, v.camera.lng]);
    return pts.length > 1 ? pts : null;
  }

  window.showMap = function () {
    if (!window.L) { hint("The map library didn't load. Reload the page."); return; }
    if (!map) {
      // Set a view straight away: Leaflet only attaches markers and lines once the map has one.
      map = L.map("map-canvas", {zoomControl: false, worldCopyJump: true, maxZoom: 19}).setView(DEMO_CENTRE, 15);
      L.control.zoom({position: "bottomright"}).addTo(map);
      L.control.scale({position: "bottomright", imperial: false}).addTo(map);
      base = tiles(map);
      map.on("click", event => { if (placing) { const id = placing; placing = null; hint(""); save(id, {lat: event.latlng.lat, lng: event.latlng.lng}); } });
      render(); if (!pendingRoute()) fit(map, cameras(), false);
    } else render();
    setTimeout(() => {
      map.invalidateSize();
      const pts = pendingRoute();
      if (pts) { map.fitBounds(pts, {padding: [180, 180], maxZoom: 19, animate: false}); lastScan.routeShown = true; }
    }, 60);
  };
  document.querySelectorAll("#map-style button").forEach(b => {
    b.onclick = () => {
      style = b.dataset.style;
      document.querySelectorAll("#map-style button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      if (map) { base.remove(); base = tiles(map); }
    };
  });
  $("map-fit").onclick = () => map && fit(map, cameras());
  $("map-demo").onclick = async () => {
    const todo = cameras().filter(v => !located(v));
    if (!todo.length) { notice("Every camera already has a place. Drag a pin to move it, or turn its view cone with ↺ ↻."); return; }
    const centre = map ? map.getCenter() : L.latLng(DEMO_CENTRE);
    $("map-demo").disabled = true;
    try {
      // A small ring around the current view, so pins don't overlap. Demo positions: move them to the real spots.
      for (const [i, v] of todo.entries()) {
        const angle = 2 * Math.PI * i / todo.length;
        await post(`/api/videos/${v.id}/camera`, {lat: centre.lat + 0.0012 * Math.sin(angle), lng: centre.lng + 0.0016 * Math.cos(angle), heading: Math.round(angle * 180 / Math.PI + 180) % 360});
      }
      await library(); render(); if (map) fit(map, cameras());
      notice(`Placed ${todo.length} camera(s) as a demo layout. Drag each pin to its real location.`);
    } catch (error) { notice(error.message); } finally { $("map-demo").disabled = false; }
  };
  $("map-panel-toggle").onclick = () => {
    const panel = $("map-panel"); panel.classList.toggle("collapsed");
    const open = !panel.classList.contains("collapsed");
    $("map-panel-toggle").setAttribute("aria-expanded", String(open)); $("map-panel-toggle").textContent = open ? "Hide list" : "Show list";
  };
  window.addEventListener("tanya:theme", () => {
    if (map && style === "street") { base.remove(); base = tiles(map); }
    if (mini) { mini.base.remove(); mini.base = tiles(mini.map); }
  });

  // Scan progress on the map: pins pulse while checked, then turn green (likely), yellow (maybe) or grey.
  window.mapFx = {
    scanStart(plan, holder) {
      scanState.clear(); lastScan = null;
      if (mini) { mini.map.remove(); mini = null; }
      miniMarkers.clear();
      const list = plan.recordings.map(r => videosCache.find(v => v.id === r.video_id)).filter(v => v && located(v));
      if (!window.L || !list.length) return;
      holder.hidden = false;
      const m = L.map(holder, {zoomControl: false, attributionControl: true, dragging: true, scrollWheelZoom: false}).setView(DEMO_CENTRE, 15);
      mini = {map: m, base: tiles(m)};
      for (const v of list) miniMarkers.set(v.id, L.marker([v.camera.lat, v.camera.lng], {icon: pin(v, true), keyboard: false}).addTo(m));
      fit(m, list, false); setTimeout(() => { m.invalidateSize(); fit(m, list, false); }, 80);
    },
    scanUpdate(id, state) {
      scanState.set(id, state);
      const v = videosCache.find(x => x.id === id); if (!v) return;
      miniMarkers.get(id)?.setIcon(pin(v, true)); markers.get(id)?.setIcon(pin(v));
      if (map) renderHud();
    },
    scanFinish(summary) {
      lastScan = summary;
      if (summary.route) for (const s of summary.route) if (s.source) scanState.set(s.video_id, "hit");
      render();
    },
  };
})();
