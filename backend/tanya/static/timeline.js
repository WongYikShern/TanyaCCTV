"use strict";
// Player event timeline (indexed labels + YOLO person-presence candidates) and the event-index search filters.
// Uses dashboard.js globals ($, element, time, seek, api, watchToken, videosCache, activeVideo, connection).
// All text is inserted with textContent. Positions are set through the CSSOM (allowed by the page's CSP).

// ---------------------------------------------------------------- event timeline
const TL_SOURCES = {
  provisional_review: {name: "Annotated · reviewed by one person (provisional)", cls: "ev-provisional"},
  publisher_annotation: {name: "Annotated (publisher, not reviewed here)", cls: "ev-publisher"},
  synthetic_script: {name: "Scripted demo event (known by construction)", cls: "ev-scripted"},
  yolo_person: {name: "YOLO person detection · unreviewed candidate", cls: "ev-yolo"},
};
const PEOPLE_STATUS = {
  new: "YOLO person detections: newly generated on this computer.",
  cached: "YOLO person detections: cached result for this exact video and the configured model.",
  cached_unverified: "YOLO person detections: cached result for this exact video; the model file's hash was not recorded, so the model cannot be verified.",
  stale: "YOLO person detections: made with different model weights (stale). They are not shown on the timeline; run person detection again to refresh them.",
};
const MAX_EVENT_ROWS = 4;
let timelineState = {events: [], people: null, duration: 0, indexAvailable: false, videoId: null};

// Greedy row packing: overlapping intervals go to separate rows, so none hides another.
function packRows(items) {
  const rows = [];
  for (const item of [...items].sort((a, b) => a.start_sec - b.start_sec || b.end_sec - a.end_sec)) {
    const row = rows.find(r => r[r.length - 1].end_sec <= item.start_sec);
    if (row) row.push(item); else rows.push([item]);
  }
  return rows;
}
function pct(seconds) { const d = timelineState.duration || 1; return Math.max(0, Math.min(100, seconds / d * 100)); }
function timelineJump(t, button) {
  seek(t);
  document.querySelectorAll("#evt-lanes .evt-bar.current, #evt-list button.current").forEach(b => b.classList.remove("current"));
  if (button) button.classList.add("current");
}
function barFor(item) {
  const src = TL_SOURCES[item.source], bar = element("button", undefined, `evt-bar ${src.cls}`);
  bar.type = "button";
  const range = `${time(item.start_sec)}–${time(item.end_sec)}`;
  bar.title = `${item.label} · ${range} · ${src.name}`;
  bar.setAttribute("aria-label", `${item.label}, ${range}, ${src.name}. Jump to ${time(item.start_sec)}.`);
  bar.style.left = `${pct(item.start_sec)}%`;
  bar.style.width = `${Math.max(pct(item.end_sec) - pct(item.start_sec), 0.8)}%`;
  bar.onclick = event => { event.stopPropagation(); timelineJump(item.start_sec, bar); };
  return bar;
}
function lane(title, rows, hiddenCount) {
  const box = element("div", undefined, "evt-lane");
  box.append(element("span", title, "evt-lane-title"));
  for (const row of rows) { const r = element("div", undefined, "evt-row"); row.forEach(item => r.append(barFor(item))); box.append(r); }
  if (hiddenCount) box.append(element("span", `+${hiddenCount} more overlapping event(s): see the list below.`, "muted small-note"));
  return box;
}
function personItems() {
  const p = timelineState.people;
  if (!p || p.stale) return [];
  return p.intervals.map(iv => ({...iv, label: "Person detected (candidate)", source: "yolo_person"}));
}
function renderTimeline() {
  const card = $("event-timeline-card");
  if (!card) return;
  const {events, indexAvailable, duration} = timelineState, people = personItems();
  const lanes = $("evt-lanes"), list = $("evt-list"), legend = $("evt-legend");
  lanes.replaceChildren(); list.replaceChildren(); legend.replaceChildren();
  $("evt-axis-mid").textContent = duration ? time(duration / 2) : ""; $("evt-axis-end").textContent = duration ? time(duration) : "";
  const used = new Set([...events.map(e => e.source), ...people.map(() => "yolo_person")]);
  for (const [key, src] of Object.entries(TL_SOURCES)) if (used.has(key)) legend.append(element("span", src.name, `evt-key ${src.cls}`));
  const rows = packRows(events), shown = rows.slice(0, MAX_EVENT_ROWS);
  const hidden = rows.slice(MAX_EVENT_ROWS).reduce((n, r) => n + r.length, 0);
  if (events.length) lanes.append(lane("Event labels", shown, hidden));
  if (people.length) lanes.append(lane("Person detection (YOLO)", packRows(people).slice(0, 2), Math.max(0, packRows(people).length - 2)));
  const status = [];
  if (!indexAvailable) status.push("No event labels: the preset event index is loaded only in the offline demo.");
  else if (!events.length) status.push("No indexed events for this recording. That does not mean nothing happened here.");
  const p = timelineState.people;
  if (p) status.push(PEOPLE_STATUS[p.status] || "");
  if (p && !p.stale && !p.intervals.length) status.push(`No person detected at confidence ≥ ${p.presence_conf}.`);
  if (!p && timelineState.peopleAvailable) status.push("No person detections yet: use “Find people” beside the player to run YOLO on this video.");
  if (!p && !timelineState.peopleAvailable) status.push("YOLO person detection is not set up on this computer.");
  $("evt-status").textContent = status.filter(Boolean).join(" ");
  $("evt-track").hidden = !events.length && !people.length;
  $("evt-hint").hidden = !events.length && !people.length;
  // Accessible, scrollable list of everything on the bar (also the fallback for very dense timelines).
  for (const item of [...events, ...people].sort((a, b) => a.start_sec - b.start_sec)) {
    const src = TL_SOURCES[item.source], li = element("li");
    const jump = element("button", undefined, "evt-item"); jump.type = "button";
    jump.append(element("span", `${time(item.start_sec)}–${time(item.end_sec)}`, "evt-time"), element("strong", item.label),
                element("span", src.name, `evt-key ${src.cls}`));
    if (item.source === "yolo_person") {
      jump.append(element("span", `Detector confidence up to ${item.max_conf.toFixed(2)} (mean ${item.mean_conf.toFixed(2)}) over ${item.frames} frames; up to ${item.max_people} person box(es) in one frame. Not an action or incident.`, "muted"));
    } else if (item.status_label) jump.append(element("span", item.status_label, "muted"));
    jump.onclick = () => timelineJump(item.start_sec, jump);
    li.append(jump);
    if (item.peak) {
      const peak = element("button", `Strongest box at ${time(item.peak.t)} (frame ${item.peak.frame}, pixels ${item.peak.box.join(", ")})`, "secondary small");
      peak.type = "button"; peak.onclick = () => timelineJump(item.peak.t, peak); li.append(peak);
    }
    list.append(li);
  }
  updatePlayhead();
}
function updatePlayhead() {
  const head = $("evt-playhead");
  if (!head || !timelineState.duration) return;
  // Rows sit inside the track's 10 px padding, so the playhead uses the same inner width.
  head.style.left = `calc(10px + (100% - 20px) * ${pct(currentMoment || 0) / 100})`;
}
window.updatePlayhead = updatePlayhead;
window.setTimelinePeople = (data) => { timelineState.people = data?.result || null; timelineState.peopleAvailable = !!data?.available; renderTimeline(); };
window.loadEventTimeline = async (id, myToken) => {
  const video = videosCache.find(v => v.id === id);
  timelineState = {events: [], people: timelineState.videoId === id ? timelineState.people : null, duration: video?.duration_sec || 0,
                   indexAvailable: false, videoId: id, peopleAvailable: timelineState.peopleAvailable};
  renderTimeline();
  try {
    const data = await api(`/api/videos/${id}/events`);
    if (myToken !== watchToken) return;
    timelineState.events = data.events; timelineState.indexAvailable = data.index_available;
    timelineState.duration = data.duration_sec || timelineState.duration;
  } catch (error) { if (myToken === watchToken) $("evt-status").textContent = error.message; return; }
  renderTimeline();
};
// Clicking the bar itself (not an event) seeks proportionally.
$("evt-track").addEventListener("click", event => {
  if (event.target.closest(".evt-bar") || !timelineState.duration) return;
  const rect = $("evt-track").getBoundingClientRect();
  const inner = rect.width - 20;   // same 10 px padding as the rows
  timelineJump(Math.max(0, Math.min(1, (event.clientX - rect.left - 10) / inner)) * timelineState.duration);
});

// ---------------------------------------------------------------- search filters (event index only)
let filterOptions = null;
function checkChips(box, options, name) {
  box.replaceChildren();
  for (const o of options) {
    const label = element("label", undefined, "check chip-check"), input = element("input");
    input.type = "checkbox"; input.value = o.value; input.name = name; input.onchange = updateFilterCount;
    label.append(input, element("span", o.label)); box.append(label);
  }
  if (!options.length) box.append(element("span", "None in this library", "muted small-note"));
}
function checked(id) { return [...$(id).querySelectorAll("input:checked")].map(i => i.value); }
function numberOrNull(id) { const v = $(id).value.trim(); return v === "" ? null : Number(v); }
window.searchFilters = () => {
  if (!filterOptions) return null;
  const f = {event_types: checked("f-types"), sources: checked("f-sources"), statuses: checked("f-statuses"),
             video_ids: $("f-recording").value ? [Number($("f-recording").value)] : [],
             start_sec: numberOrNull("f-start"), end_sec: numberOrNull("f-end"), min_yolo_conf: numberOrNull("f-minconf")};
  const active = f.event_types.length || f.sources.length || f.statuses.length || f.video_ids.length
    || f.start_sec !== null || f.end_sec !== null || f.min_yolo_conf !== null;
  return active ? f : null;
};
function describeFilters(f) {
  if (!f) return [];
  const name = (list, value) => (list.find(o => o.value === value) || {label: value}).label;
  const out = [];
  if (f.event_types?.length) out.push("Event: " + f.event_types.map(v => name(filterOptions.event_types, v)).join(", "));
  if (f.sources?.length) out.push("Source: " + f.sources.map(v => name(filterOptions.sources, v)).join(", "));
  if (f.statuses?.length) out.push("Status: " + f.statuses.map(v => name(filterOptions.statuses, v)).join(", "));
  if (f.video_ids?.length) out.push("Recording: " + f.video_ids.map(id => filterOptions.recordings.find(r => r.id === id)?.filename || `#${id}`).join(", "));
  if (f.start_sec !== null || f.end_sec !== null) out.push(`Time: ${f.start_sec ?? 0} s – ${f.end_sec ?? "end"}${f.end_sec !== null ? " s" : ""}`);
  if (f.min_yolo_conf !== null) out.push(`YOLO confidence ≥ ${f.min_yolo_conf}`);
  return out;
}
function updateFilterCount() {
  const f = window.searchFilters(), n = describeFilters(f).length;
  $("filter-count").hidden = !n; $("filter-count").textContent = n ? `${n} active` : "";
  $("query").required = !f;   // with filters, an empty box lists everything that passes them
}
window.filterSummary = (applied) => {
  const parts = describeFilters(applied && Object.values(applied).some(v => (Array.isArray(v) ? v.length : v !== null)) ? applied : null);
  if (!parts.length) return null;
  const box = element("div", undefined, "active-filters");
  box.append(element("strong", "Active filters:"));
  parts.forEach(p => box.append(element("span", p, "pill-soft")));
  const clear = element("button", "Clear filters", "secondary small"); clear.type = "button";
  clear.onclick = () => { clearFilters(); notice("Filters cleared. Search again to see all matching events."); };
  box.append(clear);
  return box;
};
function clearFilters() {
  document.querySelectorAll("#filter-panel input[type=checkbox]").forEach(i => { i.checked = false; });
  for (const id of ["f-start", "f-end", "f-minconf"]) $(id).value = "";
  $("f-recording").value = "";
  updateFilterCount();
}
window.applySavedFilters = (f) => {
  clearFilters();
  if (!f || !filterOptions) return;
  for (const [id, values] of [["f-types", f.event_types], ["f-sources", f.sources], ["f-statuses", f.statuses]])
    $(id).querySelectorAll("input").forEach(i => { i.checked = (values || []).includes(i.value); });
  $("f-recording").value = f.video_ids?.length ? String(f.video_ids[0]) : "";
  $("f-start").value = f.start_sec ?? ""; $("f-end").value = f.end_sec ?? ""; $("f-minconf").value = f.min_yolo_conf ?? "";
  $("filter-panel").open = true; updateFilterCount();
};
window.loadFilterOptions = async () => {
  if (connection?.demo_mode !== "event_index") { $("filter-panel").hidden = true; return; }
  try { filterOptions = await api("/api/search/filters"); } catch (e) { $("filter-panel").hidden = true; return; }
  if (!filterOptions.available) { filterOptions = null; $("filter-panel").hidden = true; return; }
  checkChips($("f-types"), filterOptions.event_types, "event_types");
  checkChips($("f-sources"), filterOptions.sources, "sources");
  checkChips($("f-statuses"), filterOptions.statuses, "statuses");
  const sel = $("f-recording"); sel.replaceChildren(new Option("All recordings", ""));
  for (const r of filterOptions.recordings) sel.append(new Option(displayName(r.filename) + (r.views.length ? ` (${r.views.join(", ")} view)` : ""), String(r.id)));
  $("f-minconf-label").hidden = !filterOptions.yolo_available;
  $("filter-panel").hidden = false; updateFilterCount();
};
for (const id of ["f-recording", "f-start", "f-end", "f-minconf"]) $(id).addEventListener("input", updateFilterCount);
$("filter-clear").onclick = () => { clearFilters(); notice("Filters cleared."); };
