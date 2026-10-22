"use strict";
// Camera map ("global view"). Locations are set by people: drag a pin, or choose a camera and click the map.
// Nothing is inferred from footage. Map pictures come from Esri's public tile service (no key); only tile
// requests go to it. Uses helpers from dashboard.js; all names are set with textContent.
(() => {
  const DEMO_CENTRE = [3.1478, 101.7130], DEMO_ZOOM = 17;   // Kuala Lumpur city centre, used only for demo placement
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  const tile = name => `${ESRI}${name}/MapServer/tile/{z}/{y}/{x}`;
  // [url, deepest zoom the service draws]; the dark map is a base plus a label layer.
  const TILES = {
    dark: [[tile("Canvas/World_Dark_Gray_Base"), 16], [tile("Canvas/World_Dark_Gray_Reference"), 16]],
    light: [[tile("World_Street_Map"), 19]],
    satellite: [[tile("World_Imagery"), 19]],
  };
  const ATTRIBUTION = 'Tiles &copy; <a href="https://www.esri.com/">Esri</a> and its data providers';
  let map = null, base = null, satellite = false, placing = null, mini = null;
  const markers = new Map(), miniMarkers = new Map(), scanState = new Map();
  let lastScan = null;

  const located = v => Number.isFinite(v.camera?.lat) && Number.isFinite(v.camera?.lng);
  const cameras = () => videosCache.filter(v => v.status === "done");
  function tiles(target) {
    const layers = TILES[satellite ? "satellite" : (document.documentElement.dataset.theme === "light" ? "light" : "dark")];
    return L.layerGroup(layers.map(([url, native]) => L.tileLayer(url, {attribution: ATTRIBUTION, maxZoom: 19, maxNativeZoom: native}))).addTo(target);
  }
  function pin(v) {
    const state = scanState.get(v.id) || "";
    const el = element("div", undefined, "cam-pin " + state);
    el.append(element("span", undefined, "cam-pin-dot"), element("span", displayName(v.filename), "cam-pin-label"));
    return L.divIcon({html: el, className: "cam-pin-wrap", iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -12]});
  }
  function popup(v) {
    const box = element("div", undefined, "cam-pop");
    if (v.thumbnail_url) { const img = element("img"); img.src = v.thumbnail_url; img.alt = ""; box.append(img); }
    box.append(element("strong", displayName(v.filename)));
    if (v.camera?.place) box.append(element("span", v.camera.place, "muted"));
    const found = lastScan?.byVideo[v.id];
    if (found?.hits.length) {
      box.append(element("span", `“${lastScan.query}”: ${found.likely} likely, ${found.maybe} maybe`, "cam-pop-hit"));
      const best = found.hits.find(h => h.likely) || found.hits[0];
      const play = element("button", `Play ${time(best.start_sec)}–${time(best.end_sec)}`); play.type = "button"; play.prepend(icon("play"));
      play.onclick = () => openVideo(v.id, v.filename, v.video_url, best.start_sec, best.end_sec); box.append(play);
    } else {
      const play = element("button", "Open camera", "secondary"); play.type = "button"; play.onclick = () => openVideo(v.id); box.append(play);
    }
    return box;
  }
  async function save(id, latlng) {
    try { await post(`/api/videos/${id}/camera`, latlng ? {lat: latlng.lat, lng: latlng.lng} : {lat: null, lng: null}); await library(); render(); }
    catch (error) { notice(error.message); }
  }
  function hint(text) { $("map-hint").textContent = text || ""; $("map-canvas").classList.toggle("placing", !!placing); }

  function render() {
    if (!map) return;
    markers.forEach(m => m.remove()); markers.clear();
    for (const v of cameras().filter(located)) {
      const m = L.marker([v.camera.lat, v.camera.lng], {icon: pin(v), draggable: true, keyboard: true, title: displayName(v.filename)});
      m.bindPopup(() => popup(v), {className: "cam-popup", minWidth: 220});
      m.on("dragend", () => save(v.id, m.getLatLng()));
      m.addTo(map); markers.set(v.id, m);
    }
    const list = $("map-list"); list.replaceChildren();
    if (!cameras().length) list.append(element("p", "Add footage first, then place each camera here.", "empty"));
    for (const v of cameras()) {
      const row = element("div", undefined, "map-row" + (placing === v.id ? " active" : ""));
      const t = element("img"); t.alt = ""; if (v.thumbnail_url) t.src = v.thumbnail_url;
      const text = element("div"); text.append(element("strong", displayName(v.filename)), element("span", located(v) ? (v.camera.place || "On the map") : "Not on the map yet", "muted"));
      const state = scanState.get(v.id); if (state) text.append(element("span", {hit: "Match found", maybe: "Maybe", clear: "No match", checking: "Checking…", skipped: "Not checked"}[state] || "", "map-state " + state));
      const acts = element("div", undefined, "map-row-acts");
      const place = element("button", located(v) ? "Move" : "Place", "secondary small"); place.type = "button";
      place.onclick = () => { placing = placing === v.id ? null : v.id; hint(placing ? `Click on the map where “${displayName(v.filename)}” is.` : ""); render(); };
      acts.append(place);
      if (located(v)) {
        const go = element("button", "Show", "secondary small"); go.type = "button";
        go.onclick = () => { map.setView([v.camera.lat, v.camera.lng], Math.max(map.getZoom(), 17)); markers.get(v.id)?.openPopup(); };
        const clear = element("button", "Remove", "secondary small danger"); clear.type = "button"; clear.onclick = () => save(v.id, null);
        acts.append(go, clear);
      }
      row.append(t, text, acts); list.append(row);
    }
    const banner = $("map-scan");
    banner.hidden = !lastScan;
    if (lastScan) {
      const found = Object.entries(lastScan.byVideo).filter(([, e]) => e.likely || e.maybe);
      banner.textContent = `Latest search “${lastScan.query}”: ` + (found.length
        ? found.map(([id, e]) => `${displayName(videosCache.find(v => v.id === Number(id))?.filename)} (${e.likely ? e.likely + " likely" : e.maybe + " maybe"})`).join(", ")
        : "no matching moments") + (lastScan.error ? " · search did not finish" : "");
    }
  }
  function fit(target, list) {
    const points = list.filter(located).map(v => [v.camera.lat, v.camera.lng]);
    if (points.length > 1) target.fitBounds(points, {padding: [50, 50], maxZoom: 18});
    else if (points.length) target.setView(points[0], 17);
    else target.setView(DEMO_CENTRE, 15);
  }

  window.showMap = function () {
    if (!window.L) { hint("The map library didn't load. Reload the page."); return; }
    if (!map) {
      map = L.map("map-canvas", {zoomControl: true, worldCopyJump: true, maxZoom: 19});
      base = tiles(map);
      map.on("click", event => { if (placing) { const id = placing; placing = null; hint(""); save(id, event.latlng); } });
      render(); fit(map, cameras());
    } else render();
    setTimeout(() => map.invalidateSize(), 60);
  };
  $("map-layer").onclick = () => {
    satellite = !satellite; $("map-layer").textContent = satellite ? "Street map" : "Satellite view";
    if (map) { base.remove(); base = tiles(map); }
  };
  $("map-demo").onclick = async () => {
    const todo = cameras().filter(v => !located(v));
    if (!todo.length) { notice("Every camera already has a place. Drag a pin to move it."); return; }
    const centre = map ? map.getCenter() : L.latLng(DEMO_CENTRE);
    $("map-demo").disabled = true;
    try {
      // A small ring around the current view, so pins don't overlap. Demo positions: move them to the real spots.
      for (const [i, v] of todo.entries()) {
        const angle = 2 * Math.PI * i / todo.length;
        await post(`/api/videos/${v.id}/camera`, {lat: centre.lat + 0.0012 * Math.sin(angle), lng: centre.lng + 0.0016 * Math.cos(angle)});
      }
      await library(); render(); if (map) fit(map, cameras());
      notice(`Placed ${todo.length} camera(s) as a demo layout. Drag each pin to its real location.`);
    } catch (error) { notice(error.message); } finally { $("map-demo").disabled = false; }
  };
  window.addEventListener("tanya:theme", () => {
    if (map && !satellite) { base.remove(); base = tiles(map); }
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
      const m = L.map(holder, {zoomControl: false, attributionControl: true, dragging: true, scrollWheelZoom: false});
      mini = {map: m, base: tiles(m)};
      for (const v of list) miniMarkers.set(v.id, L.marker([v.camera.lat, v.camera.lng], {icon: pin(v), keyboard: false}).addTo(m));
      fit(m, list); setTimeout(() => { m.invalidateSize(); fit(m, list); }, 80);
    },
    scanUpdate(id, state) {
      scanState.set(id, state);
      const v = videosCache.find(x => x.id === id); if (!v) return;
      miniMarkers.get(id)?.setIcon(pin(v)); markers.get(id)?.setIcon(pin(v));
    },
    scanFinish(summary) { lastScan = summary; render(); },
  };
})();
