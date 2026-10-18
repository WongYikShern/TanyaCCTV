"""Settings for the indexer, loaded from environment variables or an optional .env file.

The indexer needs no secrets. Search (Milestone 2) needs GEMINI_API_KEY, which is only ever
passed through the environment to the search subprocess; it is never read or stored here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# backend/tanya/config.py -> project root is two levels above backend/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

MIN_INTERVAL_SEC = 1.0
MAX_INTERVAL_SEC = 2.0
DEFAULT_INTERVAL_SEC = 1.0

SUPPORTED_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".m4v"})


class ConfigError(ValueError):
    """Raised when a setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    video_dir: Path
    frames_dir: Path
    db_path: Path
    frame_interval_sec: float = DEFAULT_INTERVAL_SEC
    jpeg_quality: int = 90


def validate_interval(value: float | str) -> float:
    """Return the interval as a float, or raise ConfigError if it is outside 1-2 seconds."""
    try:
        interval = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"Frame interval must be a number, got {value!r}") from None
    if not (MIN_INTERVAL_SEC <= interval <= MAX_INTERVAL_SEC):
        raise ConfigError(
            f"Frame interval must be between {MIN_INTERVAL_SEC} and {MAX_INTERVAL_SEC} "
            f"seconds, got {interval}"
        )
    return interval


def _resolve(path_str: str) -> Path:
    """Resolve a path; relative paths are taken relative to the project root."""
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_settings(interval: float | str | None = None) -> Settings:
    """Build Settings from the environment (and PROJECT_ROOT/.env if it exists)."""
    load_dotenv(PROJECT_ROOT / ".env")

    video_dir = _resolve(os.getenv("TANYA_VIDEO_DIR", "data/videos"))
    frames_dir = _resolve(os.getenv("TANYA_FRAMES_DIR", "data/frames"))
    db_path = _resolve(os.getenv("TANYA_DB_PATH", "data/tanya.db"))

    if interval is None:
        interval = os.getenv("TANYA_FRAME_INTERVAL_SEC", str(DEFAULT_INTERVAL_SEC))

    try:
        quality = int(os.getenv("TANYA_JPEG_QUALITY", "90"))
    except ValueError:
        raise ConfigError("TANYA_JPEG_QUALITY must be an integer") from None
    if not 1 <= quality <= 100:
        raise ConfigError("TANYA_JPEG_QUALITY must be between 1 and 100")

    return Settings(
        video_dir=video_dir,
        frames_dir=frames_dir,
        db_path=db_path,
        frame_interval_sec=validate_interval(interval),
        jpeg_quality=quality,
    )


# --------------------------------------------------------------------------- search (Milestone 2)

# SentrySearch (the natural-language search engine) runs in its own Python 3.12 environment and
# is reached through search_engine/tanya_bridge.py. GEMINI_API_KEY is never read here: it is only
# passed through the environment to that subprocess.
SEARCHABLE_EXTENSIONS = frozenset({".mp4", ".mov"})  # what SentrySearch can index


@dataclass(frozen=True)
class SearchSettings:
    sentry_python: Path | None  # python.exe of the SentrySearch env; None = search not configured
    bridge_path: Path
    sentry_db: Path | None = None  # None = SentrySearch's default index (~/.sentrysearch/db)
    timeout_sec: float = 60.0
    merge_ratio: float = 0.5  # grouping only; never affects result status
    merge_gap_sec: float = 0.0


def _float_env(name: str, default: float, low: float, high: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


PINNED_SENTRYSEARCH_COMMIT = "d3efd6a4351251084dc101a24970e40a38e1426d"


def local_sentry_python() -> Path:
    """Interpreter of the optional project-local search environment (.venv/sentry)."""
    sub = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return PROJECT_ROOT / ".venv" / "sentry" / sub


def load_search_settings() -> SearchSettings:
    """Build SearchSettings from the environment (and PROJECT_ROOT/.env if it exists).

    The search interpreter is TANYA_SENTRY_PYTHON if set, otherwise .venv/sentry if it exists.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    python = os.getenv("TANYA_SENTRY_PYTHON", "").strip()
    db = os.getenv("TANYA_SENTRY_DB", "").strip()
    if python:
        sentry_python = Path(python).expanduser()
    else:
        sentry_python = local_sentry_python() if local_sentry_python().is_file() else None
    return SearchSettings(
        sentry_python=sentry_python,
        bridge_path=_resolve(os.getenv("TANYA_SENTRY_BRIDGE", "search_engine/tanya_bridge.py")),
        sentry_db=_resolve(db) if db else None,
        timeout_sec=_float_env("TANYA_SEARCH_TIMEOUT_SEC", 60.0, 1.0, 600.0),
        merge_ratio=_float_env("TANYA_MERGE_RATIO", 0.5, 0.0, 1.0),
        merge_gap_sec=_float_env("TANYA_MERGE_GAP_SEC", 0.0, 0.0, 10.0),
    )
