"""Fixtures for the search-integration tests (fake bridge, no SentrySearch, no network, no key).

The synthetic videos mirror the SentrySearch trial footage, so recorded live results map onto them:
  cam1_lobby.mp4   60 s  (walking 20-40 s, lying on the floor 40-60 s)
  cam2_carpark.mp4 40 s  (red car 20-40 s)
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tanya.config import SearchSettings
from tests.conftest import make_video

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_BRIDGE = FIXTURES / "fake_bridge.py"
FAKE_CLI = [sys.executable, str(FIXTURES / "fake_sentry_cli.py")]
FAKE_KEY = "FAKE-TEST-KEY-not-real-tanya-0123456789"  # never a real key


class SearchEnv:
    def __init__(self, workspace, tmp_path: Path):
        self.ws = workspace
        self.settings = workspace.settings()
        self.search_settings = SearchSettings(sentry_python=Path(sys.executable), bridge_path=FAKE_BRIDGE,
                                              timeout_sec=20)
        self.log_file = tmp_path / "bridge_calls.log"
        self.state_file = tmp_path / "bridge_state.json"
        self.set_indexed([])

    def with_search(self, **changes) -> SearchSettings:
        return replace(self.search_settings, **changes)

    def set_indexed(self, source_files: list[str]) -> None:
        self.state_file.write_text(json.dumps({"source_files": source_files}), encoding="utf-8")

    def indexed(self) -> list[str]:
        return json.loads(self.state_file.read_text(encoding="utf-8"))["source_files"]

    def calls(self) -> list[list[str]]:
        if not self.log_file.exists():
            return []
        return [json.loads(line) for line in self.log_file.read_text(encoding="utf-8").splitlines()]

    def source(self, rel: str) -> str:
        """The exact string SentrySearch would store for a video (os.path.abspath)."""
        import os
        return os.path.abspath(self.settings.video_dir.resolve() / rel)


@pytest.fixture
def search_env(workspace, tmp_path, monkeypatch) -> SearchEnv:
    make_video(workspace.video_dir / "cam1_lobby.mp4", seconds=60, fps=2, seed=1)
    make_video(workspace.video_dir / "cam2_carpark.mp4", seconds=40, fps=2, seed=2)
    workspace.run()
    env = SearchEnv(workspace, tmp_path)
    monkeypatch.setenv("FAKE_VIDEO_DIR", str(workspace.video_dir.resolve()))
    monkeypatch.setenv("FAKE_BRIDGE_LOG", str(env.log_file))
    monkeypatch.setenv("FAKE_BRIDGE_STATE", str(env.state_file))
    monkeypatch.delenv("FAKE_BRIDGE_MODE", raising=False)
    monkeypatch.delenv("FAKE_CLI_MODE", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    return env


@pytest.fixture
def cli_env(search_env, monkeypatch) -> SearchEnv:
    """search_env, plus the TANYA_* variables the command-line scripts read."""
    s = search_env.settings
    monkeypatch.setenv("TANYA_VIDEO_DIR", str(s.video_dir))
    monkeypatch.setenv("TANYA_FRAMES_DIR", str(s.frames_dir))
    monkeypatch.setenv("TANYA_DB_PATH", str(s.db_path))
    monkeypatch.setenv("TANYA_SENTRY_PYTHON", str(search_env.search_settings.sentry_python))
    monkeypatch.setenv("TANYA_SENTRY_BRIDGE", str(search_env.search_settings.bridge_path))
    for name in ("TANYA_SENTRY_DB", "TANYA_MERGE_RATIO", "TANYA_MERGE_GAP_SEC", "TANYA_SEARCH_TIMEOUT_SEC"):
        monkeypatch.delenv(name, raising=False)
    return search_env
