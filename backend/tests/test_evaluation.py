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
