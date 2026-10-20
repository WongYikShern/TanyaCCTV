"""Merge two independent CAVIAR label reviews and rebuild the ground truth (local only, no AI calls).

    python backend/scripts/apply_label_review.py caviar-review-AB.csv caviar-review-CD.csv

Each CSV comes from the review page ("Download my review CSV"). An event becomes human_verified
only when both reviewers keep it and their boundaries agree within --tolerance seconds (the mean
is used); it is removed only when both reject it. Everything else is listed for discussion: after
resolving, both reviewers update their own answers and this command is run again.

Writes evaluation/review/caviar-verified.json (statuses, boundaries, reviewer initials) and
evaluation/review/caviar-disagreements.csv, then regenerates the dataset files.
"""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tanya import real_dataset  # noqa: E402
import build_real_dataset  # noqa: E402

def disagreements_file() -> Path:
    return build_real_dataset.ROOT / "evaluation" / "review" / "caviar-disagreements.csv"


def kappa(a: dict, b: dict) -> float | None:
    """Cohen's kappa for the keep (confirm/adjust) vs reject decision on events both reviewed."""
    both = [k for k in a if k in b]
    if not both:
        return None
    ka = [a[k]["verdict"] != "reject" for k in both]
    kb = [b[k]["verdict"] != "reject" for k in both]
    observed = sum(x == y for x, y in zip(ka, kb)) / len(both)
    pa, pb = sum(ka) / len(both), sum(kb) / len(both)
    expected = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 3)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("review_a", type=Path)
    p.add_argument("review_b", type=Path)
    p.add_argument("--tolerance", type=float, default=1.0, help="max boundary difference in seconds (default 1.0)")
    args = p.parse_args(argv)
    durations = {c["video"]: c["duration_sec"] for c in real_dataset.load_clips(
        build_real_dataset.CAVIAR, build_real_dataset.ROOT / "evaluation/datasets/caviar-small.json")}
    a, problems_a = real_dataset.read_review(args.review_a, durations)
    b, problems_b = real_dataset.read_review(args.review_b, durations)
    problems = [f"{args.review_a.name}: {x}" for x in problems_a] + [f"{args.review_b.name}: {x}" for x in problems_b]
    if problems:
        print("Fix these review problems first:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    try:
        merged = real_dataset.merge_reviews(a, b, args.tolerance)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    counts = {s: sum(m["status"] == s for m in merged.values()) for s in ("verified", "rejected", "disagree", "incomplete")}
    clips = real_dataset.load_clips(build_real_dataset.CAVIAR, build_real_dataset.ROOT / "evaluation/datasets/caviar-small.json")
    total = len(real_dataset.review_items(real_dataset.build(clips)))
    payload = dict(created=date.today().isoformat(), tolerance_sec=args.tolerance,
                   reviewers=sorted({m for r in merged.values() for m in r.get("reviewers", [])}),
                   summary=dict(counts, events_total=total, unreviewed=total - len(merged), keep_reject_kappa=kappa(a, b)),
                   events=merged)
    out = build_real_dataset.VERIFIED_FILE
    try:
        build_real_dataset.rebuild(merged)       # validates against the current events before anything is saved
    except (ValueError, OSError) as error:
        print(f"Not applied: {error}", file=sys.stderr)
        return 1
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with disagreements_file().open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_key", "status", "reason", "reviewer_a", "reviewer_b", "notes_a", "notes_b"])
        for key, m in merged.items():
            if m["status"] in ("disagree", "incomplete"):
                w.writerow([key, m["status"], m.get("reason", ""), json.dumps(a.get(key)), json.dumps(b.get(key)),
                            (a.get(key) or {}).get("notes", ""), (b.get(key) or {}).get("notes", "")])
    print(f"{total} events: {counts['verified']} verified, {counts['rejected']} rejected by both, "
          f"{counts['disagree']} disagreements, {counts['incomplete']} answered by one reviewer, "
          f"{total - len(merged)} unreviewed. Keep/reject agreement (Cohen's kappa): {payload['summary']['keep_reject_kappa']}")
    print(f"wrote {out.name} and {disagreements_file().name} in evaluation/review; dataset files regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
