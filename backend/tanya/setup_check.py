"""Read-only environment checks for TanyaCCTV (used by scripts/check_setup.py).

Nothing here creates, changes or deletes files, and the Gemini key is only checked for
presence: its value is never read into a message. FAIL means the local website/indexer cannot
work; WARN means an optional part (usually AI search) is unavailable or at risk.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import PINNED_SENTRYSEARCH_COMMIT, ConfigError, load_search_settings, load_settings

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
WEB_PORT = 5001
MIN_FREE_GB = 2.0


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _existing_parent(path: Path) -> Path:
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def check_python() -> Check:
    v = sys.version_info
    if v < (3, 11):
        return Check("Python", FAIL, f"Python {v.major}.{v.minor} is too old",
                     "Install Python 3.12 or newer and recreate .venv")
    return Check("Python", PASS, f"Python {v.major}.{v.minor}.{v.micro} at {sys.executable}")


def check_packages() -> Check:
    missing, versions = [], []
    for module, dist in (("cv2", "opencv-python-headless"), ("flask", "Flask"), ("dotenv", "python-dotenv")):
        try:
            importlib.import_module(module)
        except Exception:  # noqa: BLE001 - any import failure means the package is unusable
            missing.append(dist)
            continue
        try:
            versions.append(f"{dist} {importlib.metadata.version(dist)}")
        except importlib.metadata.PackageNotFoundError:
            versions.append(f"{dist} (version unknown)")
    if missing:
        return Check("Packages", FAIL, "missing: " + ", ".join(missing),
                     r"Run: .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt")
    return Check("Packages", PASS, ", ".join(versions))


def check_data(settings) -> list[Check]:
    checks = []
    for label, folder in (("Video folder", settings.video_dir), ("Frames folder", settings.frames_dir)):
        base = _existing_parent(folder)
        if folder.exists() and not folder.is_dir():
            checks.append(Check(label, FAIL, f"{folder} is a file, not a folder", "Fix the TANYA_* path in .env"))
        elif not os.access(base, os.W_OK):
            checks.append(Check(label, FAIL, f"cannot write to {base}", "Choose a writable folder in .env"))
        else:
            note = "" if folder.exists() else " (created when first used)"
            checks.append(Check(label, PASS, f"{folder}{note}"))
    if settings.db_path.exists():
        try:
            conn = sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                ok = conn.execute("PRAGMA quick_check").fetchone()[0]
                n = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            finally:
                conn.close()
            checks.append(Check("Database", PASS if ok == "ok" else FAIL,
                                f"{settings.db_path}: {n} video(s), integrity {ok}",
                                "" if ok == "ok" else "Restore the database from a backup or re-run indexing"))
        except sqlite3.Error as e:
            checks.append(Check("Database", FAIL, f"cannot read {settings.db_path}: {e}",
                                "Close other programs using it; re-run indexing if it is corrupt"))
    else:
        checks.append(Check("Database", PASS, f"{settings.db_path} (created by the first indexing run)"))
    free_gb = shutil.disk_usage(_existing_parent(settings.video_dir)).free / 1e9
    checks.append(Check("Disk space", PASS if free_gb >= MIN_FREE_GB else WARN, f"{free_gb:.1f} GB free",
                        "" if free_gb >= MIN_FREE_GB else "Free some space; each hour of video adds ~3,600 JPEG frames"))
    if "onedrive" in str(settings.video_dir).lower() or "onedrive" in str(settings.frames_dir).lower():
        checks.append(Check("OneDrive", WARN, "data folders are inside OneDrive; sync can lock files during indexing",
                            "Pause OneDrive while indexing, or set TANYA_VIDEO_DIR/TANYA_FRAMES_DIR outside OneDrive"))
    return checks


def check_port(port: int = WEB_PORT) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return Check("Website port", WARN, f"127.0.0.1:{port} is already in use",
                         "Another TanyaCCTV website may be running; open http://localhost:5001/ or stop it")
    return Check("Website port", PASS, f"127.0.0.1:{port} is free")


def _installed_commit(python: Path) -> str | None:
    code = ("import importlib.metadata as m, json; "
            "print(json.loads(m.distribution('sentrysearch').read_text('direct_url.json') or '{}')"
            ".get('vcs_info', {}).get('commit_id', ''))")
    try:
        proc = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def check_search(search_settings) -> list[Check]:
    py = search_settings.sentry_python
    if py is None:
        return [Check("Search engine", WARN, "not configured: AI search is disabled (local features still work)",
                      "Set TANYA_SENTRY_PYTHON or create .venv\\sentry (README: one-time setup)")]
    if not py.is_file():
        return [Check("Search engine", WARN, f"TANYA_SENTRY_PYTHON does not exist: {py}",
                      "Point TANYA_SENTRY_PYTHON at the SentrySearch environment's python.exe")]
    checks = []
    exe = any((py.parent / name).is_file() for name in ("sentrysearch.exe", "sentrysearch"))
    commit = _installed_commit(py)
    if commit is None:
        checks.append(Check("Search engine", WARN, f"{py} does not have SentrySearch installed",
                            "Install the pinned SentrySearch (README: one-time setup)"))
    elif commit != PINNED_SENTRYSEARCH_COMMIT:
        checks.append(Check("Search engine", WARN, f"SentrySearch commit {commit[:7] or 'unknown'} is not the "
                            f"tested pin {PINNED_SENTRYSEARCH_COMMIT[:7]}", "Reinstall the pinned commit"))
    elif not exe:
        checks.append(Check("Search engine", WARN, "sentrysearch executable missing next to the interpreter",
                            "Reinstall SentrySearch into that environment"))
    else:
        checks.append(Check("Search engine", PASS, f"SentrySearch {commit[:7]} (pinned) at {py}"))
    bridge = search_settings.bridge_path
    checks.append(Check("Search bridge", PASS if bridge.is_file() else WARN, str(bridge),
                        "" if bridge.is_file() else "Restore search_engine/tanya_bridge.py from Git"))
    return checks


def check_key() -> Check:
    # Presence only. The value is never read into any message.
    if os.environ.get("GEMINI_API_KEY"):
        return Check("Gemini API key", PASS, "set in this environment (value not shown)")
    return Check("Gemini API key", WARN, "not set in this environment: AI search and preparation are disabled",
                 "Set GEMINI_API_KEY in this terminal before starting (README: Windows PowerShell)")


def run_all() -> list[Check]:
    checks = [check_python(), check_packages()]
    try:
        settings = load_settings()
        search_settings = load_search_settings()
    except ConfigError as e:
        return checks + [Check("Configuration", FAIL, str(e), "Fix the value in .env or the environment")]
    checks += check_data(settings) + [check_port()] + check_search(search_settings) + [check_key()]
    return checks


def summary_lines(checks: list[Check]) -> list[str]:
    lines = []
    for c in checks:
        lines.append(f"[{c.status}] {c.name}: {c.detail}")
        if c.fix and c.status != PASS:
            lines.append(f"       fix: {c.fix}")
    return lines


def as_json(checks: list[Check]) -> str:
    return json.dumps([c.__dict__ for c in checks], indent=2)
