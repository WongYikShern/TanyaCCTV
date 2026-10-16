"""JSON bridge between TanyaCCTV (Python 3.14) and SentrySearch (Python 3.12, pinned d3efd6a).

Runs INSIDE the SentrySearch environment. The caller runs it as a subprocess and reads exactly
one JSON document from stdout. Library output goes to stderr, with secrets redacted.

    python tanya_bridge.py search "a red car" [--n 5] [--db PATH]
    python tanya_bridge.py stats [--db PATH]
    python tanya_bridge.py remove --source-file EXACT_PATH --within DIR [--db PATH]

remove deletes the chunks of ONE file, and only if the path exactly equals an indexed
source_file (SentryStore.remove_file matches the metadata exactly) AND lies inside --within.
It never does substring matching (unlike `sentrysearch remove`), so entries in the shared
index that belong to other folders cannot be touched.

Search output:
    {"ok": true, "query": ..., "total_chunks": N, "dedupe": "disabled",
     "baseline": {"median": ...},
     "results": [{"rank", "source_file", "filename", "start_sec", "end_sec",
                  "score", "score_above_median", "status"}], "note": ...}
Failure output (exit code 1):
    {"ok": false, "error": "...", "error_type": "..."}

Why every result is "uncertain":
    The trial and live tests showed that no score statistic separates relevant from irrelevant
    clips on this data. Raw scores: a correct "red car" match scored 0.36, an irrelevant
    "fire and smoke" match 0.34. A per-query robust z-score labelled irrelevant "fire and smoke"
    chunks z=4.16 and correct "lying on the floor" chunks z=1.60. Score above the query's median
    overlapped too (correct walking +0.048..+0.057, empty car park for "a red car"
    +0.040..+0.052). So results are a ranked list for a human to review; status is always
    "uncertain". score_above_median is informational only and is NOT a confidence measure.
    Any confidence labelling must be calibrated later on real authorised footage.

Deduplication is disabled (dedupe_threshold=None). With fixed CCTV cameras, chunks from the
same camera are 0.90-0.99 cosine-similar because the background dominates, so SentrySearch's
CLI default (0.9) threw away the chunks that actually contained the event.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import statistics
import sys
from pathlib import Path

STATUS_UNCERTAIN = "uncertain"  # the only status: results are never treated as confirmed incidents
NOTE = ("Ranked similarity search results, not detections. Every result needs human review; "
        "score and score_above_median are for ordering only, not confidence.")


class BridgeError(Exception):
    """A usage or input error that should be reported as JSON."""


def redact(text: str) -> str:
    """Remove the Gemini API key (if set) from any text before it leaves this process."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if len(key) >= 8:
        text = text.replace(key, "***REDACTED***")
    return text


def open_store(db: str | None):
    from sentrysearch.store import SentryStore

    if db is not None and not Path(db).is_dir():
        raise BridgeError(f"index directory not found: {db}")
    return SentryStore(db_path=db, backend="gemini")


def do_stats(args: argparse.Namespace) -> dict:
    stats = open_store(args.db).get_stats()
    return {"ok": True, "total_chunks": stats["total_chunks"], "source_files": stats["source_files"]}


def _is_within(path: str, folder: str) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    f = os.path.normcase(os.path.abspath(folder))
    try:
        return os.path.commonpath([p, f]) == f and p != f
    except ValueError:  # different drives on Windows
        return False


def do_remove(args: argparse.Namespace) -> dict:
    if not os.path.isabs(args.source_file) or not os.path.isabs(args.within):
        raise BridgeError("--source-file and --within must be absolute paths")
    if not _is_within(args.source_file, args.within):
        raise BridgeError("refusing to remove: source file is not inside --within")
    store = open_store(args.db)
    if args.source_file not in store.get_stats()["source_files"]:
        raise BridgeError("refusing to remove: no indexed source_file exactly matches this path")
    removed = store.remove_file(args.source_file)  # exact metadata match
    return {"ok": True, "source_file": args.source_file, "removed_chunks": removed}


def do_search(args: argparse.Namespace) -> dict:
    from sentrysearch.embedder import get_embedder
    from sentrysearch.search import search_footage

    if not args.query.strip():
        raise BridgeError("query must not be empty")
    if not 1 <= args.n <= 100:
        raise BridgeError("--n must be between 1 and 100")

    store = open_store(args.db)
    total = store.get_stats()["total_chunks"]
    base = {"ok": True, "query": args.query, "total_chunks": total, "dedupe": "disabled", "note": NOTE}
    if total == 0:
        return {**base, "baseline": None, "results": []}

    get_embedder("gemini")
    # One API call: score every chunk (for the per-query median), dedupe explicitly off.
    hits = search_footage(args.query, store, n_results=total, dedupe_threshold=None)
    median = statistics.median(float(h["similarity_score"]) for h in hits)

    results = []
    for rank, h in enumerate(hits[: args.n], start=1):
        score = float(h["similarity_score"])
        results.append({
            "rank": rank,
            "source_file": h["source_file"],
            "filename": Path(h["source_file"]).name,
            "start_sec": round(float(h["start_time"]), 3),
            "end_sec": round(float(h["end_time"]), 3),
            "score": round(score, 4),
            "score_above_median": round(score - median, 4),  # informational only
            "status": STATUS_UNCERTAIN,
        })
    return {**base, "baseline": {"median": round(median, 4)}, "results": results}


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):  # report bad arguments as JSON too
        raise BridgeError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="tanya_bridge")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_JsonArgumentParser)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--n", type=int, default=5)
    s.add_argument("--db", default=None, help="SentrySearch index directory (default: ~/.sentrysearch/db)")
    st = sub.add_parser("stats")
    st.add_argument("--db", default=None)
    rm = sub.add_parser("remove")
    rm.add_argument("--source-file", required=True)
    rm.add_argument("--within", required=True)
    rm.add_argument("--db", default=None)
    return parser


COMMANDS = {"search": do_search, "stats": do_stats, "remove": do_remove}


def main(argv: list[str] | None = None) -> int:
    captured = io.StringIO()
    try:
        args = build_parser().parse_args(argv)
        # Capture everything the library prints, so stdout stays pure JSON and secrets are redacted.
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            payload = COMMANDS[args.command](args)
        code = 0
    except BaseException as e:  # noqa: BLE001 - every failure must come back as JSON
        if isinstance(e, KeyboardInterrupt):
            raise
        if isinstance(e, SystemExit) and e.code in (0, None):  # e.g. --help
            payload, code = {"ok": True}, 0
        else:
            first_line = (str(e).strip().splitlines() or [""])[0]
            payload = {"ok": False, "error": redact(first_line)[:500], "error_type": type(e).__name__}
            code = 1
    if captured.getvalue():
        sys.stderr.write(redact(captured.getvalue()))
    print(redact(json.dumps(payload)))
    return code


if __name__ == "__main__":
    sys.exit(main())
