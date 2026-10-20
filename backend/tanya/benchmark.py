"""Real-footage search benchmark: ranked retrieval vs scene scan, scored against labelled events.

Inputs are a ground-truth file (tanya.real_dataset format: cases with measurable/query_kind/split)
and, per search mode, a *run record* of responses. A run record states where its outputs came
from ("live" inference saved at run time, or "replay" of an earlier recording) and holds, per
query, a status ("ok", "failed" or "unavailable"), latency and returned windows. A query with no
response is "unavailable": it is counted, never scored as a success or a miss.

Definitions (positive queries = measurable queries with at least one labelled event; negatives =
measurable queries with none; unlabelled queries are never scored):

- Hit@k: share of positive queries with any of the top-k windows overlapping a labelled event.
- Recall@k (event recall): labelled events overlapped by the top-k windows / all labelled events
  of that query, averaged over positive queries.
- Precision@k: overlapping windows among the top-k returned, averaged over positive queries.
- Loc@k IoU>=t: share of positive queries whose top-k contains a window with IoU >= t against a
  labelled event in the same video (timestamp localisation, not just overlap).
- Missed-event rate: share of positive queries with no overlapping window in the top 5
  (ranked) or no "supported" window (scan).
- Negative false-positive rate: share of negative queries that produced a candidate presented as
  a match. Ranked search always returns its nearest windows, so its rate is 1.0 by design; the
  scene scan counts a negative as a false positive only when it marks a window "supported".

Scene-scan "supported" windows are AI-supported *candidates* from sampled frames, not verified
detections. Nothing here calls a model or a network service.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

KS = (1, 5)
IOU_THRESHOLDS = (0.3, 0.5)
MODES = ("ranked", "scan", "ranked_checked")   # ranked_checked = ranked retrieval + image check
CHECKED_MODES = ("scan", "ranked_checked")       # windows carry a verdict; only "supported" counts
SOURCES = ("live", "replay")

# Structural parameters of the current pipeline (see search_sync / scenario_scan / indexer).
CHUNK_SEC, CHUNK_OVERLAP_SEC = 10.0, 2.0
SCAN_WINDOW_SEC, SCAN_STRIDE_SEC, SCAN_MAX_FRAMES = 12.0, 6.0, 6
FRAME_INTERVAL_SEC = 1.0


@dataclass(frozen=True)
class Span:
    video: str
    start_sec: float
    end_sec: float


@dataclass
class Query:
    query: str
    kind: str
    split: str
    events: list[Span]
    ignore: list[Span] = field(default_factory=list)   # contested regions (rejected labels): not scored

    @property
    def positive(self) -> bool:
        return bool(self.events)


@dataclass
class ModeResult:
    mode: str
    source: str | None
    engine: str | None
    counts: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    per_query: list = field(default_factory=list)


def load_queries(path: Path) -> tuple[list[Query], list[dict]]:
    """(measurable queries, unlabelled queries). Rejects malformed or out-of-order windows."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    measured, unlabelled, seen = [], [], set()
    for c in data["cases"]:
        if c["query"] in seen:
            raise ValueError(f"duplicate query: {c['query']!r}")
        seen.add(c["query"])
        if not c.get("measurable", True):
            unlabelled.append(dict(query=c["query"], kind=c.get("query_kind"), note=c.get("note", "")))
            continue
        events = [Span(e["video"], float(e["start_sec"]), float(e["end_sec"])) for e in c.get("events", [])]
        for e in events:
            if not 0 <= e.start_sec < e.end_sec:
                raise ValueError(f"invalid event window for {c['query']!r}: {e}")
        ignore = [Span(e["video"], float(e["start_sec"]), float(e["end_sec"])) for e in c.get("ignore_events", [])]
        measured.append(Query(c["query"], c.get("query_kind", "direct"), c.get("split", "test"), events, ignore))
    return measured, unlabelled


def load_run(path: Path | None, mode: str) -> dict | None:
    if path is None:
        return None
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    if run.get("mode") != mode:
        raise ValueError(f"{path}: run record is for mode {run.get('mode')!r}, expected {mode!r}")
    if run.get("source") not in SOURCES:
        raise ValueError(f"{path}: source must be one of {SOURCES} (synthetic or replayed outputs are "
                         "never presented as live inference)")
    return run


def overlap(a: Span, b: Span) -> float:
    return max(0.0, min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec)) if a.video == b.video else 0.0


def iou(a: Span, b: Span) -> float:
    inter = overlap(a, b)
    union = (a.end_sec - a.start_sec) + (b.end_sec - b.start_sec) - inter
    return inter / union if union > 0 else 0.0


def _windows(response: dict) -> list[tuple[Span, dict]]:
    out = []
    for w in response.get("windows", []):
        span = Span(w["video"], float(w["start_sec"]), float(w["end_sec"]))
        if not span.start_sec < span.end_sec:
            raise ValueError(f"invalid returned window {w}")
        out.append((span, w))
    return out


def _mean(values):
    values = list(values)
    return round(sum(values) / len(values), 3) if values else None


def score_mode(queries: list[Query], run: dict | None, mode: str, use_evidence_span: bool = False) -> ModeResult:
    """Score one mode. With use_evidence_span (scan only), a supported window that carries
    evidence_start_sec/evidence_end_sec is localised by that span instead of the scanned window."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    label = f"{mode} (evidence span)" if use_evidence_span else mode
    result = ModeResult(label, run and run.get("source"), run and run.get("engine"))
    responses = (run or {}).get("responses", {})
    status_counts = {"ok": 0, "failed": 0, "unavailable": 0}
    latencies, per_query = [], []
    for q in queries:
        r = responses.get(q.query)
        status = r.get("status", "ok") if r else "unavailable"
        if status not in status_counts:
            raise ValueError(f"unknown status {status!r} for {q.query!r}")
        status_counts[status] += 1
        row = dict(query=q.query, kind=q.kind, split=q.split, positive=q.positive, status=status)
        if status == "ok":
            if r.get("latency_sec") is not None:
                latencies.append(float(r["latency_sec"]))
            windows = _windows(r)
            if mode in CHECKED_MODES:     # only "supported" windows are presented as candidate matches
                windows = [(s, w) for s, w in windows if w.get("verdict") == "supported"]
                if use_evidence_span:
                    windows = [(Span(s.video, float(w["evidence_start_sec"]), float(w["evidence_end_sec"]))
                                if w.get("evidence_start_sec") is not None else s, w) for s, w in windows]
            row.update(_score_query(q, [s for s, _ in windows], mode))
        per_query.append(row)
    result.per_query = per_query
    ok = [p for p in per_query if p["status"] == "ok"]
    pos, neg = [p for p in ok if p["positive"]], [p for p in ok if not p["positive"]]
    result.counts = dict(queries=len(queries), positive=sum(q.positive for q in queries),
                         negative=sum(not q.positive for q in queries), scored_positive=len(pos),
                         scored_negative=len(neg), **status_counts)
    m = {}
    for k in KS:
        m[f"hit@{k}"] = _mean(p[f"hit@{k}"] for p in pos)
        m[f"recall@{k}"] = _mean(p[f"recall@{k}"] for p in pos)
        m[f"precision@{k}"] = _mean(p[f"precision@{k}"] for p in pos if p[f"precision@{k}"] is not None)
        for t in IOU_THRESHOLDS:
            m[f"loc@{k}_iou>={t}"] = _mean(p[f"loc@{k}_iou>={t}"] for p in pos)
    m["missed_event_rate"] = _mean(p["missed"] for p in pos)
    m["negative_false_positive_rate"] = _mean(p["false_positive"] for p in neg)
    m["latency_sec_median"] = round(statistics.median(latencies), 2) if latencies else None
    m["latency_sec_mean"] = _mean(latencies)
    result.metrics = m
    return result


def _score_query(q: Query, windows: list[Span], mode: str) -> dict:
    # A window inside a contested (rejected-label) region that does not touch a labelled event is
    # neither right nor wrong: it is removed before ranking metrics, so it cannot count as a false hit.
    windows = [w for w in windows if any(overlap(w, e) > 0 for e in q.events)
               or not any(overlap(w, c) > 0 for c in q.ignore)]
    out = {}
    if not q.positive:
        out["false_positive"] = 1.0 if windows else 0.0
        return out
    for k in KS:
        top = windows[:k]
        relevant = [w for w in top if any(overlap(w, e) > 0 for e in q.events)]
        out[f"hit@{k}"] = 1.0 if relevant else 0.0
        out[f"recall@{k}"] = sum(any(overlap(w, e) > 0 for w in top) for e in q.events) / len(q.events)
        out[f"precision@{k}"] = len(relevant) / len(top) if top else None
        best = max((iou(w, e) for w in top for e in q.events), default=0.0)
        for t in IOU_THRESHOLDS:
            out[f"loc@{k}_iou>={t}"] = 1.0 if best >= t else 0.0
    horizon = windows if mode in CHECKED_MODES else windows[:5]
    out["missed"] = 0.0 if any(overlap(w, e) > 0 for w in horizon for e in q.events) else 1.0
    return out


def scan_run_from_results(results: dict[str, dict], engine: str) -> dict:
    """Run record from scene-scan outputs ({query: {"status", "latency_sec", "batches": [batch...]}}),
    where each batch is the /api/search/scan/batch result (hits / unclear_hits / rejected_hits)."""
    responses = {}
    for query, r in results.items():
        windows = []
        for batch in r.get("batches", []):
            for key in ("hits", "unclear_hits", "rejected_hits"):
                for hit in batch.get(key, []):
                    review = hit.get("visual_review") or {}
                    span = review.get("evidence_span") or {}
                    windows.append(dict(video=hit["filename"], start_sec=hit["start_sec"], end_sec=hit["end_sec"],
                                        verdict=review.get("verdict"), scan_window=hit.get("scan_window"),
                                        evidence_start_sec=span.get("start_sec"), evidence_end_sec=span.get("end_sec")))
        windows.sort(key=lambda w: (w["verdict"] != "supported", w.get("scan_window") or 0))
        responses[query] = dict(status=r.get("status", "ok"), latency_sec=r.get("latency_sec"), windows=windows,
                                **({"error": r["error"]} if r.get("error") else {}))
    return dict(mode="scan", source="live", engine=engine, responses=responses)


def compare(a: ModeResult, b: ModeResult) -> dict:
    """Metrics restricted to queries both modes answered ("ok"), so they are comparable."""
    both = {p["query"] for p in a.per_query if p["status"] == "ok"} & {p["query"] for p in b.per_query if p["status"] == "ok"}
    if not both:
        return dict(common_queries=0, note="No query was answered by both modes; no comparison is possible.")
    out = dict(common_queries=len(both))
    for r in (a, b):
        pos = [p for p in r.per_query if p["query"] in both and p["positive"]]
        neg = [p for p in r.per_query if p["query"] in both and not p["positive"]]
        out[r.mode] = dict(positive=len(pos), negative=len(neg), hit_at_1=_mean(p["hit@1"] for p in pos),
                           loc_at_1_iou_0_5=_mean(p["loc@1_iou>=0.5"] for p in pos),
                           missed_event_rate=_mean(p["missed"] for p in pos),
                           negative_false_positive_rate=_mean(p["false_positive"] for p in neg))
    return out


# --------------------------------------------------------------------------- structural ceiling


def chunk_spans(duration: float) -> list[tuple[float, float]]:
    """Ranked-search chunks (mirrors search_sync.expected_chunk_spans)."""
    if duration <= CHUNK_SEC:
        return [(0.0, duration)]
    step, spans, start = CHUNK_SEC - CHUNK_OVERLAP_SEC, [], 0.0
    while start < duration:
        spans.append((start, min(start + CHUNK_SEC, duration)))
        start += step
        if start + CHUNK_OVERLAP_SEC >= duration:
            break
    return spans


def scan_spans(duration: float) -> list[tuple[float, float]]:
    """Scene-scan windows (mirrors scenario_scan.build_plan)."""
    count = max(1, math.ceil(max(0.0, duration - SCAN_WINDOW_SEC) / SCAN_STRIDE_SEC) + 1)
    return [(i * SCAN_STRIDE_SEC, min(duration, i * SCAN_STRIDE_SEC + SCAN_WINDOW_SEC)) for i in range(count)]


def scan_samples(lo: float, hi: float, duration: float) -> list[float]:
    """Frames the scan would send for one window (mirrors visual_review.frame_samples on 1 s frames)."""
    frames = [t * FRAME_INTERVAL_SEC for t in range(int(duration / FRAME_INTERVAL_SEC) + 1)
              if lo <= t * FRAME_INTERVAL_SEC <= hi and t * FRAME_INTERVAL_SEC < duration]
    n = min(SCAN_MAX_FRAMES, len(frames))
    chosen = {min(frames, key=lambda f: abs(f - (lo + (hi - lo) * i / max(n - 1, 1)))) for i in range(n)}
    return sorted(chosen)


def ceiling(queries: list[Query], durations: dict[str, float]) -> dict:
    """Best-case timestamp IoU and frame coverage the current windowing allows, with a perfect ranker.

    This is an upper bound from window geometry only; it is not a measurement of any model.
    """
    rows = []
    events = {(e.video, e.start_sec, e.end_sec) for q in queries for e in q.events}
    for video, start, end in sorted(events):
        ev, duration = Span(video, start, end), durations[video]
        best_chunk = max(iou(Span(video, a, b), ev) for a, b in chunk_spans(duration))
        scan = [(Span(video, a, b), scan_samples(a, b, duration)) for a, b in scan_spans(duration)]
        best_scan = max(iou(s, ev) for s, _ in scan)
        best_frames = max(sum(start <= t < end for t in samples) for _, samples in scan)
        rows.append(dict(video=video, start_sec=start, end_sec=end, duration_sec=round(end - start, 2),
                         best_chunk_iou=round(best_chunk, 3), best_scan_iou=round(best_scan, 3),
                         max_sampled_frames_in_event=best_frames))
    n = len(rows)
    share = lambda pred: round(sum(map(pred, rows)) / n, 3) if n else None  # noqa: E731
    return dict(events=n, rows=rows, summary=dict(
        median_event_sec=round(statistics.median(r["duration_sec"] for r in rows), 2) if n else None,
        events_under_4s=sum(r["duration_sec"] < 4 for r in rows),
        chunk_iou_ge_0_3=share(lambda r: r["best_chunk_iou"] >= 0.3),
        chunk_iou_ge_0_5=share(lambda r: r["best_chunk_iou"] >= 0.5),
        scan_iou_ge_0_3=share(lambda r: r["best_scan_iou"] >= 0.3),
        scan_iou_ge_0_5=share(lambda r: r["best_scan_iou"] >= 0.5),
        scan_events_with_0_sampled_frames=sum(r["max_sampled_frames_in_event"] == 0 for r in rows),
        scan_events_with_1_sampled_frame=sum(r["max_sampled_frames_in_event"] == 1 for r in rows)))


def live_plan(queries: list[Query], durations: dict[str, float], usd_per_embedding_frame: float) -> dict:
    """Exact upload/request bounds for a live run on this dataset (nothing is sent here)."""
    chunks = sum(len(chunk_spans(d)) for d in durations.values())
    frames = sum(round(b - a) for d in durations.values() for a, b in chunk_spans(d))
    windows = sum(len(scan_spans(d)) for d in durations.values())
    n = len(queries)
    return dict(
        ranked=dict(index_chunks=chunks, index_billed_frames=frames,
                    index_estimated_usd=round(frames * usd_per_embedding_frame, 4),
                    query_embedding_requests=n, uploads="each video once, as chunks, to Gemini Embedding"),
        scan=dict(queries=n, windows_per_query=windows, max_images_per_query=windows * SCAN_MAX_FRAMES,
                  max_requests_per_query=math.ceil(windows / 5), max_images_total=n * windows * SCAN_MAX_FRAMES,
                  max_requests_total=n * math.ceil(windows / 5),
                  uploads="sampled JPEG frames (<=1024 px) plus the query text to the image-check model"))


def format_report(dataset: dict, results: list[ModeResult], comparison: dict, ceil: dict, unlabelled: list) -> str:
    lines = [f"Dataset: {dataset['name']} - {dataset['clips']} clips, {dataset['events']} labelled events "
             f"({dataset['verification']})",
             f"Queries: {dataset['positive']} positive, {dataset['negative']} negative, "
             f"{len(unlabelled)} unlabelled (not scored)", ""]
    for r in results:
        c = r.counts
        lines.append(f"[{r.mode}] source={r.source or 'none'} engine={r.engine or '-'}: "
                     f"{c['ok']} ok, {c['failed']} failed, {c['unavailable']} unavailable of {c['queries']}")
        if not c["ok"]:
            lines.append("  No results: live inference was not run for this mode (requires an approved paid run).")
            continue
        m = r.metrics
        lines.append(f"  positives scored {c['scored_positive']}/{c['positive']}: hit@1 {m['hit@1']}, hit@5 {m['hit@5']}, "
                     f"recall@1 {m['recall@1']}, recall@5 {m['recall@5']}, P@1 {m['precision@1']}, P@5 {m['precision@5']}")
        lines.append(f"  localisation: loc@1 IoU>=0.3 {m['loc@1_iou>=0.3']}, IoU>=0.5 {m['loc@1_iou>=0.5']}; "
                     f"loc@5 IoU>=0.3 {m['loc@5_iou>=0.3']}, IoU>=0.5 {m['loc@5_iou>=0.5']}")
        lines.append(f"  missed-event rate {m['missed_event_rate']}; negatives scored {c['scored_negative']}/{c['negative']}: "
                     f"false-positive rate {m['negative_false_positive_rate']}; latency median {m['latency_sec_median']} s")
    lines += ["", f"Comparison on common answered queries: {json.dumps(comparison)}", "",
              f"Structural ceiling (window geometry only, perfect ranker; not a model measurement), "
              f"{ceil['events']} events:"]
    s = ceil["summary"]
    lines += [f"  median event {s['median_event_sec']} s; {s['events_under_4s']} events shorter than 4 s",
              f"  ranked 10 s chunks: best IoU>=0.3 for {s['chunk_iou_ge_0_3']}, >=0.5 for {s['chunk_iou_ge_0_5']} of events",
              f"  scan 12 s windows:  best IoU>=0.3 for {s['scan_iou_ge_0_3']}, >=0.5 for {s['scan_iou_ge_0_5']} of events",
              f"  scan sampling: {s['scan_events_with_0_sampled_frames']} events get no sampled frame, "
              f"{s['scan_events_with_1_sampled_frame']} get exactly one"]
    if unlabelled:
        lines += ["", "Unlabelled (unmeasured) queries: " + "; ".join(u["query"] for u in unlabelled)]
    return "\n".join(lines)
