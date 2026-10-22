"""Two-reviewer label verification for the real-camera dataset (synthetic fixtures; no footage, no AI)."""
import csv
import json
import sys
from pathlib import Path

import pytest

from tanya import real_dataset
from tests.test_real_benchmark import caviar_xml, person

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
import apply_label_review  # noqa: E402
import build_real_dataset  # noqa: E402


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A tiny CAVIAR-shaped project: one 6 s clip whose labels give one walking and one fall event."""
    caviar = tmp_path / "data/cctv_validation/caviar"
    (caviar / "videos").mkdir(parents=True)
    (caviar / "videos/Clip.mp4").write_bytes(b"not decoded by these tests")
    (caviar / "media-manifest.json").write_text(json.dumps([dict(
        filename="Clip.mp4", fps=25.0, decoded_frames=150, duration_sec=6.0, width=384, height=288, sha256="0" * 64)]),
        encoding="utf-8")
    (caviar / "annotations").mkdir()
    caviar_xml(caviar / "annotations/Clip.xml",
               [[person()]] * 50 + [[person(movement="inactive", context="drop down", situation="inactive")]] * 75
               + [[]] * 25)
    (tmp_path / "evaluation/datasets").mkdir(parents=True)
    (tmp_path / "evaluation/datasets/caviar-small.json").write_text(
        json.dumps({"clips": [{"name": "Clip", "purpose": "test"}]}), encoding="utf-8")
    monkeypatch.setattr(build_real_dataset, "ROOT", tmp_path)
    monkeypatch.setattr(build_real_dataset, "CAVIAR", caviar)
    monkeypatch.setattr(build_real_dataset, "VERIFIED_FILE", tmp_path / "evaluation/review/caviar-verified.json")
    clips, built, _ = build_real_dataset.rebuild()
    return tmp_path, clips, built


def fill(sheet: Path, out: Path, initials: str, answers: dict):
    """Fill the generated blank sheet: answers = {category: (verdict, start, end)}."""
    with sheet.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["category"] in answers:
            verdict, start, end = answers[r["category"]]
            r["reviewer_verdict (confirm/adjust/reject)"] = verdict
            r["verified_start_sec"], r["verified_end_sec"] = start, end
            r["reviewer_initials"] = initials
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=real_dataset.REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return out


def test_blank_sheet_lists_every_event_with_a_stable_key(workspace):
    root, clips, built = workspace
    sheet = root / "evaluation/review/caviar-review.csv"
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert [r["category"] for r in rows] == ["fallen", "person_present", "walking"]
    assert rows[0]["event_key"] == "fallen|Clip.mp4|2.00|5.00"
    assert all(not r["reviewer_verdict (confirm/adjust/reject)"] for r in rows)


def test_read_review_validates_answers(workspace, tmp_path):
    root, clips, built = workspace
    sheet = root / "evaluation/review/caviar-review.csv"
    good = fill(sheet, tmp_path / "a.csv", "AB", {"fallen": ("adjust", "2.2", "5.1"), "walking": ("confirm", "", "")})
    reviews, problems = real_dataset.read_review(good, {"Clip.mp4": 6.0})
    assert problems == [] and len(reviews) == 2
    assert reviews["fallen|Clip.mp4|2.00|5.00"]["start_sec"] == 2.2
    bad = fill(sheet, tmp_path / "b.csv", "AB", {"fallen": ("adjust", "5", "9"), "walking": ("maybe", "", "")})
    _, problems = real_dataset.read_review(bad, {"Clip.mp4": 6.0})
    assert any("outside" in p for p in problems) and any("confirm, adjust or reject" in p for p in problems)
    no_initials = fill(sheet, tmp_path / "c.csv", "", {"walking": ("confirm", "", "")})
    assert "initials" in real_dataset.read_review(no_initials, {"Clip.mp4": 6.0})[1][0]


def review(verdict, start, end, initials):
    return dict(verdict=verdict, start_sec=start, end_sec=end, initials=initials, notes="")


def test_merge_requires_two_independent_agreeing_reviewers():
    a = {"k1": review("confirm", 2, 5, "AB"), "k2": review("reject", 0, 1, "AB"), "k3": review("adjust", 2, 5, "AB"),
         "k4": review("confirm", 2, 5, "AB"), "k5": review("confirm", 2, 5, "AB")}
    b = {"k1": review("adjust", 2.6, 4.5, "CD"), "k2": review("reject", 0, 1, "CD"), "k3": review("reject", 0, 1, "CD"),
         "k4": review("adjust", 4, 5, "CD")}
    m = real_dataset.merge_reviews(a, b, tolerance_sec=1.0)
    assert m["k1"] == dict(status="verified", reviewers=["AB", "CD"], start_sec=2.3, end_sec=4.75)
    assert m["k2"]["status"] == "rejected"
    assert m["k3"]["status"] == "disagree" and "rejected" in m["k3"]["reason"]
    assert m["k4"]["status"] == "disagree" and "boundaries differ" in m["k4"]["reason"]
    assert m["k5"]["status"] == "incomplete"
    with pytest.raises(ValueError, match="independent"):
        real_dataset.merge_reviews({"k": review("confirm", 2, 5, "ab")}, {"k": review("confirm", 2, 5, "AB")})


def test_verification_changes_ground_truth_only_for_agreed_events(workspace):
    root, clips, built = workspace
    keys = {c: real_dataset.event_key(c, e["video"], e["start_sec"], e["end_sec"])
            for c, spans in built["events"].items() for e in spans}
    verified = real_dataset.build(clips, {keys["fallen"]: dict(status="verified", start_sec=2.1, end_sec=5.2),
                                          keys["walking"]: dict(status="rejected"),
                                          keys["person_present"]: dict(status="disagree")})
    assert verified["events"]["fallen"][0] == dict(video="Clip.mp4", start_sec=2.1, end_sec=5.2, derived_start_sec=2.0,
                                                        derived_end_sec=5.0, verification=real_dataset.VERIFIED)
    assert verified["events"]["walking"] == [] and verified["rejected"][0]["category"] == "walking"
    assert verified["events"]["person_present"][0]["verification"] == real_dataset.UNVERIFIED
    cases = {c["query"]: c for c in verified["cases"]}
    assert cases["a person falling to the floor"]["verification"] == real_dataset.VERIFIED
    assert cases["a person walking"]["events"] == []          # both reviewers rejected the only walking event
    with pytest.raises(ValueError, match="no longer exist"):
        real_dataset.build(clips, {"walking|Clip.mp4|0.00|9.99": dict(status="verified", start_sec=0, end_sec=1)})


def test_apply_script_end_to_end(workspace, tmp_path, capsys):
    root, clips, built = workspace
    sheet = root / "evaluation/review/caviar-review.csv"
    a = fill(sheet, tmp_path / "a.csv", "AB", {"fallen": ("confirm", "", ""), "walking": ("reject", "", ""),
                                               "person_present": ("confirm", "", "")})
    b = fill(sheet, tmp_path / "b.csv", "CD", {"fallen": ("adjust", "2.4", "5.0"), "walking": ("reject", "", ""),
                                               "person_present": ("reject", "", "")})
    assert apply_label_review.main([str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "1 verified, 1 rejected by both, 1 disagreements" in out
    saved = json.loads((root / "evaluation/review/caviar-verified.json").read_text(encoding="utf-8"))
    assert saved["reviewers"] == ["AB", "CD"] and saved["summary"]["keep_reject_kappa"] == 0.4
    events = json.loads((root / "evaluation/datasets/caviar-events.json").read_text(encoding="utf-8"))
    assert events["events"]["fallen"][0]["start_sec"] == 2.2 and events["verification"] == "partially_verified"
    disagreements = list(csv.DictReader((root / "evaluation/review/caviar-disagreements.csv").open(encoding="utf-8")))
    assert [d["event_key"].split("|")[0] for d in disagreements] == ["person_present"]
    # a plain rebuild keeps applying the saved verification
    _, rebuilt, _ = build_real_dataset.rebuild(build_real_dataset.load_verification())
    assert rebuilt["events"]["walking"] == []


def test_apply_refuses_same_reviewer_twice(workspace, tmp_path, capsys):
    root, clips, built = workspace
    sheet = root / "evaluation/review/caviar-review.csv"
    a = fill(sheet, tmp_path / "a.csv", "AB", {"fallen": ("confirm", "", "")})
    assert apply_label_review.main([str(a), str(a)]) == 1
    assert "independent" in capsys.readouterr().err
    assert not (root / "evaluation/review/caviar-verified.json").exists()
