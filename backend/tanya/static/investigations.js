"use strict";
// Investigations: case list, evidence timeline, human decisions, report export.
// Uses helpers from dashboard.js ($, element, api, time, notice, openVideo). All text is set
// through textContent; nothing from the server or the user is inserted as HTML.
let activeCase = null;
const decisionNames = {correct: "Correct", wrong: "Wrong", unsure: "Unsure"};
const sourceNames = {available: "Source available", renamed: "Source renamed", missing: "SOURCE MISSING"};
const basisText = {
  absolute: "Ordered by camera time, using the recording start times you entered.",
  within_recording: "Ordered by recording, then by position in each recording. Enter recording start times below to order clips across cameras.",
  mixed: "Clips with a recording start time are ordered by camera time first; the others follow, by position in their recording.",
  empty: "No clips yet. Search with this investigation selected under ‘Save searches and clips to’, then use ‘Add to investigation’.",
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
    card.append(element("strong", inv.title), element("span", `${inv.status === "open" ? "Open" : "Closed"} · ${inv.evidence_count} clip(s) · ${inv.unreviewed_count} unreviewed`, "muted"));
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

window.refreshInvestigation = async function () {
  await loadInvestigations();
  if (activeCase) { activeCase = await api(`/api/investigations/${activeCase.id}`); renderCase(); }
};

function renderCase() {
  const c = activeCase, open = c.status === "open";
  $("case").hidden = false;
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
  if (c.removed_evidence.length) list.append(element("p", `${c.removed_evidence.length} clip(s) removed; they remain in the change history and the report.`, "muted"));
  $("case-history").open = false;
  $("case-history-items").replaceChildren();
}

function renderQueries(c, open) {
  const box = $("case-queries");
  box.replaceChildren();
  if (!c.queries.length) { box.append(element("p", "No saved searches yet.", "muted")); return; }
  for (const q of c.queries) {
    const row = element("div", undefined, "case-row");
    row.append(element("span", `“${q.query}” · ${q.search_mode === "visual" ? "with image check" : "ranked"} · last run ${q.last_run_at ? new Date(q.last_run_at).toLocaleString() : "never"} · ${q.last_result_count ?? "?"} result(s)`));
    const run = element("button", "Run again", "secondary");
    run.type = "button"; run.disabled = !open;
    run.onclick = () => {
      $("query").value = q.query;
      if ($("visual-check").checked !== (q.search_mode === "visual")) $("visual-check").click();
      $("save-to").value = String(c.id);
      updateControls();
      $("search").scrollIntoView({behavior: "smooth"});
      notice(q.search_mode === "visual" ? "Tick the image-check approval, then search." : "Press search to run this saved query again.");
    };
    const remove = element("button", "Remove", "secondary");
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
  const category = e.decision ? `Human review: ${decisionNames[e.decision]}` : "Unreviewed candidate";
  info.append(element("h3", e.current_filename && e.current_filename !== e.video_filename ? `${e.video_filename} (now ${e.current_filename})` : e.video_filename));
  info.append(element("span", category, "badge" + (e.decision ? "" : " pending")), element("span", sourceNames[e.source_status], "badge" + (e.source_status === "missing" ? " failed" : "")));
  info.append(element("p", `${time(e.start_sec)}–${time(e.end_sec)} in the recording` + (e.absolute_start ? ` · camera time ${e.absolute_start.replace("T", " ").slice(0, 19)}` : "")));
  const how = `Found by “${e.query}” (${e.search_mode === "visual" ? "with image check" : "ranked"}${e.rank ? `, rank ${e.rank}` : ""}${e.best_score !== null ? `, ranking score ${e.best_score.toFixed(3)} — not a probability` : ""})` + (e.visual_verdict ? ` · AI image check: ${e.visual_verdict.replace("_", " ")} (unverified)` : "");
  info.append(element("p", how, "muted"));
  if (e.source_status === "missing") info.append(element("p", `The recording with content hash ${e.video_sha256.slice(0, 16)}… is no longer in the library. The reference is kept; restore the original file to review it.`, "warning"));
  if (e.video_url) {
    const watch = element("button", "Open footage →"); watch.type = "button";
    watch.onclick = () => openVideo(e.current_video_id, e.current_filename || e.video_filename, e.video_url, e.start_sec, e.end_sec);
    info.append(watch);
  }
  const review = element("div", undefined, "review-feedback");
  review.append(element("p", "Your decision (recorded in the change history; earlier decisions are kept):"));
  for (const [value, label] of Object.entries(decisionNames)) {
    const b = element("button", label, "secondary"); b.type = "button"; b.disabled = !open;
    b.setAttribute("aria-pressed", String(e.decision === value));
    b.onclick = () => change(post(`/api/investigations/${activeCase.id}/evidence/${e.id}/review`, {decision: value}), `Saved: ${label}.`);
    review.append(b);
  }
  const noteId = `note-${e.id}`;
  const noteLabel = element("label", "Reviewer note"); noteLabel.htmlFor = noteId; noteLabel.className = "note-label";
  const note = element("textarea"); note.id = noteId; note.maxLength = 2000; note.rows = 2; note.value = e.note; note.disabled = !open;
  const saveNote = element("button", "Save note", "secondary"); saveNote.type = "button"; saveNote.disabled = !open;
  saveNote.onclick = () => change(post(`/api/investigations/${activeCase.id}/evidence/${e.id}/review`, {note: note.value}), "Note saved.");
  const remove = element("button", "Remove from investigation", "secondary"); remove.type = "button"; remove.disabled = !open;
  remove.onclick = () => {
    const reason = window.prompt("Why remove this clip? (kept in the change history)", "");
    if (reason !== null) change(post(`/api/investigations/${activeCase.id}/evidence/${e.id}/remove`, {reason}), "Clip removed.");
  };
  review.append(noteLabel, note, saveNote, remove);
  if (e.reviewed_at) review.append(element("span", `Decision saved ${new Date(e.reviewed_at).toLocaleString()}.`, "muted"));
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

window.investigationClipButton = function (hit, query, visual, rank) {
  const button = element("button", "Add to investigation", "secondary");
  button.type = "button";
  button.onclick = async () => {
    const id = $("save-to").value;
    if (!id) { notice("Choose an investigation under ‘Save searches and clips to’ first."); return; }
    button.disabled = true;
    try {
      activeCase = await post(`/api/investigations/${id}/evidence`, {
        video_id: hit.video_id, start_sec: hit.start_sec, end_sec: hit.end_sec, query,
        search_mode: visual ? "visual" : "ranked", rank: rank || null, best_score: hit.best_score,
        score_above_median: hit.best_score_above_median, thumbnail: hit.thumbnail,
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
  const buttons = [$("case-report-html"), $("case-report-json")];
  buttons.forEach(b => { b.disabled = true; });
  notice(format === "html" ? "Preparing the report… (checking each source video's content hash)" : "Preparing the data export…");
  try {
    const response = await fetch(`/api/investigations/${activeCase.id}/report`, {
      method: "POST", headers: {"X-CSRF-Token": token, "Content-Type": "application/json"}, body: JSON.stringify({format})});
    if (!response.ok) throw new Error((await response.json()).error || "The report could not be created.");
    const url = URL.createObjectURL(await response.blob());
    const link = element("a"); link.href = url; link.download = `investigation-${activeCase.id}-report.${format}`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    notice(format === "html" ? "Report downloaded. It contains frame images: share it only with authorised people." : "Investigation data downloaded.");
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
