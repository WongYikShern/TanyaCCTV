"""Search benchmark on labelled footage: ranked retrieval vs scene scan (no AI calls are made).

    python backend/scripts/run_benchmark.py                      # CAVIAR ground truth, no runs yet
    python backend/scripts/run_benchmark.py --ranked RUN.json --scan RUN.json
    python backend/scripts/run_benchmark.py --plan               # exact upload bounds for a live run
    python backend/scripts/run_benchmark.py --ground-truth evaluation/synthetic_events_v2.json \\
        --ranked-recording evaluation/recordings/2026-10-19-events.json   # replayed synthetic check

RUN.json is a run record: {"mode": "ranked"|"scan", "source": "live"|"replay", "engine": "...",
"responses": {query: {"status": "ok"|"failed"|"unavailable", "latency_sec": s,
"windows": [{"video", "start_sec", "end_sec", "score"?, "verdict"?}]}}}. Queries without a
response are reported as unavailable. Replayed outputs are labelled as such, never as live.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tanya import benchmark  # noqa: E402
from tanya.evaluation import merged_windows  # noqa: E402
from tanya.search_sync import USD_PER_FRAME  # noqa: E402

PROJECT = ROOT.parent
DEFAULT_TRUTH = PROJECT / "evaluation/caviar_ground_truth.json"
DEFAULT_EVENTS = PROJECT / "evaluation/datasets/caviar-events.json"


def ranked_run_from_recording(path: Path, merge_ratio: float) -> dict:
    """Convert a recorded bridge response file (top chunks per query) into a replayed run record."""
    rec = json.loads(path.read_text(encoding="utf-8"))
    responses = {}
    for query, chunks in rec["responses"].items():
        windows = merged_windows(chunks, ratio=merge_ratio)
        responses[query] = dict(status="ok", latency_sec=None, windows=[
            dict(video=w.video, start_sec=w.start_sec, end_sec=w.end_sec, score=w.score) for w in windows])
    return dict(mode="ranked", source="replay", engine=f"recorded: {rec.get('engine', path.name)}",
                responses=responses)


def checked_run_from_recording(path: Path) -> dict:
    """Replay a recorded ranked-retrieval + image-check run ({"results": [{query, candidates, elapsed_sec}]}).
    Evidence spans are recomputed from the recorded sampled/cited frames with the current code."""
    from tanya.visual_review import evidence_span
    rec = json.loads(path.read_text(encoding="utf-8"))
    responses = {}
    for r in rec["results"]:
        windows = []
        for c in r["candidates"]:
            review = c.get("visual_review") or {}
            span = evidence_span(c["start_sec"], c["end_sec"], review.get("sampled_timestamps", []),
                                 review.get("evidence_timestamps", [])) or {}
            windows.append(dict(video=c["filename"], start_sec=c["start_sec"], end_sec=c["end_sec"],
                                verdict=review.get("verdict"), evidence_start_sec=span.get("start_sec"),
                                evidence_end_sec=span.get("end_sec")))
        windows.sort(key=lambda w: w["verdict"] != "supported")
        responses[r["query"]] = dict(status="ok", latency_sec=r.get("elapsed_sec"), windows=windows)
    return dict(mode="ranked_checked", source="replay",
                engine=f"recorded: {rec.get('model', 'image check')} on {rec.get('retrieval_recording', 'ranked retrieval')}",
                responses=responses)


def verification_summary(meta: dict) -> str:
    """'N of M events human-verified' from per-event flags; older ground-truth files have none."""
    events = {(e["video"], e["start_sec"], e["end_sec"]): e.get("verification")
              for c in meta.get("cases", []) if c.get("measurable", True) for e in c.get("events", [])}
    if not events or all(v is None for v in events.values()):
        return "verification not recorded"
    verified = sum(v == "human_verified" for v in events.values())
    provisional = sum(v == "provisional_single_reviewer" for v in events.values())
    contested = len({(e["video"], e["start_sec"], e["end_sec"]) for c in meta.get("cases", [])
                     for e in c.get("ignore_events", [])})
    text = f"{verified} of {len(events)} events human-verified"
    if provisional:
        text += f", {provisional} provisional (single reviewer, not independently verified)"
    if contested:
        text += f", {contested} contested region(s) not scored"
    return text + "; the rest are publisher labels only"


def durations_for(truth: Path, events_file: Path | None) -> dict[str, float]:
    if events_file and events_file.is_file():
        return {c["video"]: c["duration_sec"] for c in json.loads(events_file.read_text(encoding="utf-8"))["clips"]}
    return {}


def record_live_scan(queries, out: Path, reviewer=None, caviar: Path | None = None) -> int:
    """Scene-scan every measurable query over the prepared CAVIAR library (paid when reviewer is None)."""
    import time
    from tanya import scenario_scan
    from tanya.config import Settings, load_search_settings
    from tanya.sentry_client import SearchError
    caviar = caviar or PROJECT / "data/cctv_validation/caviar"
    settings = Settings(caviar / "videos", caviar / "frames", caviar / "videos.db")
    # Only a real (paid) run needs the search environment and key; an injected reviewer needs neither.
    search_settings = load_search_settings() if reviewer is None else None
    results = {}
    for q in queries:
        started, batches = time.monotonic(), []
        try:
            plan = scenario_scan.build_library_plan(settings, q.query)
            for batch in range(plan["max_calls"]):
                batches.append(scenario_scan.run_batch(plan, batch, settings, search_settings, reviewer))
            results[q.query] = dict(status="ok", latency_sec=round(time.monotonic() - started, 2), batches=batches)
        except (SearchError, ValueError) as error:
            results[q.query] = dict(status="failed", latency_sec=round(time.monotonic() - started, 2),
                                    batches=batches, error=str(error))
        print(f"{results[q.query]['status']:6s} {q.query}", flush=True)
    engine = "scene scan: " + __import__("os").environ.get("TANYA_VERIFY_MODEL", "gemini-3.8-flash")
    out.write_text(json.dumps(benchmark.scan_run_from_results(results, engine), indent=2) + "\n", encoding="utf-8")
    print(f"saved {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ground-truth", type=Path, default=DEFAULT_TRUTH)
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS, help="clip durations for the ceiling/plan")
    p.add_argument("--ranked", type=Path, help="ranked-search run record")
    p.add_argument("--scan", type=Path, help="scene-scan run record")
    p.add_argument("--ranked-recording", type=Path, help="recorded bridge responses, replayed as ranked windows")
    p.add_argument("--checked-recording", type=Path,
                   help="recorded ranked retrieval + image-check results, replayed (mode ranked_checked)")
    p.add_argument("--merge-ratio", type=float, default=0.5)
    p.add_argument("--plan", action="store_true", help="print exact upload/request bounds for a live run")
    p.add_argument("--json", type=Path, help="also write the full report as JSON")
    p.add_argument("--record-live-scan", type=Path, metavar="OUT",
                   help="PAID: run scene scan for every measurable query over the prepared CAVIAR library and "
                        "save a run record to OUT. Refused without --approve-api-calls.")
    p.add_argument("--approve-api-calls", action="store_true",
                   help="explicit approval to send sampled frames and queries to the image-check model")
    args = p.parse_args()
    try:
        queries, unlabelled = benchmark.load_queries(args.ground_truth)
        ranked = (ranked_run_from_recording(args.ranked_recording, args.merge_ratio) if args.ranked_recording
                  else benchmark.load_run(args.ranked, "ranked"))
        scan = benchmark.load_run(args.scan, "scan")
    except (OSError, ValueError, KeyError) as error:
        print(f"Cannot run the benchmark: {error}", file=sys.stderr)
        return 1
    # Durations come from the matching events file: the default one, or one passed explicitly with --events.
    events_file = args.events if (args.ground_truth == DEFAULT_TRUTH or args.events != DEFAULT_EVENTS) else None
    durations = durations_for(args.ground_truth, events_file)
    if args.plan:
        if not durations:
            print("--plan needs clip durations (the default CAVIAR dataset).", file=sys.stderr)
            return 1
        print(json.dumps(benchmark.live_plan(queries, durations, USD_PER_FRAME), indent=2))
        print("Nothing was sent. Image-check pricing is not stored in this project; confirm the current "
              "per-image/token price for the configured model before approving.")
        return 0
    if args.record_live_scan:
        if not args.approve_api_calls:
            print("Refused: --record-live-scan sends sampled frames to Google. Review --plan, then add "
                  "--approve-api-calls to approve the charges.", file=sys.stderr)
            return 2
        return record_live_scan(queries, args.record_live_scan)
    results = [benchmark.score_mode(queries, ranked, "ranked"), benchmark.score_mode(queries, scan, "scan")]
    if scan and any(w.get("evidence_start_sec") is not None for r in scan["responses"].values()
                    for w in r.get("windows", [])):
        results.append(benchmark.score_mode(queries, scan, "scan", use_evidence_span=True))
    if args.checked_recording:
        checked = checked_run_from_recording(args.checked_recording)
        results += [benchmark.score_mode(queries, checked, "ranked_checked"),
                    benchmark.score_mode(queries, checked, "ranked_checked", use_evidence_span=True)]
    comparison = benchmark.compare(results[0], results[1])     # ranked vs scan, on queries both answered
    ceil = benchmark.ceiling(queries, durations) if durations else dict(events=0, rows=[], summary={})
    meta = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    dataset = dict(name=args.ground_truth.name, clips=len(durations) or "?",
                   events=len({(e.video, e.start_sec, e.end_sec) for q in queries for e in q.events}),
                   verification=verification_summary(meta),
                   positive=sum(q.positive for q in queries), negative=sum(not q.positive for q in queries))
    if durations:
        print(benchmark.format_report(dataset, results, comparison, ceil, unlabelled))
    else:
        print(benchmark.format_report(dataset, results, comparison,
                                      dict(events=0, summary=dict.fromkeys(
                                          ["median_event_sec", "events_under_4s", "chunk_iou_ge_0_3",
                                           "chunk_iou_ge_0_5", "scan_iou_ge_0_3", "scan_iou_ge_0_5",
                                           "scan_events_with_0_sampled_frames",
                                           "scan_events_with_1_sampled_frame"])), unlabelled))
    if args.json:
        args.json.write_text(json.dumps(dict(dataset=dataset, results=[r.__dict__ for r in results],
                                             comparison=comparison, ceiling=ceil, unlabelled=unlabelled),
                                        indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
