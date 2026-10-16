"""Runs search_engine/tanya_bridge.py inside the SentrySearch environment and checks its JSON.

The bridge prints exactly one JSON line on stdout. Anything else (non-JSON, ok=false, a non-zero
exit, a timeout) becomes a SearchError. GEMINI_API_KEY is passed to the subprocess only through
the inherited environment; the only thing this module does with it is redact it from messages.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .config import SearchSettings

REQUIRED_RESULT_KEYS = {"rank", "source_file", "filename", "start_sec", "end_sec",
                        "score", "score_above_median", "status"}


class SearchError(Exception):
    """The search engine failed or returned something unusable."""


class SearchNotConfiguredError(SearchError):
    """TANYA_SENTRY_PYTHON or the bridge script is missing."""


def redact(text: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if len(key) >= 8:
        text = text.replace(key, "***REDACTED***")
    return text


def _command(settings: SearchSettings, args: list[str], positional: list[str] | None = None) -> list[str]:
    """Bridge command line. `positional` goes after "--" so values starting with "-" stay values."""
    if settings.sentry_python is None:
        raise SearchNotConfiguredError(
            "Search is not configured: set TANYA_SENTRY_PYTHON to the SentrySearch environment's "
            "python.exe (see README, 'Natural-language search')")
    if not settings.sentry_python.is_file():
        raise SearchNotConfiguredError(f"TANYA_SENTRY_PYTHON does not exist: {settings.sentry_python}")
    if not settings.bridge_path.is_file():
        raise SearchNotConfiguredError(f"Bridge script not found: {settings.bridge_path}")
    db_args = ["--db", str(settings.sentry_db)] if settings.sentry_db else []
    tail = ["--", *positional] if positional else []
    return [str(settings.sentry_python), str(settings.bridge_path), *args, *db_args, *tail]


def run_bridge(settings: SearchSettings, args: list[str], positional: list[str] | None = None) -> dict:
    """Run one bridge command and return its JSON payload (ok=true), or raise SearchError."""
    cmd = _command(settings, args, positional)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=settings.timeout_sec, cwd=settings.bridge_path.parent)
    except subprocess.TimeoutExpired:
        raise SearchError(f"search engine timed out after {settings.timeout_sec:g}s") from None
    except OSError as e:
        raise SearchError(redact(f"could not start the search engine: {e}")) from None

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        tail = redact(proc.stderr.strip().splitlines()[-1]) if proc.stderr.strip() else "no details"
        raise SearchError(f"search engine returned no valid JSON (exit {proc.returncode}): {tail[:300]}")
    if not data.get("ok"):
        kind = data.get("error_type", "error")
        raise SearchError(redact(f"search engine error ({kind}): {data.get('error', 'unknown')}"))
    if proc.returncode != 0:
        raise SearchError(f"search engine exited with code {proc.returncode}")
    return data


def search(settings: SearchSettings, query: str, n: int = 10) -> dict:
    """Ranked chunks for a query. Every result has status 'uncertain' (needs human review)."""
    if not query.strip():
        raise SearchError("query must not be empty")
    if not 1 <= n <= 100:
        raise SearchError("n must be between 1 and 100")
    # The query goes after "--": a query such as "-fire" must not be parsed as an option.
    data = run_bridge(settings, ["search", "--n", str(n)], positional=[query])
    results = data.get("results")
    if not isinstance(results, list):
        raise SearchError("search engine response has no results list")
    for r in results:
        if not isinstance(r, dict) or not REQUIRED_RESULT_KEYS <= set(r):
            raise SearchError("search engine returned a result with missing fields")
        if r["status"] != "uncertain":
            raise SearchError(f"unexpected result status {r['status']!r}; expected 'uncertain'")
        if not (isinstance(r["start_sec"], (int, float)) and isinstance(r["end_sec"], (int, float))
                and 0 <= r["start_sec"] < r["end_sec"]):
            raise SearchError("search engine returned an invalid time window")
    return data


def stats(settings: SearchSettings) -> dict:
    """Indexed source files (exact strings as stored by SentrySearch). No API call."""
    return run_bridge(settings, ["stats"])


def remove(settings: SearchSettings, source_file: str, within: Path) -> int:
    """Remove one exactly-matching indexed file inside `within`. Returns chunks removed."""
    data = run_bridge(settings, ["remove", "--source-file", source_file, "--within", str(within)])
    return int(data["removed_chunks"])
