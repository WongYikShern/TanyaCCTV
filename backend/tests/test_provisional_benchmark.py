"""Provisional single-reviewer benchmark: never 'verified', rejected labels are contested (not negatives)."""
import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

from tanya import benchmark, real_dataset
from tests.test_label_review import fill, workspace  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
import prepare_provisional_benchmark  # noqa: E402


def all_answered(root, tmp_path, initials="Ys", reject=("walking",)):
    answers = {c: ("reject" if c in reject else "confirm", "", "") for c in ("fallen", "person_present", "walking")}
    return fill(root / "evaluation/review/caviar-review.csv", tmp_path / f"review-{initials}.csv", initials, answers)


def test_single_review_is_provisional_and_rejections_are_contested(workspace, tmp_path):  # noqa: F811
    root, _, _ = workspace
    csv_path = all_answered(root, tmp_path)
    before = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    result = prepare_provisional_benchmark.prepare(csv_path, root)
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == before          # input never modified
    built = result["built"]
    states = {e["verification"] for spans in built["events"].values() for e in spans}
    assert states == {real_dataset.PROVISIONAL}                                   # never human_verified
    assert built["events"]["walking"] == [] and built["rejected"][0]["rejected_by"] == "single_reviewer"
    walking = next(c for c in built["cases"] if c["query"] == "a person walking")
    assert walking["events"] == [] and walking["ignore_events"] == [
        dict(video="Clip.mp4", start_sec=0.0, end_sec=2.0, rejected_by="single_reviewer")]
    truth = json.loads(result["paths"]["ground_truth"].read_text(encoding="utf-8"))
    assert truth["verification"] == real_dataset.PROVISIONAL and truth["provenance"]["review_sha256"] == before
    assert truth["provenance"]["review_file"] == csv_path.name and str(tmp_path) not in json.dumps(truth)
    # the two-reviewer outputs are never written by the provisional path
    assert not (root / "evaluation/review/caviar-verified.json").exists()
    assert result["paths"]["ground_truth"].name == "caviar_ground_truth.provisional_single_reviewer.json"


def test_incomplete_or_multi_reviewer_csv_is_refused(workspace, tmp_path):  # noqa: F811
    root, _, _ = workspace
    partial = fill(root / "evaluation/review/caviar-review.csv", tmp_path / "partial.csv", "Ys",
                   {"fallen": ("confirm", "", "")})
    with pytest.raises(ValueError, match="incomplete"):
        prepare_provisional_benchmark.prepare(partial, root)
    mixed = all_answered(root, tmp_path)
    rows = list(csv.DictReader(mixed.open(encoding="utf-8")))
    rows[0]["reviewer_initials"] = "CD"
    with mixed.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=real_dataset.REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError, match="One reviewer"):
        prepare_provisional_benchmark.prepare(mixed, root)


def test_contested_windows_are_neither_hits_nor_false_positives():
    q = benchmark.Query("a person standing still", "direct", "dev",
                        events=[benchmark.Span("a.mp4", 0, 4)], ignore=[benchmark.Span("a.mp4", 10, 14)])
    run = dict(mode="ranked", source="live", engine="t", responses={q.query: dict(status="ok", windows=[
        dict(video="a.mp4", start_sec=10, end_sec=14),          # inside the contested region: dropped
        dict(video="a.mp4", start_sec=0, end_sec=4)])})
    m = benchmark.score_mode([q], run, "ranked").metrics
    assert m["hit@1"] == 1.0 and m["precision@1"] == 1.0    # without the ignore rule this would be 0.0
    no_ignore = benchmark.Query(q.query, q.kind, q.split, q.events)
    assert benchmark.score_mode([no_ignore], run, "ranked").metrics["hit@1"] == 0.0


def test_two_reviewer_rejection_is_also_contested_not_negative(workspace):  # noqa: F811
    _, clips, built = workspace
    key = next(real_dataset.event_key("walking", e["video"], e["start_sec"], e["end_sec"]) for e in built["events"]["walking"])
    rebuilt = real_dataset.build(clips, {key: dict(status="rejected", reviewers=["AB", "CD"])})
    walking = next(c for c in rebuilt["cases"] if c["query"] == "a person walking")
    assert walking["events"] == [] and walking["ignore_events"][0]["rejected_by"] == "two_reviewers"


def test_cli_refuses_missing_file(tmp_path, capsys):
    assert prepare_provisional_benchmark.main([str(tmp_path / "nope.csv")]) == 1
    assert "not found" in capsys.readouterr().err


@pytest.mark.skipif(not (ROOT / "evaluation/provisional/caviar_ground_truth.provisional_single_reviewer.json").is_file(),
                    reason="no provisional dataset prepared on this machine")
def test_committed_provisional_dataset_is_labelled_and_consistent():
    truth = json.loads((ROOT / "evaluation/provisional/caviar_ground_truth.provisional_single_reviewer.json")
                       .read_text(encoding="utf-8"))
    assert truth["verification"] == real_dataset.PROVISIONAL and truth["provenance"]["status"] == real_dataset.PROVISIONAL
    events = [e for c in truth["cases"] for e in c["events"]]
    assert events and all(e["verification"] == real_dataset.PROVISIONAL for e in events)
    assert "human_verified" not in json.dumps(truth["cases"])
    queries, _ = benchmark.load_queries(ROOT / "evaluation/provisional/caviar_ground_truth.provisional_single_reviewer.json")
    for q in queries:
        for c in q.ignore:
            assert not any(benchmark.overlap(c, e) > 0 for e in q.events)    # contested never overlaps a positive
