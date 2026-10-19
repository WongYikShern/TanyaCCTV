"""Retrieval evaluation against annotated ground truth (recall@K, precision@K, timing error).

A result is *relevant* when its time window overlaps an annotated event in the same video.
Metrics are computed both for raw 10 s search chunks and for TanyaCCTV's merged windows.

These numbers describe ranking quality on a given annotated set only. They are not detection
accuracy, and similarity scores are never treated as probabilities. Queries with no annotated
event ("negative" queries) have no precision/recall: the engine always returns its nearest
clips, so they are reported separately and never counted as correct rejections.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .search import Chunk, merge_chunks

DEFAULT_KS = (1, 3, 5)


@dataclass(frozen=True)
class Event:
    video: str          # file name of the recording
    start_sec: float
    end_sec: float


@dataclass
class Case:
    query: str
    events: list[Event]  # empty = negative query
    event_type: str = "unspecified"


@dataclass(frozen=True)
class Window:
    video: str
    start_sec: float
    end_sec: float
    score: float


@dataclass
class QueryResult:
    query: str
    level: str                      # "chunks" or "merged"
    negative: bool
    returned: int
    event_type: str = "unspecified"
    hit_at: dict = field(default_factory=dict)
    precision_at: dict = field(default_factory=dict)
    recall_at: dict = field(default_factory=dict)
    reciprocal_rank: float | None = None
    first_relevant: dict | None = None   # window, matched event, start/end error, IoU
    top_window: dict | None = None


# --------------------------------------------------------------------------- ground truth


def load_ground_truth(path: Path) -> list[Case]:
    """JSON ({"cases": [{"query", "events": [{"video","start_sec","end_sec"}]}]}) or the
    docs/cctv-validation-template.csv format (rows sharing a query are one case)."""
    if path.suffix.lower() == ".csv":
        return _load_template_csv(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for c in data["cases"]:
        events = [Event(e["video"], float(e["start_sec"]), float(e["end_sec"])) for e in c.get("events", [])]
        cases.append(Case(c["query"], events, c.get("event_type") or ("negative" if not events else "unspecified")))
    _validate(cases)
    return cases


def _load_template_csv(path: Path) -> list[Case]:
    by_query: dict[str, Case] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            query = (row.get("query") or "").strip()
            if not query:
                continue
            case = by_query.setdefault(query, Case(query, []))
            video = (row.get("expected_video_alias") or "").strip()
            start, end = (row.get("expected_start_sec") or "").strip(), (row.get("expected_end_sec") or "").strip()
            if video and start and end:   # blank expected window = negative / absent case
                case.events.append(Event(video, float(start), float(end)))
    cases = list(by_query.values())
    _validate(cases)
    return cases


def _validate(cases: list[Case]) -> None:
    seen = set()
    for c in cases:
        if not c.query.strip():
            raise ValueError("ground truth contains an empty query")
        if c.query in seen:
            raise ValueError(f"duplicate query in ground truth: {c.query!r}")
        seen.add(c.query)
        for e in c.events:
            if not 0 <= e.start_sec < e.end_sec:
                raise ValueError(f"invalid event window for {c.query!r}: {e}")


# --------------------------------------------------------------------------- metrics


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def iou(w: Window, e: Event) -> float:
    inter = overlap(w.start_sec, w.end_sec, e.start_sec, e.end_sec)
    union = max(w.end_sec, e.end_sec) - min(w.start_sec, e.start_sec)
    return inter / union if union > 0 else 0.0


def matches(w: Window, e: Event) -> bool:
    return w.video == e.video and overlap(w.start_sec, w.end_sec, e.start_sec, e.end_sec) > 0


def score_case(case: Case, windows: list[Window], level: str, ks=DEFAULT_KS,
               *, min_iou: float = 0.0) -> QueryResult:
    """Metrics for ranked windows; min_iou adds a timing requirement to overlap relevance."""
    if not 0 <= min_iou <= 1:
        raise ValueError("min_iou must be between 0 and 1")
    def relevant_event(window, event):
        return matches(window, event) and (min_iou == 0 or iou(window, event) >= min_iou)
    result = QueryResult(case.query, level, negative=not case.events, event_type=case.event_type,
                         returned=len(windows))
    if windows:
        top = windows[0]
        result.top_window = asdict(top)
    if not case.events:
        return result
    relevant = [any(relevant_event(w, e) for e in case.events) for w in windows]
    for k in ks:
        top_k = relevant[:k]
        result.hit_at[k] = any(top_k)
        result.precision_at[k] = (sum(top_k) / len(top_k)) if top_k else 0.0
        found = {i for i, e in enumerate(case.events) if any(relevant_event(w, e) for w in windows[:k])}
        result.recall_at[k] = len(found) / len(case.events)
    first = next((i for i, r in enumerate(relevant) if r), None)
    result.reciprocal_rank = 1 / (first + 1) if first is not None else 0.0
    if first is not None:
        w = windows[first]
        e = max((e for e in case.events if relevant_event(w, e)), key=lambda e: iou(w, e))
        result.first_relevant = {
            "rank": first + 1, "window": asdict(w), "event": asdict(e),
            "start_error_sec": round(abs(w.start_sec - e.start_sec), 3),
            "end_error_sec": round(abs(w.end_sec - e.end_sec), 3),
            "iou": round(iou(w, e), 3),
        }
    return result


# --------------------------------------------------------------------------- from search responses


def chunk_windows(bridge_results: list[dict]) -> list[Window]:
    """Raw bridge results (ranked chunks) -> windows, keyed by file name."""
    return [Window(r["filename"], float(r["start_sec"]), float(r["end_sec"]), float(r["score"]))
            for r in bridge_results]


def merged_windows(bridge_results: list[dict], ratio: float = 0.5, gap_sec: float = 0.0) -> list[Window]:
    """Apply TanyaCCTV's grouping (search.merge_chunks) per video, ranked by best score."""
    by_video: dict[str, list[Chunk]] = {}
    for r in bridge_results:
        by_video.setdefault(r["filename"], []).append(
            Chunk(r["rank"], float(r["start_sec"]), float(r["end_sec"]), float(r["score"]),
                  float(r["score_above_median"])))
    windows = []
    for video, chunks in by_video.items():
        for group in merge_chunks(chunks, ratio, gap_sec):
            windows.append(Window(video, min(c.start_sec for c in group), max(c.end_sec for c in group),
                                  max(c.score for c in group)))
    return sorted(windows, key=lambda w: -w.score)


def restrict_to_index(cases: list[Case], indexed_videos) -> tuple[list[Case], list[dict]]:
    """Drop annotated events in videos the recorded index did not contain.

    Such events could never be retrieved, so counting them as misses would be wrong. They are
    returned as "not_indexed". A positive query whose events are all outside the index becomes
    unmeasurable (it must not be scored as a negative query).
    """
    indexed = set(indexed_videos)
    kept, not_indexed = [], []
    for c in cases:
        inside = [e for e in c.events if e.video in indexed]
        not_indexed += [{"query": c.query, **asdict(e)} for e in c.events if e.video not in indexed]
        if c.events and not inside:
            continue
        kept.append(Case(c.query, inside, c.event_type))
    return kept, not_indexed


def evaluate(cases: list[Case], responses: dict[str, list[dict]], ks=DEFAULT_KS,
             ratio: float = 0.5, gap_sec: float = 0.0, allow_missing: bool = False,
             indexed_videos=None) -> dict:
    """Evaluate bridge responses ({query: ranked results}) at chunk and merged level.

    With allow_missing, queries without a response are listed under "not_measured" instead of
    raising; they are never counted as hits or misses. With indexed_videos (the videos the
    recorded index contained), events in other videos are excluded and listed as not indexed.
    """
    all_cases, not_indexed = cases, []
    if indexed_videos is not None:
        cases, not_indexed = restrict_to_index(cases, indexed_videos)
    unmeasurable = [c for c in all_cases if c.query not in {k.query for k in cases}]
    missing = [c.query for c in cases if c.query not in responses]
    if missing and not allow_missing:
        raise ValueError("no recorded response for: " + ", ".join(missing))
    measured = [c for c in cases if c.query in responses]
    per_query, analysis = [], []
    localized = {"0.3": [], "0.5": []}
    for case in measured:
        results = responses[case.query]
        merged = merged_windows(results, ratio, gap_sec)
        chunks = chunk_windows(results)
        per_query.append(score_case(case, chunks, "chunks", ks))
        for threshold, scored in localized.items():
            for level, windows in (("chunks", chunks), ("merged", merged)):
                scored.append(score_case(case, windows, level, ks, min_iou=float(threshold)))
        per_query.append(score_case(case, merged, "merged", ks))
        analysis.append(error_analysis(case, merged, all_cases, k=max(ks)))
    by_type = {t: summarise([q for q in per_query if q.level == "merged" and q.event_type == t], ks)
               for t in sorted({c.event_type for c in measured})}
    return {"ks": list(ks), "per_query": [asdict(q) for q in per_query],
            "summary": {level: summarise([q for q in per_query if q.level == level], ks)
                        for level in ("chunks", "merged")},
            "by_event_type": by_type, "analysis": analysis,
            "localization": {threshold: {
                "summary": {level: summarise([q for q in scored if q.level == level], ks)
                            for level in ("chunks", "merged")},
                "per_query": [asdict(q) for q in scored]}
                for threshold, scored in localized.items()},
            "not_measured": [{"query": c.query, "event_type": c.event_type,
                              "reason": "no recorded response"} for c in cases if c.query in missing]
                            + [{"query": c.query, "event_type": c.event_type,
                                "reason": "its videos were not in the recorded index"} for c in unmeasurable],
            "not_indexed_events": not_indexed}


def error_analysis(case: Case, windows: list[Window], all_cases: list[Case], k: int = 5) -> dict:
    """What the top-k windows actually were, and which annotated events were missed.

    A non-relevant window is labelled with any *other* annotated event it overlaps (a confusion),
    or "background" when it overlaps no annotated event at all.
    """
    annotated = [(c.query, e) for c in all_cases for e in c.events]
    false_positives = []
    for rank, w in enumerate(windows[:k], start=1):
        if any(matches(w, e) for e in case.events):
            continue
        overlaps = sorted({q for q, e in annotated if q != case.query and matches(w, e)})
        false_positives.append({"rank": rank, "video": w.video, "start_sec": w.start_sec, "end_sec": w.end_sec,
                                "overlaps": overlaps or ["background"]})
    missed = [asdict(e) for e in case.events if not any(matches(w, e) for w in windows[:k])]
    return {"query": case.query, "event_type": case.event_type, "negative": not case.events, "k": k,
            "false_positives": false_positives, "missed_events": missed}


def summarise(results: list[QueryResult], ks=DEFAULT_KS) -> dict:
    positive = [r for r in results if not r.negative]
    n = len(positive)
    found = [r.first_relevant for r in positive if r.first_relevant]

    def mean(values):
        values = list(values)
        return round(sum(values) / len(values), 3) if values else None

    return {
        "positive_queries": n,
        "negative_queries": len(results) - n,
        "hit_rate_at": {k: mean(r.hit_at[k] for r in positive) for k in ks},
        "mean_precision_at": {k: mean(r.precision_at[k] for r in positive) for k in ks},
        "mean_recall_at": {k: mean(r.recall_at[k] for r in positive) for k in ks},
        "mrr": mean(r.reciprocal_rank for r in positive),
        "mean_start_error_sec": mean(f["start_error_sec"] for f in found),
        "mean_end_error_sec": mean(f["end_error_sec"] for f in found),
        "mean_iou": mean(f["iou"] for f in found),
    }


def format_report(report: dict) -> str:
    ks = report["ks"]
    lines = []
    for level, title in (("chunks", "Raw 10 s chunks"), ("merged", "TanyaCCTV merged windows")):
        s = report["summary"][level]
        lines += [f"{title}: {s['positive_queries']} positive, {s['negative_queries']} negative query(ies)",
                  "  " + "  ".join(f"hit@{k} {s['hit_rate_at'][k]}" for k in ks),
                  "  " + "  ".join(f"P@{k} {s['mean_precision_at'][k]}" for k in ks),
                  "  " + "  ".join(f"R@{k} {s['mean_recall_at'][k]}" for k in ks),
                  f"  MRR {s['mrr']}  first-relevant timing: start error {s['mean_start_error_sec']} s, "
                  f"end error {s['mean_end_error_sec']} s, IoU {s['mean_iou']}", ""]
    if report.get("localization"):
        lines.append("Temporal localization (same-video overlap plus minimum IoU; diagnostic thresholds, not detector acceptance criteria):")
        for threshold, measured in report["localization"].items():
            for level in ("chunks", "merged"):
                summary = measured["summary"][level]
                k = max(ks)
                lines.append(f"  IoU >= {threshold}, {level}: hit@{ks[0]} {summary['hit_rate_at'][ks[0]]}, "
                             f"P@{k} {summary['mean_precision_at'][k]}, R@{k} {summary['mean_recall_at'][k]}")
        lines.append("  Negative queries are excluded from these positive-event metrics; these do not measure absence.")
        lines.append("")
    lines.append("Per query (merged windows):")
    for q in report["per_query"]:
        if q["level"] != "merged":
            continue
        top = q["top_window"]
        top_text = f"{top['video']} {top['start_sec']:g}-{top['end_sec']:g}s" if top else "no results"
        if q["negative"]:
            lines.append(f"  [negative] {q['query']!r}: top {top_text} (nearest clip; not evidence of the event)")
        else:
            fr = q["first_relevant"]
            timing = (f"first relevant at rank {fr['rank']}, IoU {fr['iou']}" if fr else "no relevant window")
            lines.append(f"  {q['query']!r}: top {top_text}; {timing}")
    if report.get("by_event_type"):
        lines.append("\nBy event type (merged windows; positive queries only):")
        for event_type, s in report["by_event_type"].items():
            if s["positive_queries"]:
                lines.append(f"  {event_type}: {s['positive_queries']} query(ies), hit@1 {s['hit_rate_at'][ks[0]]}, "
                             f"MRR {s['mrr']}, mean IoU {s['mean_iou']}")
    if report.get("analysis"):
        lines.append("\nNon-matching results in the top windows (false positives) and missed events:")
        for a in report["analysis"]:
            fps = "; ".join(f"#{f['rank']} {f['video']} {f['start_sec']:g}-{f['end_sec']:g}s ({', '.join(f['overlaps'])})"
                            for f in a["false_positives"]) or "none"
            missed = ", ".join(f"{m['video']} {m['start_sec']:g}-{m['end_sec']:g}s" for m in a["missed_events"]) or "none"
            lines.append(f"  {a['query']!r}: non-matching in top {a['k']}: {fps}; missed: {missed}")
    if report.get("not_measured"):
        lines.append("\nNot measured (counted neither as hits nor misses): "
                     + "; ".join(f"{m['query']!r} [{m['event_type']}]: {m['reason']}" for m in report["not_measured"]))
    if report.get("not_indexed_events"):
        lines.append(f"Annotated events outside the recorded index (excluded): {len(report['not_indexed_events'])}")
    lines.append("\nRanking quality on this annotated set only; not detection accuracy. "
                 "Scores are ranking signals, not probabilities.")
    return "\n".join(lines)
