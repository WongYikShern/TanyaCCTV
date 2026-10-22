"""Build the CAVIAR real-camera evaluation dataset from publisher labels (local only, no AI calls).

    python backend/scripts/build_real_dataset.py            # manifest, ground truth, review sheet
    python backend/scripts/build_real_dataset.py --sheets   # also contact sheets + review page for reviewers
    python backend/scripts/build_real_dataset.py --serve-review   # review page at http://127.0.0.1:5003/

Needs the footage prepared by `download_caviar.py --download` then `--prepare`. Writes:
  evaluation/datasets/caviar-events.json     derived event intervals (+ licence/attribution)
  evaluation/datasets/caviar-manifest.jsonl  one row per query x clip x event
  evaluation/caviar_ground_truth.json        ground truth in the evaluation harness format
  evaluation/review/caviar-review.csv        human verification sheet (fill in, keep alongside)
With --sheets, JPEG contact sheets and review.html go to data/cctv_validation/caviar/review/
(git-ignored: they show footage). If evaluation/review/caviar-verified.json exists (written by
apply_label_review.py), verified boundaries are applied and rejected events are removed.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tanya import real_dataset  # noqa: E402

CAVIAR = ROOT / "data" / "cctv_validation" / "caviar"
VERIFIED_FILE = ROOT / "evaluation" / "review" / "caviar-verified.json"


def load_verification() -> dict:
    if not VERIFIED_FILE.is_file():
        return {}
    return json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))["events"]


def sheet_name(category, e, i) -> str:
    return f"{category}_{Path(e['video']).stem}_{i:02d}_{e['derived_start_sec']:.2f}-{e['derived_end_sec']:.2f}.jpg"


REVIEW_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CAVIAR label review</title>
<style>body{font:14px system-ui,sans-serif;margin:0;background:#f1f3f7;color:#1a1d24}
header{position:sticky;top:0;background:#0a0b0f;color:#fff;padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;z-index:2}
header input{padding:6px;border-radius:6px;border:0;width:90px}button{background:#1f5eff;color:#fff;border:0;border-radius:8px;padding:7px 12px;cursor:pointer}
button.secondary{background:#fff;color:#1f5eff;border:1px solid #c9d6ff}main{max-width:1180px;margin:0 auto;padding:16px}
.ev{background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.06);padding:14px;margin:14px 0}
.ev.done{border-left:5px solid #0f9d58}.ev img{width:100%;border-radius:6px}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:8px}
video{width:384px;max-width:100%;background:#000;border-radius:6px}label{display:flex;gap:4px;align-items:center}
input[type=number]{width:80px}.mono{font-family:Consolas,monospace;background:#eef2ff;padding:4px 8px;border-radius:6px}textarea{width:100%;min-height:36px}.muted{color:#6a7180}.warn{background:#fff4dc;padding:10px;border-radius:8px}</style></head>
<body><header><strong>CAVIAR label review</strong><label>Your initials <input id="initials" maxlength="8"></label>
<button id="start" type="button">Start my review</button><span id="who"></span>
<span id="progress"></span><button id="download" hidden>Download my review CSV</button></header><main>
<p class="warn">Review <b>independently</b>: do not look at another reviewer's answers. For each event, watch around the
derived interval, then choose <b>confirm</b> (boundaries right within about 1 s), <b>adjust</b> (event real, enter the
correct start/end) or <b>reject</b> (the event does not happen here). Use the burned-in camera clock and the video
controls; "Set start/end" copies the current playback time. Answers autosave in this browser.
Footage: CAVIAR, EC Funded CAVIAR project/IST 2001 37540 (publisher states CC BY-SA). Local only.</p>
<div id="events"></div></main>
<script>
const EVENTS = __EVENTS__;
const COLUMNS = __COLUMNS__;
const FPS = __FPS__;   // label frame i <-> video time i / FPS (verified frame-exact in the browser)
// Where "Play from 1 s before start" seeks: never before 0 s or past the last frame; null when the
// event's start time is missing or invalid (the button is then disabled rather than guessing).
function seekTarget(start, duration) {
  if (start === null || start === undefined || start === "") return null;
  const s = Number(start);
  if (!Number.isFinite(s) || s < 0) return null;
  let t = Math.max(0, s - 1);
  if (Number.isFinite(duration) && duration > 0) t = Math.min(t, Math.max(0, duration - 1 / FPS));
  return Math.round(t * 100) / 100;
}
// Exact position (the browser's own clock shows whole seconds only, e.g. 25.20 s appears as 0:25).
function readout(t) { return Number.isFinite(t) ? "Video time " + t.toFixed(2) + " s · frame " + Math.floor(t * FPS + 1e-6) : "Video time –"; }
// Each reviewer's answers are stored separately (keyed by initials) so a second reviewer on the
// same computer never sees the first reviewer's choices.
let store = {}, reviewer = "";
const keyFor = who => "caviar-review:" + who.toLowerCase();
const save = () => { try { localStorage.setItem(keyFor(reviewer), JSON.stringify(store)); } catch (e) {} progress(); };
const initials = document.getElementById("initials");
document.getElementById("start").onclick = () => {
  const who = initials.value.trim();
  if (!/^[A-Za-z][A-Za-z0-9.-]{0,7}$/.test(who)) { alert("Enter your initials (letters), e.g. AB."); return; }
  reviewer = who;
  try { store = JSON.parse(localStorage.getItem(keyFor(who)) || "{}"); } catch (e) { store = {}; }
  initials.disabled = true; document.getElementById("start").hidden = true;
  document.getElementById("who").textContent = "Reviewer: " + who + " (reload the page to switch reviewer)";
  document.getElementById("download").hidden = false;
  render();
};
function progress() { const n = EVENTS.filter(e => (store[e.event_key] || {}).verdict).length;
  document.getElementById("progress").textContent = n + " / " + EVENTS.length + " reviewed"; }
function el(tag, attrs = {}, text) { const n = document.createElement(tag); Object.assign(n, attrs); if (text !== undefined) n.textContent = text; return n; }
function render() {
for (const e of EVENTS) {
  const s = store[e.event_key] || (store[e.event_key] = {});
  const card = el("section", {className: "ev"});
  card.append(el("h3", {}, e.event_id + " · " + e.category + " · " + e.video + " · " + e.derived_start_sec + "–" + e.derived_end_sec + " s"),
              el("p", {className: "muted"}, "Rule: " + e.rule));
  card.append(el("img", {src: e.sheet, alt: "Frames around " + e.event_id, loading: "lazy"}));
  const video = el("video", {src: "../videos/" + e.video, controls: true, preload: "metadata"});
  const row = el("div", {className: "row"});
  const target = seekTarget(e.derived_start_sec);
  const jump = el("button", {className: "secondary", type: "button"},
                  target === null ? "Start time missing: review this event manually"
                                  : "Play from " + target.toFixed(2) + " s (1 s before the " + Number(e.derived_start_sec).toFixed(2) + " s start)");
  jump.disabled = target === null;
  jump.onclick = () => { const t = seekTarget(e.derived_start_sec, video.duration); if (t === null) return;
                         video.currentTime = t; video.play(); };
  const now = el("span", {className: "mono now"}, readout(NaN));
  for (const ev of ["loadedmetadata", "timeupdate", "seeked"]) video.addEventListener(ev, () => { now.textContent = readout(video.currentTime); });
  const start = el("input", {type: "number", step: "0.04", min: 0, value: s.start ?? ""});
  const end = el("input", {type: "number", step: "0.04", min: 0, value: s.end ?? ""});
  const setS = el("button", {className: "secondary", type: "button"}, "Set start"), setE = el("button", {className: "secondary", type: "button"}, "Set end");
  setS.onclick = () => { start.value = video.currentTime.toFixed(2); start.oninput(); };
  setE.onclick = () => { end.value = video.currentTime.toFixed(2); end.oninput(); };
  start.oninput = () => { s.start = start.value; save(); }; end.oninput = () => { s.end = end.value; save(); };
  const verdicts = el("div", {className: "row"});
  for (const v of ["confirm", "adjust", "reject"]) {
    const r = el("input", {type: "radio", name: e.event_key, value: v, checked: s.verdict === v});
    r.onchange = () => { s.verdict = v; card.classList.add("done"); save(); };
    const l = el("label"); l.append(r, v); verdicts.append(l);
  }
  if (s.verdict) card.classList.add("done");
  const notes = el("textarea", {placeholder: "Notes (what you saw, why you adjusted or rejected)", value: s.notes || ""});
  notes.oninput = () => { s.notes = notes.value; save(); };
  const ls = el("label"); ls.append("Verified start (s)", start); const le = el("label"); le.append("end (s)", end);
  row.append(jump, now, setS, setE, ls, le);
  card.append(video, row, verdicts, notes);
  document.getElementById("events").append(card);
}
progress();
}
const csvCell = v => { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
document.getElementById("download").onclick = () => {
  if (!reviewer) { alert("Start your review first."); return; }
  const missing = EVENTS.filter(e => (store[e.event_key] || {}).verdict === "adjust" && !(store[e.event_key].start && store[e.event_key].end));
  if (missing.length) { alert("Adjusted events need a verified start and end: " + missing.map(e => e.event_id).join(", ")); return; }
  const backwards = EVENTS.filter(e => { const a = store[e.event_key] || {}; return a.verdict === "adjust" && !(Number(a.end) > Number(a.start) && Number(a.start) >= 0); });
  if (backwards.length) { alert("Adjusted end must be after start (and start 0 s or later): " + backwards.map(e => e.event_id).join(", ")); return; }
  const lines = [COLUMNS.map(csvCell).join(",")];
  for (const e of EVENTS) { const s = store[e.event_key] || {};
    lines.push([e.event_id, e.event_key, e.video, e.category, e.derived_start_sec, e.derived_end_sec, e.rule,
                s.verdict || "", s.verdict === "adjust" ? s.start : "", s.verdict === "adjust" ? s.end : "",
                s.verdict ? reviewer : "", s.notes || ""].map(csvCell).join(",")); }
  const a = el("a", {href: URL.createObjectURL(new Blob([lines.join("\n") + "\n"], {type: "text/csv"})),
                     download: "caviar-review-" + reviewer + ".csv"});
  document.body.append(a); a.click(); a.remove();
};
</script></body></html>
"""


def review_page(built, out_dir: Path) -> Path:
    """Local, self-contained review page (opens from disk; footage stays local)."""
    items = real_dataset.review_items(built)
    names = {}
    for category, spans in built["events"].items():
        for i, e in enumerate(spans, 1):
            names[real_dataset.event_key(category, e["video"], e["derived_start_sec"], e["derived_end_sec"])] = \
                sheet_name(category, e, i)
    for item in items:
        item["sheet"] = names.get(item["event_key"], "")
    page = REVIEW_PAGE.replace("__EVENTS__", json.dumps(items).replace("</", "<\\/")).replace(
        "__COLUMNS__", json.dumps(real_dataset.REVIEW_COLUMNS)).replace("__FPS__", json.dumps(real_dataset.FPS))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "review.html"
    path.write_text(page, encoding="utf-8")
    return path


def contact_sheets(clips, events, out_dir: Path) -> int:
    """One image per derived event: frames 1 s before, at start, middle, end, and 1 s after."""
    import cv2
    import numpy as np
    out_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    by_video = {c["video"]: c for c in clips}
    for category, spans in sorted(events.items()):
        for i, e in enumerate(spans, 1):
            clip = by_video[e["video"]]
            cap = cv2.VideoCapture(str(CAVIAR / "videos" / e["video"]))
            tiles = []
            try:
                a, b = e["derived_start_sec"], e["derived_end_sec"]
                for label, t in (("-1s", a - 1), ("start", a), ("mid", (a + b) / 2), ("end", b - 0.04), ("+1s", b + 1)):
                    t = min(max(t, 0.0), clip["duration_sec"] - 0.04)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, round(t * real_dataset.FPS))
                    ok, frame = cap.read()
                    frame = frame if ok else np.zeros((clip["height"], clip["width"], 3), np.uint8)
                    cv2.putText(frame, f"{label} {t:.2f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (0, 255, 255), 1, cv2.LINE_AA)
                    tiles.append(frame)
            finally:
                cap.release()
            name = sheet_name(category, e, i)
            cv2.imwrite(str(out_dir / name), np.hstack(tiles))
            made += 1
    return made


def review_app(folder: Path = CAVIAR):
    """Local-only server for the review page with byte-range video (seeking). Serves only review/ and videos/."""
    from flask import Flask, abort, redirect, send_from_directory
    app = Flask(__name__)

    @app.get("/")
    def index():
        return redirect("/review/review.html")

    @app.get("/<any(review, videos):area>/<path:name>")
    def media(area, name):
        if not (folder / area).is_dir():
            abort(404)
        return send_from_directory(folder / area, name, conditional=True)
    return app


def rebuild(verification: dict | None = None):
    """Derive events (applying reviewer verification), validate, and write all committed outputs."""
    clips = real_dataset.load_clips(CAVIAR, ROOT / "evaluation/datasets/caviar-small.json")
    built = real_dataset.build(clips, verification)
    problems = real_dataset.validate_manifest_rows(built["rows"], {c["video"]: c["duration_sec"] for c in clips})
    if problems:
        raise ValueError("Manifest validation failed:\n  " + "\n  ".join(problems[:20]))
    paths = real_dataset.write_outputs(clips, built, ROOT / "evaluation/datasets",
                                       ROOT / "evaluation/review/caviar-review.csv")
    return clips, built, paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheets", action="store_true", help="also write local JPEG contact sheets for reviewers")
    parser.add_argument("--serve-review", action="store_true",
                        help="serve the review page at http://127.0.0.1:5003/ (local only; Ctrl+C to stop)")
    args = parser.parse_args()
    if args.serve_review:
        if not (CAVIAR / "review" / "review.html").is_file():
            print("Run with --sheets first to create the review page.", file=sys.stderr)
            return 1
        print("Review page: http://127.0.0.1:5003/  (local only; Ctrl+C to stop)", flush=True)
        review_app().run(host="127.0.0.1", port=5003, debug=False)
        return 0
    try:
        clips, built, paths = rebuild(load_verification())
    except (ValueError, OSError) as error:
        print(f"Cannot build the dataset: {error}", file=sys.stderr)
        return 1
    measurable = [c for c in built["cases"] if c["measurable"]]
    positives = [c for c in measurable if c["events"]]
    states = [e["verification"] for spans in built["events"].values() for e in spans]
    print(f"{len(clips)} clips, {len(states)} events: {states.count(real_dataset.VERIFIED)} human-verified, "
          f"{states.count(real_dataset.UNVERIFIED)} publisher-label only, {len(built['rejected'])} rejected by reviewers")
    print(f"{len(built['cases'])} queries: {len(positives)} positive, {len(measurable) - len(positives)} negative, "
          f"{len(built['cases']) - len(measurable)} unlabelled (not scored)")
    for category, spans in sorted(built["events"].items()):
        print(f"  {category:15s} {len(spans):3d} interval(s) in {len({e['video'] for e in spans})} clip(s)")
    for key, path in paths.items():
        print(f"wrote {key}: {path.relative_to(ROOT)}")
    if args.sheets:
        n = contact_sheets(clips, built["events"], CAVIAR / "review")
        page = review_page(built, CAVIAR / "review")
        print(f"wrote {n} contact sheets and {page.relative_to(ROOT)} (git-ignored; open the page in a browser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
