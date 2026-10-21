"""Investigation reports (JSON and a self-contained, printable HTML page).

Reports keep human decisions separate from retrieval: only items a person marked Correct ("relevant")
are "human-confirmed". Similarity scores and detector scores appear only as context for how a clip was
found. Every item keeps its source reference (content hash, file name and path when added, time window),
and items whose source recording is missing or changed are flagged rather than dropped.

Event-index clips also carry the provenance the server recorded when they were added (label, source and
label status, e.g. a provisional single-reviewer label or an unreviewed YOLO person detection). Frame
images are footage, so they are embedded in the HTML only when the person exporting asks for them.

Version 2 keeps every version-1 field and adds: evidence[].event, evidence[].review.history,
summary.unresolved / summary.by_source / summary.label_status, report_options and label_caveats.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

REPORT_VERSION = 2
CATEGORIES = {
    "correct": ("human_confirmed", "Human-confirmed (marked Correct): relevant"),
    "wrong": ("rejected_by_reviewer", "Rejected by reviewer (marked Wrong): not relevant"),
    "unsure": ("unsure", "Reviewer unsure: uncertain"),
    None: ("unreviewed_candidate", "Unreviewed candidate (not checked by a person)"),
}
DECISION_NAMES = {"correct": "Relevant (Correct)", "wrong": "Not relevant (Wrong)", "unsure": "Uncertain (Unsure)",
                  None: "not reviewed"}
SOURCE_NAMES = {"provisional_review": "CAVIAR annotation, reviewed by one person (provisional)",
                "publisher_annotation": "CAVIAR publisher annotation (not reviewed here)",
                "synthetic_script": "Scripted event in generated synthetic footage",
                "yolo_person": "YOLO person detection (unreviewed candidate)"}
LIMITATIONS = [
    "Clips were found by similarity search, a direct footage scan, the preset offline event index or by hand. "
    "Search results are not detections, and similarity scores are ranking signals, not calibrated probabilities.",
    "Only items a person marked Correct are human-confirmed. Unreviewed candidates, AI image-check verdicts and "
    "YOLO person detections are unverified.",
    "YOLO person detections only suggest that a person may be in view. They do not establish a fall, fight or any "
    "other action.",
    "Event-index labels come from the source named on each item. Provisional CAVIAR labels were reviewed by one "
    "person; a second independent review is pending, so they are not independently verified.",
    "A search returning no relevant clip does not prove an event did not happen.",
    "Ranked search works on 10-second chunks; time windows are approximate, not frame-accurate.",
    "Clip times are positions within each recording. Absolute times appear only where an operator "
    "entered the recording's start time, and depend on that camera clock being correct.",
    "Accuracy on real CCTV footage has not been validated for this system.",
]
BRAND_MARK = Path(__file__).resolve().parent / "static" / "brand" / "favicon-64.png"


def _fmt(sec) -> str:
    if sec is None:
        return "—"
    sec = float(sec)
    whole = int(sec)
    text = f"{whole // 3600:d}:{whole % 3600 // 60:02d}:{whole % 60:02d}" if whole >= 3600 else f"{whole // 60:d}:{whole % 60:02d}"
    frac = sec - whole
    return text + (f".{round(frac * 10):d}" if frac >= 0.05 else "")


def build_report(inv: dict, items: list[dict], basis: str, audit: list[dict], include_frames: bool = False) -> dict:
    """items: timeline-ordered, source-resolved evidence (see investigations.timeline/resolve_sources)."""
    evidence = []
    counts = {key: 0 for key, _ in CATEGORIES.values()}
    by_source, label_status = {}, {}
    for e in items:
        category = CATEGORIES[e["decision"]][0]
        counts[category] += 1
        event = e.get("event")
        if event:
            by_source[event["source"]] = by_source.get(event["source"], 0) + 1
            label_status[event.get("verification", "unknown")] = label_status.get(event.get("verification", "unknown"), 0) + 1
        evidence.append({
            "evidence_id": e["id"],
            "category": category,
            "source": {"video_sha256": e["video_sha256"], "filename_when_added": e["video_filename"],
                       "path_when_added": e["video_rel_path"], "status": e["source_status"],
                       "current_filename": e.get("current_filename"),
                       "content_verified_at_export": e.get("content_verified")},
            "window": {"start_sec": e["start_sec"], "end_sec": e["end_sec"],
                       "absolute_start": e.get("absolute_start"), "absolute_end": e.get("absolute_end")},
            "found_by": {"query": e["query"], "search_mode": e["search_mode"], "rank": e["rank"],
                         "ranking_score": e["best_score"], "score_above_median": e["score_above_median"],
                         "ai_image_check": e["visual_verdict"], "ai_image_check_reason": e["visual_reason"]},
            "event": event,
            "review": {"decision": e["decision"], "note": e["note"], "reviewed_at": e["reviewed_at"],
                       "history": e.get("history", [])},
            "added_at": e["added_at"],
            "thumbnail": e.get("thumbnail"),
        })
    caveats = []
    if "provisional_single_reviewer" in label_status:
        caveats.append("Some evidence uses CAVIAR labels reviewed by one person only (provisional). A second "
                       "independent review is pending; reviewer disagreements are not resolved automatically.")
    if "yolo_person" in by_source:
        caveats.append("Some evidence comes from YOLO person detection: a person-presence candidate, not a "
                       "recognised action or a confirmed incident.")
    if "synthetic_script" in by_source:
        caveats.append("Some evidence uses generated cartoon footage with scripted events; it is not real CCTV.")
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "investigation": {k: inv[k] for k in ("id", "title", "description", "status", "created_at", "updated_at")},
        "report_options": {"frame_images_included": include_frames},
        "summary": {"evidence_items": len(evidence), **counts,
                    "unresolved": counts["unsure"] + counts["unreviewed_candidate"],
                    "missing_sources": sum(e["source"]["status"] == "missing" for e in evidence),
                    "changed_sources": sum(e["source"]["status"] == "changed" for e in evidence),
                    "by_source": by_source, "label_status": label_status,
                    "timeline_basis": basis},
        "label_caveats": caveats,
        "saved_queries": [{k: q[k] for k in ("id", "query", "search_mode", "settings", "created_at",
                                            "last_run_at", "last_result_count")} for q in inv["queries"]],
        "evidence": evidence,
        "removed_evidence": [{"evidence_id": r["id"], "filename": r["video_filename"], "start_sec": r["start_sec"],
                              "end_sec": r["end_sec"], "decision_at_removal": r["decision"],
                              "removed_at": r["removed_at"], "reason": r["removal_reason"]}
                             for r in inv["removed_evidence"]],
        "audit_log": [{"at": a["at"], "action": a["action"], "detail": a["detail"]} for a in audit],
        "limitations": LIMITATIONS,
    }


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------- HTML

CSS = """
:root{--orange:#D96828;--orange-strong:#B4521A;--orange-text:#A94B15;--orange-soft:#FFF4EC;--red:#E3342F;--red-text:#C42B26;
--red-soft:#FDECEC;--green:#187245;--green-soft:#E8F6EE;--amber:#8A5A00;--amber-soft:#FFF5DD;--slate:#3E5F82;--slate-soft:#EEF2F7;
--ink:#20242B;--muted:#626B78;--line:#E2E5E9;--bg:#F5F6F8}
*{box-sizing:border-box} body{font:14px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif;color:var(--ink);margin:0;padding:24px 16px;background:#fff}
main{max-width:1000px;margin:0 auto}
header.brand{display:flex;align-items:center;gap:12px;border-bottom:3px solid var(--orange);padding-bottom:12px;margin-bottom:14px}
header.brand img{width:40px;height:40px} .wordmark{font-weight:800;font-size:20px;letter-spacing:-.01em}
.wordmark .t{color:var(--orange-strong)} .wordmark .c{color:var(--red-text)} .doc{margin-left:auto;text-align:right;font-size:12px;color:var(--muted)}
h1{font-size:24px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 10px;padding-bottom:4px;border-bottom:1px solid var(--line);text-transform:uppercase;letter-spacing:.04em}
.meta{color:var(--muted);font-size:12px} .banner{background:var(--orange-soft);border:1px solid #F2C3A3;border-left:4px solid var(--orange);border-radius:8px;padding:10px 14px;margin:14px 0}
.caveat{background:var(--amber-soft);border:1px solid #F1D79A;border-left:4px solid #D99A1E;border-radius:8px;padding:8px 12px;margin:8px 0;font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px} .card{border:1px solid var(--line);border-radius:10px;padding:10px 12px;border-top:3px solid var(--slate)}
.card b{display:block;font-size:22px} .card span{font-size:12px;color:var(--muted)} .card.ok{border-top-color:var(--green)} .card.bad{border-top-color:var(--red)} .card.warn{border-top-color:#D99A1E}
table{border-collapse:collapse;width:100%;font-size:12px} th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top} th{background:var(--bg)}
.item{border:1px solid var(--line);border-radius:10px;padding:12px;margin:12px 0;display:grid;grid-template-columns:200px 1fr;gap:14px;break-inside:avoid}
.item.noframe{grid-template-columns:1fr} .item img{width:100%;border-radius:6px}
.noimg{border:1px dashed #C8CDD4;border-radius:6px;padding:30px 8px;text-align:center;color:var(--muted);font-size:12px}
.pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--line);margin:0 4px 4px 0}
.human_confirmed{background:var(--green-soft);border-color:#B9E3CB;color:var(--green)} .rejected_by_reviewer{background:var(--red-soft);border-color:#F3B9B7;color:var(--red-text)}
.unsure{background:var(--amber-soft);border-color:#F1D79A;color:var(--amber)} .unreviewed_candidate{background:var(--slate-soft);border-color:#D2DCE8;color:var(--slate)}
.src-provisional_review,.src-publisher_annotation{background:var(--slate-soft);color:var(--slate)} .src-synthetic_script{background:var(--bg);color:var(--muted)}
.src-yolo_person{background:var(--amber-soft);color:var(--amber)} .warnline{color:var(--red-text);font-weight:600}
.small{font-size:12px;color:var(--muted)} code{font-size:11px;word-break:break-all} dl{display:grid;grid-template-columns:150px 1fr;gap:2px 10px;margin:6px 0;font-size:12px} dt{color:var(--muted)} dd{margin:0}
@media(max-width:640px){.item{grid-template-columns:1fr} dl{grid-template-columns:1fr}}
@media print{body{padding:0} .item,.card,table tr{break-inside:avoid} h2{break-after:avoid} a{color:inherit}}
"""


def _thumbnail_tag(thumbnail, frames_dir: Path | None) -> str:
    if not thumbnail or frames_dir is None:
        return "<div class='noimg'>no frame image</div>"
    root = frames_dir.resolve()
    path = (root / thumbnail).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".jpg" or not path.is_file():
        return "<div class='noimg'>frame image unavailable</div>"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"<img alt='Frame from the clip' src='data:image/jpeg;base64,{data}'>"


def _brand() -> str:
    mark = ""
    if BRAND_MARK.is_file():   # the TanyaCCTV logo mark (not footage), so the report is recognisable offline
        mark = f"<img alt='TanyaCCTV logo' src='data:image/png;base64,{base64.b64encode(BRAND_MARK.read_bytes()).decode('ascii')}'>"
    return f"{mark}<span class='wordmark'><span class='t'>Tanya</span><span class='c'>CCTV</span></span>"


def _found_by(f: dict, event: dict | None) -> str:
    if f["search_mode"] == "manual":
        found = "chosen manually in the video player (not a search result)"
    elif f["search_mode"] == "scan":
        found = (f"direct footage scan for “{escape(f['query'])}” (sampled images checked in time order; "
                 "not a similarity ranking)")
    elif f["search_mode"] == "index":
        found = f"preset offline event index, query “{escape(f['query'])}” (keyword match; no AI, no ranking)"
    else:
        found = f"query “{escape(f['query'])}” ({escape(f['search_mode'])} search)"
    found += (f", rank {f['rank']}" if f["rank"] else "")
    found += (f", ranking score {f['ranking_score']:.3f} (not a probability)" if f["ranking_score"] is not None else "")
    if f["ai_image_check"]:
        found += f"; AI image check: {escape(f['ai_image_check'])} (unverified)"
        if f["ai_image_check_reason"]:
            found += f" — “{escape(f['ai_image_check_reason'])}”"
    return found


def _event_block(event: dict | None) -> str:
    if not event:
        return ""
    src = event.get("source", "")
    rows = [("Event label", escape(event.get("label", ""))),
            ("Label source", f"<span class='pill src-{escape(src)}'>{escape(SOURCE_NAMES.get(src, src))}</span>"),
            ("Label status", escape(str(event.get("verification", "unknown")).replace("_", " "))),
            ("Provenance", escape(event.get("provenance", "")))]
    d = event.get("detector")
    if d:
        info = (f"confidence up to {d['max_conf']:.2f} (mean {d['mean_conf']:.2f}) over {d['frames']} frames at ≥ "
                f"{d['threshold']}; model {escape(str(d.get('weights') or '?'))}, {escape(str(d.get('imgsz') or '?'))} px")
        info += ("; weights hash " + escape(d["weights_sha256"][:16]) + "…" if d.get("weights_sha256")
                 else "; weights hash not recorded by the source run")
        peak = d.get("peak")
        if peak:
            info += (f"; strongest box at {_fmt(peak['t'])} (frame {peak['frame']}), pixels "
                     f"[{', '.join(str(v) for v in peak['box'])}]")
        rows.append(("Detector", info + ". A detector score, not the probability of an event."))
    return "<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def _history(review: dict) -> str:
    entries = [h for h in review.get("history", []) if h["action"] != "note_changed"]
    if not entries:
        return ""
    steps = " → ".join(f"{escape(DECISION_NAMES.get(h['to'], str(h['to'])))} ({escape(h['at'])})" for h in entries)
    return f"<p class='small'>Decision history: not reviewed → {steps}</p>"


def render_html(report: dict, frames_dir: Path | None = None) -> str:
    inv, s = report["investigation"], report["summary"]
    frames = report.get("report_options", {}).get("frame_images_included") and frames_dir is not None
    basis_text = {"absolute": "by camera time (operator-entered recording start times)",
                  "within_recording": "by recording, then position within each recording (no camera start times entered)",
                  "mixed": "camera-timed clips first, then other recordings by position within the recording",
                  "empty": "no evidence yet"}[s["timeline_basis"]]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Investigation report: {escape(inv['title'])}</title><style>{CSS}</style></head><body><main>",
        f"<header class='brand'>{_brand()}<div class='doc'>Investigation report<br>#{inv['id']} · generated "
        f"{escape(report['generated_at'])} UTC</div></header>",
        f"<h1>{escape(inv['title'])}</h1>",
        f"<p class='meta'>Investigation #{inv['id']} · status {escape(inv['status'])} · created {escape(inv['created_at'])} · "
        f"last updated {escape(inv['updated_at'])} · report generated {escape(report['generated_at'])} (UTC)</p>",
    ]
    if inv["description"]:
        out.append(f"<p>{escape(inv['description'])}</p>")
    out.append("<div class='banner'><strong>Read this first.</strong> This report lists clips found by search, the "
               "preset event index or by hand, and a person's review decisions. Only items marked <em>Correct</em> "
               "(relevant) by a person are human-confirmed. Nothing in this report was confirmed by the AI or a "
               "detector, and absence of a clip does not prove an event did not happen.</div>")
    for c in report.get("label_caveats", []):
        out.append(f"<div class='caveat'>{escape(c)}</div>")
    cards = [("Evidence items", s["evidence_items"], ""), ("Human-confirmed", s["human_confirmed"], "ok"),
             ("Rejected", s["rejected_by_reviewer"], ""), ("Unsure", s["unsure"], "warn"),
             ("Unreviewed", s["unreviewed_candidate"], "warn"), ("Unresolved", s.get("unresolved", 0), "warn"),
             ("Missing sources", s["missing_sources"], "bad" if s["missing_sources"] else ""),
             ("Changed sources", s["changed_sources"], "bad" if s["changed_sources"] else "")]
    out.append("<h2>Summary</h2><div class='cards'>" + "".join(
        f"<div class='card {cls}'><b>{n}</b><span>{escape(label)}</span></div>" for label, n, cls in cards) + "</div>")
    out.append("<table><tr><th>Evidence items</th><th>Human-confirmed</th><th>Rejected</th>"
               "<th>Unsure</th><th>Unreviewed</th><th>Missing sources</th><th>Changed sources</th></tr>"
               f"<tr><td>{s['evidence_items']}</td><td>{s['human_confirmed']}</td><td>{s['rejected_by_reviewer']}</td>"
               f"<td>{s['unsure']}</td><td>{s['unreviewed_candidate']}</td><td>{s['missing_sources']}</td>"
               f"<td>{s['changed_sources']}</td></tr></table>")
    if s.get("by_source"):
        out.append("<p class='small'>Event-index evidence by label source: " + ", ".join(
            f"{escape(SOURCE_NAMES.get(k, k))}: {v}" for k, v in sorted(s["by_source"].items())) + ".</p>")
    out.append(f"<h2>Evidence timeline</h2><p class='small'>Ordered {escape(basis_text)}."
               + ("" if frames else " Frame images are not included in this report (choose “Include frame images” "
                                    "when exporting if they are needed and you are authorised to share them).") + "</p>")
    if not report["evidence"]:
        out.append("<p>No evidence has been added to this investigation.</p>")
    for e in report["evidence"]:
        label = {k: v for k, v in CATEGORIES.values()}[e["category"]]
        w, src, f, r = e["window"], e["source"], e["found_by"], e["review"]
        when = f"{_fmt(w['start_sec'])}–{_fmt(w['end_sec'])} in the recording"
        if w["absolute_start"]:
            when += f" · camera time {escape(w['absolute_start'])} to {escape(w['absolute_end'])}"
        status = {"available": "available in the library",
                  "renamed": f"available, now named {escape(src['current_filename'] or '')}",
                  "missing": "<span class='warnline'>MISSING from the library — reference kept below</span>",
                  "changed": "<span class='warnline'>CHANGED: the file's content no longer matches the reference "
                             "hash below — do not rely on it without checking the original</span>"}[src["status"]]
        if src.get("content_verified_at_export"):
            status += " · content verified against the hash at export"
        decision = (f"{escape(DECISION_NAMES[r['decision']])} at {escape(r['reviewed_at'] or '')}" if r["decision"]
                    else "not reviewed")
        thumb = f"<div>{_thumbnail_tag(e['thumbnail'], frames_dir)}</div>" if frames else ""
        out.append(
            f"<section class='item{'' if frames else ' noframe'}'>{thumb}<div>"
            f"<span class='pill {e['category']}'>{escape(label)}</span>"
            f"<p><strong>{escape(src['filename_when_added'])}</strong> · {when}</p>"
            + _event_block(e.get("event")) +
            f"<p class='small'>Source: {status}<br>Content hash <code>{escape(src['video_sha256'])}</code><br>"
            f"Path when added: <code>{escape(src['path_when_added'])}</code></p>"
            f"<p class='small'>Found by: {_found_by(f, e.get('event'))}</p>"
            f"<p class='small'>Review: {decision}</p>" + _history(r)
            + (f"<p><strong>Reviewer note:</strong> {escape(r['note'])}</p>" if r["note"] else "")
            + "</div></section>")
    out.append("<h2>Saved searches</h2>")
    if report["saved_queries"]:
        out.append("<table><tr><th>Query</th><th>Mode</th><th>Settings and filters</th><th>Last run</th><th>Results</th></tr>")
        for q in report["saved_queries"]:
            out.append(f"<tr><td>{escape(q['query'])}</td><td>{escape(q['search_mode'])}</td>"
                       f"<td><code>{escape(json.dumps(q['settings'], sort_keys=True))}</code></td>"
                       f"<td>{escape(q['last_run_at'] or '')}</td><td>{'' if q['last_result_count'] is None else q['last_result_count']}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p>No saved searches.</p>")
    if report["removed_evidence"]:
        out.append("<h2>Removed from the investigation</h2><table><tr><th>Clip</th><th>Window</th><th>Decision at removal</th>"
                   "<th>Removed</th><th>Reason</th></tr>")
        for r in report["removed_evidence"]:
            out.append(f"<tr><td>{escape(r['filename'])}</td><td>{_fmt(r['start_sec'])}–{_fmt(r['end_sec'])}</td>"
                       f"<td>{escape(r['decision_at_removal'] or 'not reviewed')}</td><td>{escape(r['removed_at'])}</td>"
                       f"<td>{escape(r['reason'] or '')}</td></tr>")
        out.append("</table>")
    out.append("<h2>Change history</h2><table><tr><th>When (UTC)</th><th>Action</th><th>Details</th></tr>")
    for a in report["audit_log"]:
        out.append(f"<tr><td>{escape(a['at'])}</td><td>{escape(a['action'].replace('_', ' '))}</td>"
                   f"<td><code>{escape(json.dumps(a['detail'], sort_keys=True, ensure_ascii=False))}</code></td></tr>")
    out.append("</table><h2>Limitations</h2><ul>" + "".join(f"<li>{escape(x)}</li>" for x in report["limitations"]) + "</ul>")
    out.append("<p class='small'>" + ("Frame images are embedded so this report can be reviewed offline. " if frames else "")
               + "This report may contain personal data: share it only with people authorised to see the footage.</p>"
               "</main></body></html>")
    return "\n".join(out)
