"""Settings for the indexer, loaded from environment variables or an optional .env file.

No secrets are needed for this milestone. Later milestones should also read
their secrets (e.g. bot tokens) from the environment, never from code.
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
