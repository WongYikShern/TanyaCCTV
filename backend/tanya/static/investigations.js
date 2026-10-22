"use strict";
// Investigations: case list, evidence timeline, human decisions, report export.
// Uses helpers from dashboard.js ($, element, api, time, notice, openVideo). All text is set
// through textContent; nothing from the server or the user is inserted as HTML.
let activeCase = null;
// Stored values stay correct/wrong/unsure (reports and history use them); people see what they mean.
const decisionNames = {correct: "Relevant", wrong: "Not relevant", unsure: "Uncertain"};
const decisionHelp = {correct: "This clip shows what the investigation is looking for (human-confirmed).",
  wrong: "This clip does not show it.", unsure: "Cannot tell yet: keep it open for another look."};
const eventSourceNames = {provisional_review: "Annotated · reviewed by one person (provisional)",
  publisher_annotation: "Annotated (publisher, not reviewed here)", synthetic_script: "Scripted demo event",
  yolo_person: "YOLO person detection · model candidate"};
const sourceNames = {available: "Source available", renamed: "Source renamed", missing: "SOURCE MISSING", changed: "SOURCE CHANGED"};
const basisText = {
  absolute: "Ordered by camera time, using the recording start times you entered.",
  within_recording: "Ordered by recording, then by position in each recording. Enter recording start times below to order clips across cameras.",
  mixed: "Clips with a recording start time are ordered by camera time first; the others follow, by position in their recording.",
  empty: "No clips yet. On the Search page, choose this investigation under ‘Save clips to’, then press ‘Add to investigation’ on a result.",
};

function remember(id) { try { id ? localStorage.setItem("tanya.case", String(id)) : localStorage.removeItem("tanya.case"); } catch (e) { /* storage unavailable */ } }
function remembered() { try { return Number(localStorage.getItem("tanya.case")) || null; } catch (e) { return null; } }
function post(path, payload) {
  return api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload || {})});
}

async function loadInvestigations() {
  const {investigations} = await api("/api/investigations");
  const list = $("investigation-list"), select = $("save-to"), chosen = select.value;
  list.replaceChildren();
  select.replaceChildren(new Option("No investigation", ""));
  if (!investigations.length) list.append(element("div", "No investigations yet. Create one to start collecting clips.", "empty"));
  for (const inv of investigations) {
    const card = element("button", undefined, "case-card" + (activeCase && activeCase.id === inv.id ? " active" : ""));
    card.type = "button";
    card.append(element("strong", inv.title), element("span", `${inv.status === "open" ? "Open" : "Closed"} · ${plural(inv.evidence_count, "clip")} · ${inv.unreviewed_count} unreviewed`, "muted"));
    card.onclick = () => openCase(inv.id);
    list.append(card);
    if (inv.status === "open") select.append(new Option(inv.title, String(inv.id)));
  }
  if ([...select.options].some(o => o.value === chosen)) select.value = chosen;
}

async function openCase(id) {
  try {
    activeCase = await api(`/api/investigations/${id}`);
  } catch (error) {
    if (id === remembered()) remember(null);
    notice(error.message);
    return;
  }
  remember(id);
  renderCase();
  await loadInvestigations();
  if (activeCase.status === "open") $("save-to").value = String(id);
}

window.openInvestigation = id => openCase(id);
window.refreshInvestigation = async function () {
  await loadInvestigations();
  if (activeCase) { activeCase = await api(`/api/investigations/${activeCase.id}`); renderCase(); }
};

function renderCase() {
  const c = activeCase, open = c.status === "open";
  $("case").hidden = false; $("case-empty").hidden = true;
  $("case-title").textContent = c.title;
  $("case-description").textContent = c.description;
  $("case-status").textContent = open ? "OPEN INVESTIGATION" : "CLOSED · REOPEN TO MAKE CHANGES";
  $("case-close").textContent = open ? "Close" : "Reopen";
  $("case-rename").disabled = !open;
  renderQueries(c, open);
  renderClocks(c, open);
  $("case-basis").textContent = basisText[c.timeline_basis];
  const list = $("case-evidence");
  list.replaceChildren();
  for (const e of c.evidence) list.append(evidenceCard(e, open));
  if (c.removed_evidence.length) list.append(element("p", `${plural(c.removed_evidence.length, "clip")} removed; ${c.removed_evidence.length === 1 ? "it remains" : "they remain"} in the change history and the report.`, "muted"));
  $("case-history").open = false;
  $("case-history-items").replaceChildren();
}

function renderQueries(c, open) {
  const box = $("case-queries");
  box.replaceChildren();
  if (!c.queries.length) { box.append(element("p", "No saved searches yet.", "muted")); return; }
  for (const q of c.queries) {
    const row = element("div", undefined, "case-row");
    const filtered = q.settings && q.settings.filters ? " · with filters" : "";
    row.append(element("span", `“${q.query}” · ${q.search_mode === "visual" ? "with image check" : q.settings && q.settings.engine && q.settings.engine.startsWith("Preset") ? "event index" : "ranked"}${filtered} · last run ${q.last_run_at ? new Date(q.last_run_at).toLocaleString() : "never"} · ${q.last_result_count == null ? "? results" : plural(q.last_result_count, "result")}`));
    const run = element("button", "Run again", "secondary");
    run.type = "button"; run.disabled = !open;
    run.onclick = () => {
      $("query").value = q.query;
      // Saved searches come from the quick (ranked) search, so rerun them the same way.
      $("search-mode").value = "ranked"; $("more-options").open = true;
      if ($("visual-check").checked !== (q.search_mode === "visual")) $("visual-check").click();
      $("save-to").value = String(c.id);
      if (window.applySavedFilters) window.applySavedFilters(q.settings && q.settings.filters);
      updateControls();
      location.hash = "#search";
      notice(q.search_mode === "visual" ? "Tick the image-check approval, then search." : "Press search to run this saved query again.");
    };
    const remove = element("button", "Remove", "secondary danger");
    remove.type = "button"; remove.disabled = !open;
    remove.onclick = () => change(post(`/api/investigations/${c.id}/queries/${q.id}/remove`));
    row.append(run, remove);
    box.append(row);
  }
}

function renderClocks(c, open) {
  const box = $("case-clocks");
  box.replaceChildren();
  for (const r of c.recordings) {
    const form = element("form", undefined, "case-row clock");
    const id = `clock-${r.video_sha256.slice(0, 12)}`;
    const label = element("label", `${r.filename} recording started at (camera local time)`);
    label.htmlFor = id;
    const input = element("input"); input.type = "datetime-local"; input.step = "1"; input.id = id; input.disabled = !open;
    if (r.recorded_start) input.value = r.recorded_start;
    const save = element("button", "Save time", "secondary"); save.disabled = !open;
    form.append(label, input, save);
    form.onsubmit = event => { event.preventDefault(); change(post(`/api/investigations/${c.id}/clock`, {video_sha256: r.video_sha256, recorded_start: input.value})); };
    box.append(form);
  }
}

function evidenceCard(e, open) {
  const card = element("article", undefined, "result evidence-item");
  if (e.thumbnail_url) { const img = element("img"); img.src = e.thumbnail_url; img.alt = `Frame from ${e.video_filename}`; card.append(img); }
  else card.append(element("div", e.source_status === "missing" ? "Source missing" : "No frame", "video-placeholder small-placeholder"));
  const info = element("div");
  const category = e.decision ? `Human review: ${decisionNames[e.decision]}` : (e.event && e.event.source === "yolo_person" ? "Model candidate · not reviewed" : "Unreviewed candidate");
  info.append(element("h3", e.current_filename && e.current_filename !== e.video_filename ? `${e.video_filename} (now ${e.current_filename})` : e.video_filename));
  info.append(element("span", category, "badge" + (e.decision ? "" : " pending")), element("span", sourceNames[e.source_status], "badge" + (e.source_status === "missing" || e.source_status === "changed" ? " failed" : "")));
  info.append(element("p", `${time(e.start_sec)}–${time(e.end_sec)} in the recording` + (e.absolute_start ? ` · camera time ${e.absolute_start.replace("T", " ").slice(0, 19)}` : "")));
  if (e.event) {
    const ev = element("div", undefined, "evidence-event");
    ev.append(element("span", eventSourceNames[e.event.source] || e.event.source, "badge " + (e.event.source === "yolo_person" ? "pending" : "info")));
    ev.append(element("p", `Label: ${e.event.label} · status: ${String(e.event.verification || "unknown").replace(/_/g, " ")}`));
    if (e.event.provenance) ev.append(element("p", e.event.provenance, "muted small-note"));
    const d = e.event.detector;
    if (d) ev.append(element("p", `Detector confidence up to ${d.max_conf.toFixed(2)} (mean ${d.mean_conf.toFixed(2)}) over ${d.frames} frames; model ${d.weights || "unknown"}, ${d.imgsz || "?"} px. A person-presence candidate, not an action.`, "muted small-note"));
    info.append(ev);
  }
  const how = e.search_mode === "index" ? `Found in the preset offline event index by “${e.query}” (keyword match; no AI, no ranking)` : e.search_mode === "manual" ? "Chosen manually in the video player (not a search result)" : e.search_mode === "scan" ? `Found by a direct footage scan for “${e.query}” (sampled images checked in time order; not a similarity ranking)` + (e.visual_verdict ? ` · AI image check: ${e.visual_verdict.replace("_", " ")} (unverified)` : "") : `Found by “${e.query}” (${e.search_mode === "visual" ? "with image check" : "ranked"}${e.rank ? `, rank ${e.rank}` : ""}${e.best_score !== null ? `, ranking score ${e.best_score.toFixed(3)} — not a probability` : ""})` + (e.visual_verdict ? ` · AI image check: ${e.visual_verdict.replace("_", " ")} (unverified)` : "");
  info.append(element("p", how, "muted"));
  if (e.source_status === "changed") info.append(element("p", "This recording's file has changed since the clip was added (its size differs). It may no longer be the referenced footage; re-index it, and check the exported report's content verification.", "warning"));
  if (e.source_status === "missing") info.append(element("p", `The recording with content hash ${e.video_sha256.slice(0, 16)}… is no longer in the library. The reference is kept; restore the original file to review it.`, "warning"));
  if (e.video_url) {
    const watch = element("button", "Open footage →"); watch.type = "button";
    watch.onclick = () => openVideo(e.current_video_id, e.current_filename || e.video_filename, e.video_url, e.start_sec, e.end_sec);
    info.append(watch);
  }
  const review = element("div", undefined, "review-feedback");
  review.append(element("p", "Your decision (recorded in the change history; earlier decisions are kept):"));
  for (const [value, label] of Object.entries(decisionNames)) {
    const b = element("button", label, "secondary"); b.type = "button"; b.disabled = !open; b.title = decisionHelp[value];
    b.setAttribute("aria-pressed", String(e.decision === value));
    b.onclick = () => change(post(`/api/investigations/${activeCase.id}/evidence/${e.id}/review`, {decision: value}), `Saved: ${label}.`);
    review.append(b);
  }
  const noteId = `note-${e.id}`;
  const noteLabel = element("label", "Reviewer note"); noteLabel.htmlFor = noteId; noteLabel.className = "note-label";
  const note = element("textarea"); note.id = noteId; note.maxLength = 2000; note.rows = 2; note.value = e.note; note.disabled = !open;
  const saveNote = element("button", "Save note", "secondary"); saveNote.type = "button"; saveNote.disabled = !open;
  saveNote.onclick = () => change(post(`/api/investigations/${activeCase.id}/evidence/${e.id}/review`, {note: note.value}), "Note saved.");
  const remove = element("button", "Remove from investigation", "secondary danger"); remove.type = "button"; remove.disabled = !open;
  remove.onclick = () => {
    const reason = window.prompt("Why remove this clip? (kept in the change history)", "");
    if (reason !== null) change(post(`/api/investigations/${activeCase.id}/evidence/${e.id}/remove`, {reason}), "Clip removed.");
  };
  review.append(noteLabel, note, saveNote, remove);
  if (e.reviewed_at) review.append(element("span", `Decision saved ${new Date(e.reviewed_at).toLocaleString()}.`, "muted"));
  const decisions = (e.history || []).filter(h => h.action !== "note_changed");
  if (decisions.length) review.append(element("p", "History: not reviewed → " + decisions.map(h => `${decisionNames[h.to] || h.to} (${new Date(h.at).toLocaleString()})`).join(" → "), "muted small-note"));
  const notes = (e.history || []).filter(h => h.action === "note_changed").length;
  if (notes) review.append(element("p", `The note was changed ${plural(notes, "time")}; earlier versions are in the change history.`, "muted small-note"));
  info.append(review);
  card.append(info);
  return card;
}

async function change(request, message) {
  try {
    activeCase = await request;
    renderCase();
    await loadInvestigations();
    if (activeCase.warning) notice(activeCase.warning);
    else if (message) notice(message);
  } catch (error) { notice(error.message); }
}

// A direct footage scan window (hit.scan_window) is not a similarity ranking: store it as "scan" with no rank.
window.investigationClipButton = function (hit, query, visual, rank) {
  const mode = hit.event ? "index" : hit.scan_window ? "scan" : (visual ? "visual" : "ranked");
  const button = element("button", "Add to investigation", "secondary");
  button.type = "button";
  button.onclick = async () => {
    const id = $("save-to").value;
    if (!id) { notice("First choose an investigation under ‘Save clips to’, next to the search box. Create one on the Investigations page if you don't have one."); $("save-to").focus(); return; }
    button.disabled = true;
    try {
      activeCase = await post(`/api/investigations/${id}/evidence`, {
        video_id: hit.video_id, start_sec: hit.start_sec, end_sec: hit.end_sec, query,
        search_mode: mode, rank: mode === "scan" || mode === "index" ? null : (rank || null),
        best_score: mode === "scan" || mode === "index" ? null : hit.best_score,
        score_above_median: mode === "scan" || mode === "index" ? null : hit.best_score_above_median, thumbnail: hit.thumbnail,
        ...(mode === "index" ? {event_source: hit.event.source} : {}),
        visual_verdict: hit.visual_review ? hit.visual_review.verdict : null,
        visual_reason: hit.visual_review ? hit.visual_review.reason : null});
      button.textContent = "Added ✓";
      renderCase();
      await loadInvestigations();
      notice(`Added ${hit.filename} ${time(hit.start_sec)}–${time(hit.end_sec)} to “${activeCase.title}”. It stays unverified until you review it.`);
    } catch (error) { button.disabled = false; notice(error.message); }
  };
  return button;
};

async function downloadReport(format) {
  const buttons = [$("case-report-html"), $("case-report-json")], frames = format === "html" && $("case-report-frames").checked;
  $("case-export").open = false;
  buttons.forEach(b => { b.disabled = true; });
  notice(format === "html" ? "Preparing the report… (checking each source video's content hash)" : "Preparing the data export…");
  try {
    const response = await serverFetch(`/api/investigations/${activeCase.id}/report`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({format, include_frames: frames})});
    if (!response.ok) throw new Error((await response.json()).error || "The report could not be created.");
    const url = URL.createObjectURL(await response.blob());
    const link = element("a"); link.href = url; link.download = `investigation-${activeCase.id}-report.${format}`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    notice(format === "json" ? "Investigation data downloaded." : frames ? "Report downloaded. It contains frame images: share it only with authorised people." : "Report downloaded.");
  } catch (error) { notice(error.message); }
  finally { buttons.forEach(b => { b.disabled = false; }); }
}

$("new-investigation").onsubmit = async event => {
  event.preventDefault();
  try {
    activeCase = await post("/api/investigations", {title: $("new-title").value});
    event.target.reset();
    renderCase(); remember(activeCase.id);
    await loadInvestigations();
    $("save-to").value = String(activeCase.id);
    notice(`Created “${activeCase.title}”. Searches and clips will now be saved to it.`);
  } catch (error) { notice(error.message); }
};
$("case-rename").onclick = () => { $("rename-form").hidden = false; $("rename-title").value = activeCase.title; $("rename-title").focus(); };
$("rename-cancel").onclick = () => { $("rename-form").hidden = true; };
$("rename-form").onsubmit = event => { event.preventDefault(); $("rename-form").hidden = true; change(post(`/api/investigations/${activeCase.id}`, {title: $("rename-title").value}), "Title saved."); };
$("case-close").onclick = () => change(post(`/api/investigations/${activeCase.id}/status`, {status: activeCase.status === "open" ? "closed" : "open"}));
$("case-report-html").onclick = () => downloadReport("html");
// Close the export menu when clicking elsewhere or pressing Escape.
document.addEventListener("click", event => { if ($("case-export").open && !$("case-export").contains(event.target)) $("case-export").open = false; });
document.addEventListener("keydown", event => { if (event.key === "Escape" && $("case-export").open) { $("case-export").open = false; $("case-export").querySelector("summary").focus(); } });
$("case-report-json").onclick = () => downloadReport("json");
$("case-history").addEventListener("toggle", async () => {
  if (!$("case-history").open || !activeCase) return;
  try {
    const {audit} = await api(`/api/investigations/${activeCase.id}/audit`);
    const box = $("case-history-items");
    box.replaceChildren(...audit.map(a => element("p", `${new Date(a.at).toLocaleString()} — ${a.action.replaceAll("_", " ")}${a.detail.from !== undefined || a.detail.to !== undefined ? `: ${a.detail.from ?? "none"} → ${a.detail.to ?? "none"}` : ""}`, "muted")));
  } catch (error) { notice(error.message); }
});

loadInvestigations().then(() => { const id = remembered(); if (id) openCase(id); }).catch(error => notice(error.message));
