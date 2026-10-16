"""Opt-in: bring the SentrySearch index in line with TanyaCCTV's indexed videos.

Dry run by default: shows videos to index, entries to remove, estimated frames and API cost,
and changes nothing. Only with --yes does it remove stale entries and call the Gemini API.

    python backend/scripts/sync_search_index.py          # plan only (free, no API calls)
    python backend/scripts/sync_search_index.py --yes    # apply (costs money on the paid tier)

Run index_videos.py first. Searching never runs this automatically.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tanya import search_sync, sentry_client  # noqa: E402
from tanya.config import ConfigError, load_search_settings, load_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on filenames the console can't show
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Sync the SentrySearch index (dry run unless --yes).")
    parser.add_argument("--yes", action="store_true", help="apply the plan (removes entries, calls the API)")
    args = parser.parse_args(argv)

    try:
        settings, search_settings = load_settings(), load_search_settings()
        if not settings.db_path.exists():
            raise ConfigError(f"No TanyaCCTV database at {settings.db_path}. Run index_videos.py first.")
        indexed = sentry_client.stats(search_settings)["source_files"]
        plan = search_sync.build_plan(settings, indexed, search_sync.load_manifest(settings))
        print(search_sync.describe(plan))
        if plan.is_empty:
            print("\nNothing to do.")
            return 0
        if not args.yes:
            print("\nDry run: nothing was changed. Re-run with --yes to apply this plan.")
            return 0
        print("\nApplying plan...")
        ok = search_sync.apply_plan(plan, settings, search_settings,
                                    search_sync.sentry_cli_command(search_settings))
    except (ConfigError, sentry_client.SearchNotConfiguredError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    except sentry_client.SearchError as e:
        print(f"Sync failed: {e}", file=sys.stderr)
        return 3
    print("\nDone." if ok else "\nFinished with failures (see above). Re-run to retry.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
