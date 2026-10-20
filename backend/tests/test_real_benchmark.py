"""Real-footage dataset and benchmark: label derivation, manifest validation, metrics, safety.

Synthetic fixtures test the logic only; they are never evidence of real-world accuracy.
"""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tanya import benchmark, real_dataset, scenario_scan, search_sync
from tanya.config import Settings
from tanya.evaluation import evaluate, load_ground_truth
from tanya.indexer import Indexer
from tanya.visual_review import evidence_span
from tests.conftest import make_video

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
import run_benchmark  # noqa: E402


# --------------------------------------------------------------------------- CAVIAR label derivation


def caviar_xml(path: Path, frames: list[list[dict]], groups: dict[int, dict] | None = None) -> Path:
    """Minimal CAVIAR-format XML: frames[i] = list of {movement, context, situation} per person."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?><dataset name="t">']
    for i, people in enumerate(frames):
        objs = "".join(
            f'<object id="{j}"><box h="10" w="10" xc="5" yc="5"/><appearance>visible</appearance><hypothesislist>'
            f'<hypothesis evaluation="1.0" id="1" prev="0.0"><movement>{p["movement"]}</movement><role>walker</role>'
            f'<context>{p["context"]}</context><situation>{p["situation"]}</situation></hypothesis></hypothesislist></object>'
            for j, p in enumerate(people))
        g = (groups or {}).get(i)
        grp = (f'<group id="0"><hypothesislist><hypothesis evaluation="1.0" id="1" prev="0.0"><movement>active</movement>'
               f'<role>meeters</role><context>{g["context"]}</context><situation>{g["situation"]}</situation></hypothesis>'
               f'</hypothesislist></group>') if g else ""
        parts.append(f'<frame number="{i}"><objectlist>{objs}</objectlist><grouplist>{grp}</grouplist></frame>')
    path.write_text("".join(parts) + "</dataset>", encoding="utf-8")
    return path


def person(movement="walking", context="walking", situation="moving"):
    return dict(movement=movement, context=context, situation=situation)


def test_intervals_merge_short_gaps_and_drop_short_runs():
    flags = [True] * 25 + [False] * 10 + [True] * 25 + [False] * 30 + [True] * 5
    # 25 fps: 0-1 s, gap 0.4 s (merged), 1.4-2.4 s, gap 1.2 s, then a 0.2 s blip (dropped as < 1 s)
    assert real_dataset.intervals(flags) == [(0.0, 2.4)]
    assert real_dataset.intervals(flags, min_duration_sec=0.1) == [(0.0, 2.4), (3.6, 3.8)]
    assert real_dataset.intervals([False] * 10) == []


def test_track_level_context_does_not_define_the_moment(tmp_path):
    """Regression: CAVIAR 'context' labels a whole track; a future faller walking in is not 'fallen'."""
    walking_in = [[person(context="drop down")]] * 50             # 2 s walking, track labelled "drop down"
    on_floor = [[person(movement="inactive", context="drop down", situation="inactive")]] * 75
    entering = [[person(context="shop enter", situation="moving")]] * 25 + \
               [[person(context="shop enter", situation="shop enter")]] * 25
    xml = caviar_xml(tmp_path / "a.xml", walking_in + on_floor + entering)
    _, events = real_dataset.clip_events(xml)
    assert events["fallen"] == [(2.0, 5.0)]                       # not from 0 s
    assert events["standing_still"] == []                         # a fallen person is not "standing still"
    assert events["shop_enter"] == [(6.0, 7.0)]                   # situation, not the track context
    assert events["walking"] == [(0.0, 2.0), (5.0, 7.0)]


def test_group_situation_and_any_person(tmp_path):
    frames = [[person(), person()]] * 50 + [[]] * 25
    xml = caviar_xml(tmp_path / "g.xml", frames, {i: dict(context="meeting", situation="interacting")
                                                   for i in range(10, 40)})
    _, events = real_dataset.clip_events(xml)
    assert events["meeting"] == [(0.4, 1.6)]
    assert events["person_present"] == [(0.0, 2.0)]


def test_non_contiguous_frames_are_rejected(tmp_path):
    xml = tmp_path / "bad.xml"
    xml.write_text('<dataset><frame number="0"><objectlist/></frame><frame number="2"><objectlist/></frame></dataset>',
                   encoding="utf-8")
    with pytest.raises(ValueError, match="not contiguous"):
        real_dataset.frame_flags(xml)


def test_load_clips_reports_missing_footage(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"clips": [{"name": "Walk1"}]}), encoding="utf-8")
    (tmp_path / "media-manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Prepared video missing"):
        real_dataset.load_clips(tmp_path, plan)


# --------------------------------------------------------------------------- manifest validation


def test_manifest_validation_catches_bounds_and_presence_errors():
    good = dict(clip_id="c", dataset="CAVIAR", relative_path="v/a.mp4", duration_sec=10, resolution="1x1",
                licence="x", query="q", query_kind="direct", split="dev", annotation_confidence="u",
                event_start_sec=1.0, event_end_sec=2.0, event_present=True)
    assert real_dataset.validate_manifest_rows([good], {"a.mp4": 10}) == []
    bad = [dict(good, event_end_sec=12.0), dict(good, event_start_sec=None), dict(good, event_present=False),
           dict(good, event_start_sec=None, event_end_sec=None), dict(good, split="train"), dict(good, licence="")]
    problems = real_dataset.validate_manifest_rows(bad, {"a.mp4": 10})
    assert len(problems) == 7                      # row 1 is both half-set and "present without a window"
    assert {p.split(":")[0] for p in problems} == {f"row {i}" for i in range(6)}
    assert any("outside" in p for p in problems) and any("both be set" in p for p in problems)


def test_committed_caviar_dataset_is_consistent():
    events = json.loads((ROOT / "evaluation/datasets/caviar-events.json").read_text(encoding="utf-8"))
    durations = {c["video"]: c["duration_sec"] for c in events["clips"]}
    rows = [json.loads(line) for line in
            (ROOT / "evaluation/datasets/caviar-manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert real_dataset.validate_manifest_rows(rows, durations) == []
    assert events["licence"] and events["attribution"] and events["verification"] == real_dataset.UNVERIFIED
    queries, unlabelled = benchmark.load_queries(ROOT / "evaluation/caviar_ground_truth.json")
    kinds = {q.query: q.kind for q in queries}
    assert all(not q.events for q in queries if q.kind in ("negative", "hard_negative"))
    assert all(q.events for q in queries if q.kind in ("direct", "paraphrase"))
    assert {u["kind"] for u in unlabelled} <= {"appearance", "ambiguous"} and unlabelled
    assert {"dev", "test"} == {q.split for q in queries} and len(kinds) == len(queries)
    for q in queries:
        for e in q.events:
            assert 0 <= e.start_sec < e.end_sec <= durations[e.video] + 1e-6


# --------------------------------------------------------------------------- metrics


QUERIES = [benchmark.Query("walk", "direct", "dev", [benchmark.Span("a.mp4", 10, 14)]),
           benchmark.Query("fall", "direct", "test", [benchmark.Span("b.mp4", 2, 4), benchmark.Span("a.mp4", 30, 32)]),
           benchmark.Query("car", "negative", "test", [])]


def run(mode, responses, source="live"):
    return dict(mode=mode, source=source, engine="test", responses=responses)


def test_ranked_metrics_are_hand_checkable():
    r = benchmark.score_mode(QUERIES, run("ranked", {
        "walk": dict(status="ok", latency_sec=2.0, windows=[dict(video="a.mp4", start_sec=0, end_sec=10),
                                                            dict(video="a.mp4", start_sec=11, end_sec=15)]),
        "fall": dict(status="ok", latency_sec=4.0, windows=[dict(video="b.mp4", start_sec=0, end_sec=10)]),
        "car": dict(status="ok", latency_sec=3.0, windows=[dict(video="a.mp4", start_sec=0, end_sec=10)])}), "ranked")
    m = r.metrics
    assert m["hit@1"] == 0.5 and m["hit@5"] == 1.0               # walk misses at rank 1 (touching only)
    assert m["recall@5"] == 0.75                                  # walk 1/1, fall 1/2
    assert m["precision@5"] == 0.75                               # walk 1/2, fall 1/1
    assert m["loc@5_iou>=0.5"] == 0.5                             # walk IoU 3/5=0.6; fall 2/10=0.2
    assert m["missed_event_rate"] == 0.0 and m["negative_false_positive_rate"] == 1.0
    assert m["latency_sec_median"] == 3.0 and r.counts["ok"] == 3


def test_scan_counts_only_supported_windows_and_negatives_need_a_supported_match():
    r = benchmark.score_mode(QUERIES, run("scan", {
        "walk": dict(status="ok", windows=[dict(video="a.mp4", start_sec=6, end_sec=18, verdict="unclear")]),
        "fall": dict(status="ok", windows=[dict(video="b.mp4", start_sec=0, end_sec=12, verdict="supported")]),
        "car": dict(status="ok", windows=[dict(video="a.mp4", start_sec=0, end_sec=12, verdict="not_supported")])}),
        "scan")
    assert r.metrics["missed_event_rate"] == 0.5                  # walk: only an unclear window
    assert r.metrics["negative_false_positive_rate"] == 0.0       # nearest windows are not detections


def test_unavailable_and_failed_queries_are_counted_never_scored():
    r = benchmark.score_mode(QUERIES, run("ranked", {"walk": dict(status="failed", windows=[])}), "ranked")
    assert (r.counts["failed"], r.counts["unavailable"], r.counts["ok"]) == (1, 2, 0)
    assert r.metrics["hit@1"] is None and r.metrics["negative_false_positive_rate"] is None
    none = benchmark.score_mode(QUERIES, None, "scan")
    assert none.counts["unavailable"] == 3 and none.source is None


def test_evidence_span_scoring_improves_localisation_only_when_cited():
    responses = {"walk": dict(status="ok", windows=[dict(video="a.mp4", start_sec=6, end_sec=18, verdict="supported",
                                                         evidence_start_sec=9.8, evidence_end_sec=14.2)])}
    window = benchmark.score_mode(QUERIES[:1], run("scan", responses), "scan")
    span = benchmark.score_mode(QUERIES[:1], run("scan", responses), "scan", use_evidence_span=True)
    assert window.metrics["loc@1_iou>=0.5"] == 0.0 and span.metrics["loc@1_iou>=0.5"] == 1.0


def test_comparison_uses_only_queries_both_modes_answered():
    a = benchmark.score_mode(QUERIES, run("ranked", {"walk": dict(status="ok", windows=[
        dict(video="a.mp4", start_sec=10, end_sec=14)])}), "ranked")
    b = benchmark.score_mode(QUERIES, None, "scan")
    assert benchmark.compare(a, b)["common_queries"] == 0


def test_run_records_must_declare_live_or_replay_and_match_the_mode(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps(run("scan", {}, source="synthetic")), encoding="utf-8")
    with pytest.raises(ValueError, match="never presented as live"):
        benchmark.load_run(f, "scan")
    f.write_text(json.dumps(run("scan", {})), encoding="utf-8")
    with pytest.raises(ValueError, match="expected 'ranked'"):
        benchmark.load_run(f, "ranked")


def test_replayed_recording_reproduces_the_existing_harness():
    """Same recorded synthetic responses, two implementations: the numbers must agree."""
    truth = ROOT / "evaluation/synthetic_events_v2.json"
    recording = ROOT / "evaluation/recordings/2026-10-19-events.json"
    queries, _ = benchmark.load_queries(truth)
    replay = run_benchmark.ranked_run_from_recording(recording, 0.5)
    assert replay["source"] == "replay"                           # never labelled as live
    ours = benchmark.score_mode(queries, replay, "ranked").metrics
    report = evaluate(load_ground_truth(truth), json.loads(recording.read_text(encoding="utf-8"))["responses"])
    old = report["summary"]["merged"]
    assert (ours["hit@1"], ours["hit@5"]) == (old["hit_rate_at"][1], old["hit_rate_at"][5])
    assert (ours["recall@1"], ours["recall@5"]) == (old["mean_recall_at"][1], old["mean_recall_at"][5])
    assert (ours["precision@1"], ours["precision@5"]) == (old["mean_precision_at"][1], old["mean_precision_at"][5])


# --------------------------------------------------------------------------- window geometry and evidence


@pytest.mark.parametrize("duration", [5.0, 15.32, 24.48, 40.32, 299.9])
def test_ceiling_geometry_mirrors_the_real_pipeline(duration):
    assert benchmark.chunk_spans(duration) == search_sync.expected_chunk_spans(duration)
    count = max(1, -(-max(0, duration - scenario_scan.WINDOW_SEC) // scenario_scan.STRIDE_SEC) + 1)
    assert len(benchmark.scan_spans(duration)) == count
    assert (benchmark.SCAN_WINDOW_SEC, benchmark.SCAN_STRIDE_SEC) == (scenario_scan.WINDOW_SEC, scenario_scan.STRIDE_SEC)


def test_scan_samples_match_frame_sampling_on_one_second_frames():
    assert benchmark.scan_samples(0, 12, 40) == [0, 2, 5, 7, 10, 12]
    assert benchmark.scan_samples(36, 40.32, 40.32) == [36, 37, 38, 39, 40]


def test_evidence_span_from_cited_frames():
    sampled = [16.0, 21.0, 26.0, 30.0, 35.0, 39.0]
    assert evidence_span(16, 40, sampled, [21.0, 26.0]) == {"start_sec": 18.7, "end_sec": 28.3}
    assert evidence_span(16, 40, sampled, []) is None
    assert evidence_span(0, 12, [0, 12], [0.0, 12.0]) == {"start_sec": 0, "end_sec": 12}    # clipped


# --------------------------------------------------------------------------- no external calls


def test_benchmark_and_dataset_tools_start_no_processes(monkeypatch, capsys):
    def blocked(*a, **k):
        raise AssertionError("a process was started")
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py"])
    assert run_benchmark.main() == 0
    assert "unavailable" in capsys.readouterr().out


def test_live_scan_recording_is_refused_without_approval(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", "--record-live-scan", str(tmp_path / "o.json")])
    monkeypatch.setattr(run_benchmark, "record_live_scan", lambda *a, **k: pytest.fail("must not run"))
    assert run_benchmark.main() == 2 and "Refused" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


def test_live_scan_recorder_writes_a_scored_run_with_a_mock_reviewer(tmp_path, monkeypatch):
    lib = tmp_path / "caviar"
    make_video(lib / "videos" / "a.mp4", seconds=14, seed=1)
    Indexer(Settings(lib / "videos", lib / "frames", lib / "videos.db"), log=lambda m: None).run()
    from tanya import visual_review
    monkeypatch.setattr(visual_review, "subprocess", types.SimpleNamespace(run=lambda *a, **k: pytest.fail("egress")))

    def reviewer(payload, settings):
        return [dict(id=c["id"], verdict="supported" if i == 0 else "not_supported", reason="mock",
                     evidence_timestamps=[c["frames"][1]["timestamp_sec"]] if i == 0 else [])
                for i, c in enumerate(payload["candidates"])]
    queries = [benchmark.Query("walk", "direct", "dev", [benchmark.Span("a.mp4", 1, 4)])]
    out = tmp_path / "scan.json"
    assert run_benchmark.record_live_scan(queries, out, reviewer=reviewer, caviar=lib) == 0
    record = benchmark.load_run(out, "scan")
    windows = record["responses"]["walk"]["windows"]
    assert windows[0]["verdict"] == "supported" and windows[0]["evidence_start_sec"] is not None
    scored = benchmark.score_mode(queries, record, "scan")
    assert scored.counts["ok"] == 1 and scored.metrics["hit@1"] == 1.0


def test_checked_replay_recomputes_evidence_spans_and_stays_labelled_as_replay():
    """Before/after on recorded checker output (synthetic footage): spans tighten localisation only."""
    truth = ROOT / "evaluation/synthetic_events_v2.json"
    record = run_benchmark.checked_run_from_recording(ROOT / "evaluation/recordings/2026-10-19-targeted-visual.json")
    assert record["mode"] == "ranked_checked" and record["source"] == "replay"
    queries, _ = benchmark.load_queries(truth)
    window = benchmark.score_mode(queries, record, "ranked_checked").metrics
    span = benchmark.score_mode(queries, record, "ranked_checked", use_evidence_span=True).metrics
    assert window["hit@1"] == span["hit@1"] == 1.0                 # same candidates, same detections
    assert (window["loc@1_iou>=0.5"], span["loc@1_iou>=0.5"]) == (0.333, 0.667)
    assert span["loc@1_iou>=0.3"] >= window["loc@1_iou>=0.3"]
    with pytest.raises(ValueError, match="unknown mode"):
        benchmark.score_mode(queries, record, "detector")
