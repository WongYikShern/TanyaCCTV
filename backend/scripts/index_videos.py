"""Index authorised sample CCTV videos: extract frames and store metadata in SQLite.

Usage (from the project root, with the virtual environment active):
    python backend/scripts/index_videos.py
    python backend/scripts/index_videos.py --interval 1.5
    python backend/scripts/index_videos.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the `tanya` package importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tanya.config import MAX_INTERVAL_SEC, MIN_INTERVAL_SEC, ConfigError, load_settings  # noqa: E402
from tanya.indexer import FAILED, INDEXED, SKIPPED, UNSUPPORTED, Indexer  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract frames from CCTV videos and index them in SQLite.")
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help=f"seconds between extracted frames ({MIN_INTERVAL_SEC}-{MAX_INTERVAL_SEC}); "
        "default: TANYA_FRAME_INTERVAL_SEC or 1.0",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-index every video even if it was already indexed",
    )
    return parser.parse_args(argv)


def print_summary(summary) -> None:
    print("\n=== Indexing summary ===")
    sections = [
        (INDEXED, "Indexed"),
        (SKIPPED, "Skipped"),
        (FAILED, "Failed"),
        (UNSUPPORTED, "Ignored (unsupported file type)"),
    ]
    for status, title in sections:
        items = summary.by_status(status)
        print(f"{title}: {len(items)}")
        for o in items:
            print(f"  - {o.rel_path}: {o.message}")
    print(f"Removed stale index entries: {len(summary.removed)}")
    for rel in summary.removed:
        print(f"  - {rel}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(interval=args.interval)
        print(f"Video directory : {settings.video_dir}")
        print(f"Frames directory: {settings.frames_dir}")
        print(f"Database        : {settings.db_path}")
        print(f"Frame interval  : {settings.frame_interval_sec}s{'  (force)' if args.force else ''}\n")
        summary = Indexer(settings, force=args.force).run()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. Run the script again to finish; partial work is retried safely.", file=sys.stderr)
        return 130

    print_summary(summary)
    return 1 if summary.has_failures else 0


if __name__ == "__main__":
    sys.exit(main())
