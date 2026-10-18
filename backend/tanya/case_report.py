"""Investigation reports (JSON and a self-contained, printable HTML page).

Reports keep human decisions separate from retrieval: only items a person marked Correct are
"human-confirmed". Similarity scores appear only as context for how a clip was found. Every item
keeps its source reference (content hash, file name and path when added, time window), and items
whose source recording is no longer in the library are flagged rather than dropped.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

REPORT_VERSION = 1
CATEGORIES = {
    "correct": ("human_confirmed", "Human-confirmed (marked Correct)"),
    "wrong": ("rejected_by_reviewer", "Rejected by reviewer (marked Wrong)"),
    "unsure": ("unsure", "Reviewer unsure"),
    None: ("unreviewed_candidate", "Unreviewed candidate (not checked by a person)"),
}
LIMITATIONS = [
    "Clips were found by similarity search. Search results are not detections, and similarity scores "
    "are ranking signals, not calibrated probabilities.",
    "Only items a person marked Correct are human-confirmed. Unreviewed candidates and AI image-check "
    "verdicts are unverified.",
    "A search returning no relevant clip does not prove an event did not happen.",
    "Search works on 10-second chunks; time windows are approximate, not frame-accurate.",
    "Clip times are positions within each recording. Absolute times appear only where an operator "
    "entered the recording's start time, and depend on that camera clock being correct.",
    "Accuracy on real CCTV footage has not been validated for this system.",
]


def _fmt(sec) -> str:
    if sec is None:
        return "—"
    sec = float(sec)
    whole = int(sec)
    text = f"{whole // 3600:d}:{whole % 3600 // 60:02d}:{whole % 60:02d}" if whole >= 3600 else f"{whole // 60:d}:{whole % 60:02d}"
    frac = sec - whole
    return text + (f".{round(frac * 10):d}" if frac >= 0.05 else "")


def build_report(inv: dict, items: list[dict], basis: str, audit: list[dict]) -> dict:
    """items: timeline-ordered, source-resolved evidence (see investigations.timeline/resolve_sources)."""
    evidence = []
    counts = {key: 0 for key, _ in CATEGORIES.values()}
    for e in items:
        category = CATEGORIES[e["decision"]][0]
        counts[category] += 1
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
            "review": {"decision": e["decision"], "note": e["note"], "reviewed_at": e["reviewed_at"]},
            "added_at": e["added_at"],
            "thumbnail": e.get("thumbnail"),
        })
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "investigation": {k: inv[k] for k in ("id", "title", "description", "status", "created_at", "updated_at")},
        "summary": {"evidence_items": len(evidence), **counts,
                    "missing_sources": sum(e["source"]["status"] == "missing" for e in evidence),
                    "changed_sources": sum(e["source"]["status"] == "changed" for e in evidence),
                    "timeline_basis": basis},
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
*{box-sizing:border-box} body{font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#1f2b28;margin:0;padding:24px 16px;background:#fff}
main{max-width:1000px;margin:0 auto} h1{font-size:24px;margin:0 0 4px} h2{font-size:17px;margin:28px 0 10px;border-bottom:1px solid #dfe6e1;padding-bottom:4px}
.meta{color:#5d6b66;font-size:12px} .banner{background:#fff6e0;border:1px solid #e0b33f;border-radius:8px;padding:10px 14px;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:12px} th,td{border:1px solid #dfe6e1;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f3f6f4} .item{border:1px solid #dfe6e1;border-radius:10px;padding:12px;margin:12px 0;display:grid;grid-template-columns:220px 1fr;gap:14px;break-inside:avoid}
.item img{width:100%;border-radius:6px} .noimg{border:1px dashed #c8d3cc;border-radius:6px;padding:30px 8px;text-align:center;color:#7c8a84;font-size:12px}
.cat{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid #c9d3cd}
.human_confirmed{background:#e3f4ea;border-color:#62a37f} .rejected_by_reviewer{background:#fbe7e3;border-color:#c97b6b}
.unsure{background:#fff2d9;border-color:#d8a64a} .unreviewed_candidate{background:#eef1f8;border-color:#9aa7c7}
.missing{color:#a33e2b;font-weight:600} .small{font-size:12px;color:#5d6b66} code{font-size:11px;word-break:break-all}
@media(max-width:640px){.item{grid-template-columns:1fr}} @media print{body{padding:0}}
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


def render_html(report: dict, frames_dir: Path | None = None) -> str:
    inv, s = report["investigation"], report["summary"]
    basis_text = {"absolute": "by camera time (operator-entered recording start times)",
                  "within_recording": "by recording, then position within each recording (no camera start times entered)",
                  "mixed": "camera-timed clips first, then other recordings by position within the recording",
                  "empty": "no evidence yet"}[s["timeline_basis"]]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Investigation report: {escape(inv['title'])}</title><style>{CSS}</style></head><body><main>",
        f"<h1>{escape(inv['title'])}</h1>",
        f"<p class='meta'>Investigation #{inv['id']} · status {escape(inv['status'])} · created {escape(inv['created_at'])} · "
        f"report generated {escape(report['generated_at'])} (UTC)</p>",
    ]
    if inv["description"]:
        out.append(f"<p>{escape(inv['description'])}</p>")
    out.append("<div class='banner'><strong>Read this first.</strong> This report lists clips found by similarity "
               "search and a person's review decisions. Only items marked <em>Correct</em> by a person are "
               "human-confirmed. Nothing in this report was confirmed by the AI, and absence of a clip does not "
               "prove an event did not happen.</div>")
    out.append("<h2>Summary</h2><table><tr><th>Evidence items</th><th>Human-confirmed</th><th>Rejected</th>"
               "<th>Unsure</th><th>Unreviewed</th><th>Missing sources</th><th>Changed sources</th></tr>"
               f"<tr><td>{s['evidence_items']}</td><td>{s['human_confirmed']}</td><td>{s['rejected_by_reviewer']}</td>"
               f"<td>{s['unsure']}</td><td>{s['unreviewed_candidate']}</td><td>{s['missing_sources']}</td>"
               f"<td>{s['changed_sources']}</td></tr></table>")
    out.append(f"<h2>Evidence timeline</h2><p class='small'>Ordered {escape(basis_text)}.</p>")
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
                  "missing": "<span class='missing'>MISSING from the library — reference kept below</span>",
                  "changed": "<span class='missing'>CHANGED: the file's content no longer matches the reference "
                             "hash below — do not rely on it without checking the original</span>"}[src["status"]]
        if src.get("content_verified_at_export"):
            status += " · content verified against the hash at export"
        found = ("chosen manually in the video player (not a search result)" if f["search_mode"] == "manual" else
                 f"query “{escape(f['query'])}” ({escape(f['search_mode'])} search)")
        found = (found
                 + (f", rank {f['rank']}" if f["rank"] else "")
                 + (f", ranking score {f['ranking_score']:.3f} (not a probability)" if f["ranking_score"] is not None else ""))
        if f["ai_image_check"]:
            found += f"; AI image check: {escape(f['ai_image_check'])} (unverified)"
            if f["ai_image_check_reason"]:
                found += f" — “{escape(f['ai_image_check_reason'])}”"
        decision = (f"{escape(r['decision'])} at {escape(r['reviewed_at'] or '')}" if r["decision"] else "not reviewed")
        out.append(
            f"<section class='item'><div>{_thumbnail_tag(e['thumbnail'], frames_dir)}</div><div>"
            f"<span class='cat {e['category']}'>{escape(label)}</span>"
            f"<p><strong>{escape(src['filename_when_added'])}</strong> · {when}</p>"
            f"<p class='small'>Source: {status}<br>Content hash <code>{escape(src['video_sha256'])}</code><br>"
            f"Path when added: <code>{escape(src['path_when_added'])}</code></p>"
            f"<p class='small'>Found by: {found}</p>"
            f"<p class='small'>Review: {decision}</p>"
            + (f"<p><strong>Reviewer note:</strong> {escape(r['note'])}</p>" if r["note"] else "")
            + "</div></section>")
    out.append("<h2>Saved searches</h2>")
    if report["saved_queries"]:
        out.append("<table><tr><th>Query</th><th>Mode</th><th>Settings</th><th>Last run</th><th>Results</th></tr>")
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
    out.append("<p class='small'>Frame images are embedded so this report can be reviewed offline. It may contain "
               "personal data: share it only with people authorised to see the footage.</p></main></body></html>")
    return "\n".join(out)
