"""Prepare a PROVISIONAL CAVIAR benchmark from ONE reviewer's CSV (local only, no AI calls).

    python backend/scripts/prepare_provisional_benchmark.py C:\\path\\to\\caviar-review-XX.csv
    python backend/scripts/run_benchmark.py --ground-truth evaluation/provisional/caviar_ground_truth.provisional_single_reviewer.json

This is NOT the two-reviewer verification (apply_label_review.py) and never writes its files.
Nothing here is "human_verified": events the reviewer kept are labelled provisional_single_reviewer,
and rejected events become contested regions (ignore_events) that are not scored either way.
The input CSV is only read; its SHA-256 (not its location) is recorded in the outputs.
"""
import argparse
import collections
import hashlib
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tanya import real_dataset  # noqa: E402

SUFFIX = "." + real_dataset.PROVISIONAL


def prepare(review_csv: Path, root: Path = ROOT) -> dict:
    caviar = root / "data" / "cctv_validation" / "caviar"
    clips = real_dataset.load_clips(caviar, root / "evaluation/datasets/caviar-small.json")
    durations = {c["video"]: c["duration_sec"] for c in clips}
    reviews, problems = real_dataset.read_review(review_csv, durations)
    if problems:
        raise ValueError("Fix the review CSV first:\n  " + "\n  ".join(problems))
    expected = {i["event_key"] for i in real_dataset.review_items(real_dataset.build(clips))}
    missing = sorted(expected - set(reviews))
    if missing:
        raise ValueError(f"The review is incomplete: {len(missing)} of {len(expected)} events unanswered "
                         f"(first: {missing[0]}). A provisional benchmark needs every event reviewed.")
    initials = sorted({r["initials"] for r in reviews.values()})
    if len(initials) != 1:
        raise ValueError(f"One reviewer's CSV expected; found initials {initials}.")
    verdicts = collections.Counter(r["verdict"] for r in reviews.values())
    built = real_dataset.build(clips, real_dataset.single_review_verification(reviews))
    row_problems = real_dataset.validate_manifest_rows(built["rows"], durations)
    if row_problems:
        raise ValueError("Manifest validation failed:\n  " + "\n  ".join(row_problems[:20]))
    provenance = dict(
        status=real_dataset.PROVISIONAL, created=date.today().isoformat(),
        review_file=review_csv.name, review_sha256=hashlib.sha256(review_csv.read_bytes()).hexdigest(),
        reviewers=initials, events_reviewed=len(reviews), verdicts=dict(verdicts),
        rejected_without_notes=sum(r["verdict"] == "reject" and not r.get("notes") for r in reviews.values()),
        caution="One reviewer only. Not independently verified; do not report as human-verified accuracy. "
                "Rejected events are contested regions, not verified negatives.")
    out = root / "evaluation" / "provisional"
    paths = real_dataset.write_outputs(clips, built, out, None, suffix=SUFFIX,
                                       truth_path=out / f"caviar_ground_truth{SUFFIX}.json", provenance=provenance)
    return dict(paths=paths, built=built, provenance=provenance)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("review_csv", type=Path)
    args = p.parse_args(argv)
    if not args.review_csv.is_file():
        print(f"Review CSV not found: {args.review_csv}", file=sys.stderr)
        return 1
    before = hashlib.sha256(args.review_csv.read_bytes()).hexdigest()
    try:
        result = prepare(args.review_csv)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    assert hashlib.sha256(args.review_csv.read_bytes()).hexdigest() == before   # input is never modified
    prov, built = result["provenance"], result["built"]
    kept = sum(len(v) for v in built["events"].values())
    print(f"PROVISIONAL (single reviewer {', '.join(prov['reviewers'])}): {prov['events_reviewed']} events reviewed, "
          f"verdicts {prov['verdicts']}")
    print(f"  {kept} events kept as {real_dataset.PROVISIONAL}; {len(built['rejected'])} rejected -> contested regions "
          f"(not scored); 0 human_verified")
    if prov["rejected_without_notes"]:
        print(f"  note: {prov['rejected_without_notes']} rejection(s) have no reviewer note explaining why")
    for key, path in result["paths"].items():
        print(f"  wrote {key}: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
