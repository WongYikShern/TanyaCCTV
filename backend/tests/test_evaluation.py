"""Tests for the search evaluation harness, recorded baseline and synthetic demo footage."""

from __future__ import annotations

import json

import numpy as np
import pytest

import evaluate_search
import make_demo_footage
from tanya.config import PROJECT_ROOT
from tanya.evaluation import Case, Event, Window, evaluate, iou, load_ground_truth, score_case

TRUTH = PROJECT_ROOT / "evaluation" / "synthetic_ground_truth.json"
RECORDING = PROJECT_ROOT / "evaluation" / "recordings" / "2026-10-17-gemini-embedding-2.json"


def W(video, start, end, score=0.5):
    return Window(video, float(start), float(end), score)


# --------------------------------------------------------------------------- metrics (known answers)


def test_precision_recall_hit_and_rank():
    case = Case("q", [Event("a.mp4", 20, 40)])
    ranked = [W("b.mp4", 20, 40), W("a.mp4", 30, 40), W("a.mp4", 0, 10)]
    r = score_case(case, ranked, "chunks", ks=(1, 3))
    assert r.hit_at == {1: False, 3: True}
    assert r.precision_at == {1: 0.0, 3: pytest.approx(1 / 3)}
    assert r.recall_at == {1: 0.0, 3: 1.0}
    assert r.reciprocal_rank == 0.5
    assert r.first_relevant["rank"] == 2 and r.first_relevant["start_error_sec"] == 10
    assert r.first_relevant["end_error_sec"] == 0 and r.first_relevant["iou"] == 0.5


def test_same_times_in_another_video_are_not_relevant():
    case = Case("q", [Event("a.mp4", 0, 10)])
    r = score_case(case, [W("b.mp4", 0, 10)], "chunks", ks=(1,))
    assert r.hit_at[1] is False and r.first_relevant is None and r.reciprocal_rank == 0.0


def test_touching_windows_do_not_overlap():
    assert iou(W("a.mp4", 0, 20), Event("a.mp4", 20, 40)) == 0.0
    r = score_case(Case("q", [Event("a.mp4", 20, 40)]), [W("a.mp4", 10, 20)], "chunks", ks=(1,))
    assert r.hit_at[1] is False


def test_recall_counts_events_not_windows():
    case = Case("q", [Event("a.mp4", 0, 10), Event("b.mp4", 50, 60)])
    r = score_case(case, [W("a.mp4", 0, 10), W("a.mp4", 2, 8), W("b.mp4", 55, 60)], "chunks", ks=(2, 3))
    assert r.recall_at == {2: 0.5, 3: 1.0}


def test_fewer_results_than_k_uses_returned_count():
    r = score_case(Case("q", [Event("a.mp4", 0, 10)]), [W("a.mp4", 0, 10)], "chunks", ks=(5,))
    assert r.precision_at[5] == 1.0


def test_negative_queries_are_reported_but_never_scored_as_correct():
    report = evaluate([Case("pos", [Event("a.mp4", 0, 10)]), Case("neg", [])], {
        "pos": [dict(rank=1, filename="a.mp4", start_sec=0, end_sec=10, score=.4, score_above_median=.1)],
        "neg": [dict(rank=1, filename="a.mp4", start_sec=0, end_sec=10, score=.3, score_above_median=.0)]})
    assert report["summary"]["chunks"]["positive_queries"] == 1
    assert report["summary"]["chunks"]["negative_queries"] == 1
    neg = next(q for q in report["per_query"] if q["query"] == "neg" and q["level"] == "chunks")
    assert neg["negative"] and neg["hit_at"] == {} and neg["precision_at"] == {} and neg["top_window"]


def test_missing_response_is_an_error():
    with pytest.raises(ValueError, match="no recorded response"):
        evaluate([Case("q", [])], {})


# --------------------------------------------------------------------------- ground truth files


def test_template_csv_loads_and_groups_rows(tmp_path):
    header = (PROJECT_ROOT / "docs" / "cctv-validation-template.csv").read_text(encoding="utf-8").strip()
    rows = ["c1,a red car,camera-A,20,40,red car enters,day,supported,,,,,,",
            "c2,a red car,camera-B,5,9,second car,night,supported,,,,,,",
            "c3,fire and smoke,,,,none visible,day,not supported,,,,,,"]
    path = tmp_path / "private-validation.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    cases = {c.query: c for c in load_ground_truth(path)}
    assert cases["a red car"].events == [Event("camera-A", 20, 40), Event("camera-B", 5, 9)]
    assert cases["fire and smoke"].events == []


@pytest.mark.parametrize("cases", [
    [{"query": "q", "events": [{"video": "a", "start_sec": 10, "end_sec": 10}]}],
    [{"query": " ", "events": []}],
    [{"query": "q", "events": []}, {"query": "q", "events": []}],
])
def test_invalid_ground_truth_is_rejected(tmp_path, cases):
    path = tmp_path / "gt.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_ground_truth(path)


# --------------------------------------------------------------------------- recorded baseline (real Gemini, 2026-10-17)


def test_recorded_gemini_baseline():
    """Regression baseline from the recorded real run. Change only with a new recording."""
    data = json.loads(RECORDING.read_text(encoding="utf-8"))
    report = evaluate(load_ground_truth(TRUTH), data["responses"])
    chunks, merged = report["summary"]["chunks"], report["summary"]["merged"]
    assert chunks["positive_queries"] == 3 and chunks["negative_queries"] == 1
    assert chunks["hit_rate_at"][1] == merged["hit_rate_at"][1] == 1.0
    assert chunks["mrr"] == merged["mrr"] == 1.0
    assert chunks["mean_precision_at"][3] == 1.0 and chunks["mean_precision_at"][5] == 0.667
    assert merged["mean_precision_at"][3] == 0.5
    assert chunks["mean_iou"] == 0.417 and merged["mean_iou"] == 0.867        # merging tightens timing
    assert chunks["mean_end_error_sec"] == 10.0 and merged["mean_end_error_sec"] == 0.667
    assert "AIza" not in RECORDING.read_text(encoding="utf-8")


def test_evaluate_script_offline_and_json(capsys):
    assert evaluate_search.main([]) == 0
    out = capsys.readouterr().out
    assert "TanyaCCTV merged windows" in out and "not detection accuracy" in out
    assert evaluate_search.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["merged"]["mrr"] == 1.0


def test_live_mode_sends_nothing_without_approval(monkeypatch, capsys):
    monkeypatch.setattr(evaluate_search, "search", lambda *a, **k: pytest.fail("must not call the API"))
    assert evaluate_search.main(["--live"]) == 0
    out = capsys.readouterr().out
    assert "Nothing was sent" in out and "4 text queries" in out and "no footage" in out


def test_live_mode_with_approval_saves_responses(monkeypatch, tmp_path, capsys):
    recorded = json.loads(RECORDING.read_text(encoding="utf-8"))["responses"]
    calls = []
    monkeypatch.setattr(evaluate_search, "search",
                        lambda settings, q, n: calls.append(q) or {"results": recorded[q]})
    out = tmp_path / "rec.json"
    assert evaluate_search.main(["--live", "--approve-api-calls", "--save", str(out)]) == 0
    assert sorted(calls) == sorted(recorded) and json.loads(out.read_text())["responses"] == recorded


def test_bad_ground_truth_path_exit_code(tmp_path):
    assert evaluate_search.main(["--ground-truth", str(tmp_path / "missing.json")]) == 2


# --------------------------------------------------------------------------- synthetic footage


def test_generator_events_match_ground_truth():
    truth = {(e.video, c.query, e.start_sec, e.end_sec) for c in load_ground_truth(TRUTH) for e in c.events}
    generated = {(f, q, float(s), float(t)) for f, (_, events) in make_demo_footage.SCENES.items()
                 for q, s, t in events}
    assert generated == truth


def test_generator_frames_show_the_events():
    def red(img):  # pixels of the car's red (BGR ~ (30, 30, 200))
        return int(np.sum((img[..., 2] > 170) & (img[..., 0] < 80) & (img[..., 1] < 80)))
    assert red(make_demo_footage.carpark_frame(10)) == 0 and red(make_demo_footage.carpark_frame(30)) > 2000
    empty, walking, lying = (make_demo_footage.lobby_frame(t) for t in (10, 30, 50))
    shirt = lambda img: int(np.sum((img[..., 0] > 170) & (img[..., 2] < 60)))  # blue-ish shirt
    assert shirt(empty) == 0 and shirt(walking) > 500 and shirt(lying) > 500


def test_generator_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(make_demo_footage, "SCENES", {"cam1_lobby.mp4": (2, []), "cam2_carpark.mp4": (2, [])})
    written = make_demo_footage.make(tmp_path, ffmpeg=None, log=lambda m: None)
    assert [p.name for p in written] == ["cam1_lobby.mp4", "cam2_carpark.mp4"]
    before = (tmp_path / "cam1_lobby.mp4").read_bytes()
    with pytest.raises(FileExistsError):
        make_demo_footage.make(tmp_path, ffmpeg=None, log=lambda m: None)
    assert (tmp_path / "cam1_lobby.mp4").read_bytes() == before


def test_save_never_overwrites_and_refuses_before_any_api_call(monkeypatch, tmp_path):
    existing = tmp_path / "recording.json"
    existing.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(evaluate_search, "search", lambda *a, **k: pytest.fail("must not call the API"))
    assert evaluate_search.main(["--live", "--approve-api-calls", "--save", str(existing)]) == 2
    assert existing.read_text(encoding="utf-8") == "keep me"


# --------------------------------------------------------------------------- Phase 7: event dataset and analysis

EVENTS_V2 = PROJECT_ROOT / "evaluation" / "synthetic_events_v2.json"


def test_events_v2_ground_truth_matches_all_generated_scenes():
    cases = load_ground_truth(EVENTS_V2)
    annotated = {(e.video, c.query, e.start_sec, e.end_sec) for c in cases for e in c.events}
    scenes = make_demo_footage.SETS["all"]
    generated = {(f, q, float(s), float(t)) for f, (_, events) in scenes.items() for q, s, t in events}
    assert generated <= annotated                                   # every generated event is annotated
    assert {v for v, *_ in annotated} <= set(scenes)                # only generated clips are referenced
    for video, _, start, end in annotated:
        assert 0 <= start < end <= scenes[video][0]
    types = {c.event_type for c in cases}
    assert {"entry", "exit", "loitering", "fall", "vehicle_entry", "vehicle_parked", "vehicle_exit", "negative"} <= types
    assert sum(not c.events for c in cases) == 5


def test_event_scenes_show_their_events():
    m = make_demo_footage
    person = lambda img: int(np.sum((img[..., 0] > 170) & (img[..., 2] < 60)))      # blue shirt
    blue_car = lambda img: int(np.sum((img[..., 0] > 140) & (img[..., 1] > 60) & (img[..., 1] < 120) & (img[..., 2] < 60)))
    door_open = lambda img: int(np.sum(img[100:200, 500:560].max(axis=2) < 60)) > 3000
    assert person(m.entrance_frame(5)) == 0 and person(m.entrance_frame(30)) > 500 and person(m.entrance_frame(58)) == 0
    assert not door_open(m.entrance_frame(5)) and door_open(m.entrance_frame(15)) and door_open(m.entrance_frame(50))
    assert blue_car(m.driveway_frame(5)) == 0 and blue_car(m.driveway_frame(28)) > 2000 and blue_car(m.driveway_frame(48)) == 0
    upright, falling, lying = (m.corridor_frame(t) for t in (12, 21.5, 30))
    assert person(upright) > 500 and person(falling) > 500 and person(lying) > 500
    assert not np.array_equal(falling, lying)


def test_events_outside_the_recorded_index_are_excluded_not_missed():
    from tanya.evaluation import restrict_to_index
    cases = [Case("walk", [Event("a.mp4", 0, 10), Event("c.mp4", 0, 10)], "person_movement"),
             Case("only_c", [Event("c.mp4", 5, 9)], "fall"), Case("neg", [], "negative")]
    kept, dropped = restrict_to_index(cases, ["a.mp4"])
    assert [c.query for c in kept] == ["walk", "neg"] and kept[0].events == [Event("a.mp4", 0, 10)]
    assert [d["video"] for d in dropped] == ["c.mp4", "c.mp4"]
    report = evaluate(cases, {"walk": [dict(rank=1, filename="a.mp4", start_sec=0, end_sec=10, score=.4,
                                            score_above_median=.1)], "neg": []}, indexed_videos=["a.mp4"])
    s = report["summary"]["chunks"]
    assert s["positive_queries"] == 1 and s["mean_recall_at"][5] == 1.0            # c.mp4 not counted as a miss
    assert report["not_measured"] == [{"query": "only_c", "event_type": "fall",
                                       "reason": "its videos were not in the recorded index"}]


def test_error_analysis_labels_confusions_background_and_misses():
    cases = [Case("walk", [Event("a.mp4", 20, 40), Event("b.mp4", 0, 10)], "person_movement"),
             Case("lie", [Event("a.mp4", 40, 60)], "person_lying")]
    r = lambda rank, f, s, e, score: dict(rank=rank, filename=f, start_sec=s, end_sec=e, score=score,
                                          score_above_median=score - .3)
    report = evaluate(cases, {"walk": [r(1, "a.mp4", 24, 34, .5), r(2, "a.mp4", 48, 58, .45), r(3, "a.mp4", 0, 10, .4)],
                              "lie": [r(1, "a.mp4", 40, 50, .5)]}, ratio=1.0)
    walk = next(a for a in report["analysis"] if a["query"] == "walk")
    assert [(f["start_sec"], f["overlaps"]) for f in walk["false_positives"]] == [(48, ["lie"]), (0, ["background"])]
    assert walk["missed_events"] == [{"video": "b.mp4", "start_sec": 0.0, "end_sec": 10.0}]
    assert set(report["by_event_type"]) == {"person_movement", "person_lying"}


def test_missing_responses_raise_unless_allowed():
    cases = [Case("a", [Event("x.mp4", 0, 5)]), Case("b", [Event("x.mp4", 0, 5)])]
    with pytest.raises(ValueError):
        evaluate(cases, {"a": []})
    report = evaluate(cases, {"a": []}, allow_missing=True)
    assert report["not_measured"][0]["query"] == "b" and report["summary"]["chunks"]["positive_queries"] == 1


def test_recording_declares_its_index_and_v2_run_is_honest(capsys):
    assert json.loads(RECORDING.read_text(encoding="utf-8"))["indexed_videos"] == ["cam1_lobby.mp4", "cam2_carpark.mp4"]
    assert evaluate_search.main(["--ground-truth", str(EVENTS_V2), "--allow-missing", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["merged"]["positive_queries"] == 3 and len(report["not_indexed_events"]) == 12
    reasons = {m["query"]: m["reason"] for m in report["not_measured"]}
    assert reasons["a person falling down"] == "its videos were not in the recorded index"
    assert reasons["a dog running"] == "no recorded response"
    assert evaluate_search.main(["--ground-truth", str(EVENTS_V2)]) == 2       # missing responses refused by default


def test_extended_live_recording_preserves_scope_and_known_failures():
    """Re-score saved responses offline; never replace observed failures with a perfect mock."""
    path = PROJECT_ROOT / 'evaluation/recordings/2026-10-19-events.json'
    recording = json.loads(path.read_text())
    cases = load_ground_truth(PROJECT_ROOT / 'evaluation/synthetic_events_v2.json')
    assert len(recording['responses']) == len(cases) == 16
    assert len(recording['indexed_videos']) == 5
    assert recording['provenance']['video_embedding_requests'] == 32
    for results in recording['responses'].values():
        assert all(r['status'] == 'uncertain' and r['source_file'].startswith('{VIDEO_DIR}/') for r in results)
    report = evaluate(cases, recording['responses'], indexed_videos=recording['indexed_videos'])
    summary = report['summary']['merged']
    assert (summary['positive_queries'], summary['negative_queries']) == (11, 5)
    assert summary['hit_rate_at'][1] == 0.818
    assert summary['mean_precision_at'][5] == 0.508
    assert summary['mean_recall_at'][5] == 1.0
    assert summary['mean_iou'] == 0.453
    assert report['localization']['0.5']['summary']['merged']['mean_recall_at'][5] == 0.455
    strict_fall = next(q for q in report['localization']['0.5']['per_query']
                       if q['query'] == 'a person falling down' and q['level'] == 'merged')
    assert strict_fall['recall_at'][5] == 0.0
    assert not report['not_measured']
    assert report['by_event_type']['loitering']['hit_rate_at'][1] == 0.0
    assert report['by_event_type']['vehicle_parked']['hit_rate_at'][1] == 0.0
    assert report['by_event_type']['fall']['mean_iou'] == 0.125
    negatives = [a for a in report['analysis'] if a['negative']]
    assert len(negatives) == 5 and all(a['false_positives'] for a in negatives)


def test_temporal_relevance_rejects_broad_overlap_but_accepts_exact_threshold():
    case = Case('fall', [Event('a.mp4', 20, 23)])
    broad = W('a.mp4', 16, 40)
    half = W('a.mp4', 20, 26)
    assert score_case(case, [broad], 'merged', ks=(1,)).recall_at[1] == 1
    strict = score_case(case, [broad, half], 'merged', ks=(1, 2), min_iou=.5)
    assert strict.hit_at == {1: False, 2: True}
    assert strict.precision_at[2] == .5 and strict.recall_at[2] == 1
    assert strict.first_relevant['rank'] == 2
    assert score_case(case, [W('other.mp4', 20, 23)], 'chunks', ks=(1,), min_iou=.5).hit_at[1] is False


@pytest.mark.parametrize('threshold', [-.1, 1.1, float('nan')])
def test_invalid_temporal_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        score_case(Case('q', []), [], 'chunks', min_iou=threshold)


def test_localization_excludes_negatives_and_unmeasured_queries():
    cases = [Case('fall', [Event('a.mp4', 20, 23)]), Case('absent', []),
             Case('missing response', [Event('a.mp4', 0, 3)])]
    responses = {'fall': [dict(filename='a.mp4', start_sec=16, end_sec=40, score=.8,
                               score_above_median=.1, rank=1)], 'absent': []}
    report = evaluate(cases, responses, allow_missing=True)
    assert report['summary']['merged']['mean_recall_at'][5] == 1
    for measured in report['localization'].values():
        summary = measured['summary']['merged']
        assert (summary['positive_queries'], summary['negative_queries']) == (1, 1)
        assert summary['mean_recall_at'][5] == 0
        assert len(measured['per_query']) == 4
    assert len(report['not_measured']) == 1
