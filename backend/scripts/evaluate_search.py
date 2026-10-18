"""Measure search ranking quality against annotated ground truth.

Offline (default, free): re-scores a recorded set of real search responses.
    python backend/scripts/evaluate_search.py
    python backend/scripts/evaluate_search.py --json

Live (sends each query's text to Google; needs the key, a prepared index, and your approval):
    python backend/scripts/evaluate_search.py --live                       # shows the plan only
    python backend/scripts/evaluate_search.py --live --approve-api-calls --save evaluation/recordings/new.json

Ground truth can be JSON (evaluation/synthetic_ground_truth.json) or a filled-in copy of
docs/cctv-validation-template.csv. Results describe ranking on that set only, not detection accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tanya.config import PROJECT_ROOT, ConfigError, load_search_settings  # noqa: E402
from tanya.evaluation import evaluate, format_report, load_ground_truth  # noqa: E402
from tanya.sentry_client import SearchError, search  # noqa: E402

DEFAULT_TRUTH = PROJECT_ROOT / "evaluation" / "synthetic_ground_truth.json"
DEFAULT_RECORDING = PROJECT_ROOT / "evaluation" / "recordings" / "2026-10-17-gemini-embedding-2.json"
# Gemini Embedding 2 text input, paid tier: US$0.20 per 1M tokens (pricing checked 2026-10-16).
USD_PER_TEXT_TOKEN = 0.20 / 1_000_000


def load_recording(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["responses"] if "responses" in data else data


def live_responses(cases, n: int) -> dict[str, list[dict]]:
    settings = load_search_settings()
    return {c.query: search(settings, c.query, n)["results"] for c in cases}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="Evaluate search ranking against ground truth.")
    p.add_argument("--ground-truth", type=Path, default=DEFAULT_TRUTH)
    p.add_argument("--recorded", type=Path, default=DEFAULT_RECORDING)
    p.add_argument("--live", action="store_true", help="query the configured search index instead")
    p.add_argument("--approve-api-calls", action="store_true", help="required with --live to actually send queries")
    p.add_argument("--n", type=int, default=10, help="chunks requested per live query")
    p.add_argument("--save", type=Path, help="with --live: save the responses for later offline evaluation")
    p.add_argument("--merge-ratio", type=float, default=0.5)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        cases = load_ground_truth(args.ground_truth)
    except (OSError, ValueError, KeyError) as e:
        print(f"Cannot read ground truth {args.ground_truth}: {e}", file=sys.stderr)
        return 2

    if args.save and args.save.exists():
        print(f"Refusing to overwrite {args.save}; choose a new file name.", file=sys.stderr)
        return 2
    if args.live:
        tokens = sum(len(c.query.split()) * 2 + 4 for c in cases)  # generous token estimate
        print(f"Live evaluation plan: send {len(cases)} text queries to Google Gemini (query text only; "
              f"no footage or frames). Estimated cost ~US${tokens * USD_PER_TEXT_TOKEN:.6f} on the paid tier "
              f"(estimate, not a cap). Results depend on what is in the configured search index.")
        if not args.approve_api_calls:
            print("Nothing was sent. Re-run with --approve-api-calls to proceed.")
            return 0
        try:
            responses = live_responses(cases, args.n)
        except (SearchError, ConfigError) as e:
            print(f"Live evaluation failed: {e}", file=sys.stderr)
            return 3
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json.dumps({"recorded_at": date.today().isoformat(), "responses": responses},
                                            indent=2) + "\n", encoding="utf-8")
            print(f"Saved responses to {args.save}")
    else:
        try:
            responses = load_recording(args.recorded)
        except (OSError, ValueError, KeyError) as e:
            print(f"Cannot read recording {args.recorded}: {e}", file=sys.stderr)
            return 2

    try:
        report = evaluate(cases, responses, ratio=args.merge_ratio)
    except ValueError as e:
        print(f"Cannot evaluate: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
