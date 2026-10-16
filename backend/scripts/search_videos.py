"""Search indexed CCTV videos in natural language (via SentrySearch).

Usage (project root, venv active, GEMINI_API_KEY set in this terminal or in .env):
    python backend/scripts/search_videos.py "a person lying on the floor"
    python backend/scripts/search_videos.py "a red car" --n 20 --json
    python backend/scripts/search_videos.py "a red car" --html data/search_results.html --open

Every result is "uncertain": a ranked clip for a person to review, never a confirmed incident.
Searching never indexes, re-indexes or removes anything (see sync_search_index.py for that).
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tanya.config import ConfigError, load_search_settings, load_settings  # noqa: E402
from tanya.report import render_html  # noqa: E402
from tanya.search import search_videos  # noqa: E402
from tanya.sentry_client import SearchError, SearchNotConfiguredError  # noqa: E402


def fmt_time(sec: float) -> str:
    return f"{int(sec) // 60:02d}:{int(sec) % 60:02d}"


def safe_console() -> None:
    """Never crash on a query or filename the console encoding can't show (e.g. cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def write_page(path: Path, settings, query: str, response=None, error: str | None = None,
               open_it: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(settings, query, response, error), encoding="utf-8")
    print(f"Review page written to {path.resolve()}", file=sys.stderr)
    if open_it:
        webbrowser.open(path.resolve().as_uri())


def main(argv: list[str] | None = None) -> int:
    safe_console()
    parser = argparse.ArgumentParser(description="Natural-language search over indexed videos.")
    parser.add_argument("query")
    parser.add_argument("--n", type=int, default=10, help="number of 10 s chunks to retrieve (1-100)")
    parser.add_argument("--json", action="store_true", help="print the full response as JSON")
    parser.add_argument("--html", type=Path, metavar="FILE",
                        help="also write a review page (thumbnails, playable clips) to FILE")
    parser.add_argument("--open", action="store_true", help="open the --html page in the default browser")
    args = parser.parse_args(argv)
    if args.open and not args.html:
        parser.error("--open requires --html FILE")
    # Guard against typos such as --html data\tanya.db, which would overwrite the database.
    if args.html and args.html.suffix.lower() not in {".html", ".htm"}:
        parser.error("--html FILE must end in .html or .htm")

    try:
        settings = load_settings()
        search_settings = load_search_settings()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2

    print(f'Searching for "{args.query}"...', file=sys.stderr)
    try:
        response = search_videos(args.query, settings, search_settings, n=args.n)
    except (SearchNotConfiguredError, SearchError) as e:
        not_configured = isinstance(e, SearchNotConfiguredError)
        print(f"{'Configuration error' if not_configured else 'Search failed'}: {e}", file=sys.stderr)
        if args.html:
            write_page(args.html, settings, args.query, error=str(e), open_it=args.open)
        return 2 if not_configured else 3

    if args.html:
        write_page(args.html, settings, args.query, response, open_it=args.open)

    if args.json:
        print(json.dumps(response.to_dict(), indent=2))
        return 0

    print(f'Results for "{response.query}" (ranked; every result needs review):\n')
    if not response.hits:
        print("  No results from indexed TanyaCCTV videos.")
    for i, h in enumerate(response.hits, start=1):
        print(f"  #{i} {h.rel_path}  {fmt_time(h.start_sec)}-{fmt_time(h.end_sec)}  "
              f"best score {h.best_score:.3f} ({h.best_score_above_median:+.3f} vs median)  [{h.status}]")
        print("      chunks: " + ", ".join(f"{fmt_time(c.start_sec)}-{fmt_time(c.end_sec)} ({c.score:.3f})"
                                         for c in h.chunks))
        print(f"      thumbnail: {h.thumbnail or 'none'}")
    for w in response.warnings:
        print(f"\nWarning: {w}")
    print(f"\nNote: {response.note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
