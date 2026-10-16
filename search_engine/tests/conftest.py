"""Fixtures for the bridge tests. Run these with the SentrySearch Python 3.12 environment.

Configuration (environment variables, all optional):
  TANYA_SENTRY_PYTHON      python.exe of the pinned SentrySearch env, used for subprocess tests
  TANYA_BRIDGE_TEST_INDEX  index holding the synthetic trial footage (default ~/.sentrysearch/db)
  TANYA_LIVE_REPORT        if set, live tests write their JSON results to this file
Tests that need something missing are skipped, never failed.

Ground truth for the synthetic trial footage:
  cam1_lobby.mp4   person walking 20-40 s, person lying on the floor 40-60 s
  cam2_carpark.mp4 red car driving through 20-40 s
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))  # import tanya_bridge

BRIDGE = ENGINE_DIR / "tanya_bridge.py"
_py = os.environ.get("TANYA_SENTRY_PYTHON")
BRIDGE_PYTHON = Path(_py) if _py else None
SOURCE_INDEX = Path(os.environ.get("TANYA_BRIDGE_TEST_INDEX", Path.home() / ".sentrysearch" / "db"))
LIVE_REPORT = os.environ.get("TANYA_LIVE_REPORT")

EVENTS = {
    "walking": ("cam1_lobby.mp4", 20.0, 40.0),
    "lying": ("cam1_lobby.mp4", 40.0, 60.0),
    "red_car": ("cam2_carpark.mp4", 20.0, 40.0),
}


def overlaps(result: dict, event: tuple[str, float, float]) -> bool:
    name, start, end = event
    return result["filename"] == name and result["start_sec"] < end and result["end_sec"] > start


@pytest.fixture
def bridge_python() -> Path:
    if BRIDGE_PYTHON is None or not BRIDGE_PYTHON.is_file():
        pytest.skip("TANYA_SENTRY_PYTHON not set to the SentrySearch env's python.exe")
    return BRIDGE_PYTHON


@pytest.fixture
def index_copy(tmp_path) -> Path:
    """A private copy of the synthetic trial index, so tests never modify the real one."""
    if not (SOURCE_INDEX / "chroma.sqlite3").exists():
        pytest.skip(f"synthetic trial index not found at {SOURCE_INDEX}")
    dst = tmp_path / "db"
    shutil.copytree(SOURCE_INDEX, dst)
    from sentrysearch.store import SentryStore

    files = SentryStore(db_path=dst, backend="gemini").get_stats()["source_files"]
    if sorted(Path(f).name for f in files) != ["cam1_lobby.mp4", "cam2_carpark.mp4"]:
        pytest.skip("index does not contain exactly the synthetic trial footage")
    return dst


@pytest.fixture
def chunk_embeddings(index_copy) -> dict[tuple[str, float], list[float]]:
    """Real stored chunk embeddings keyed by (filename, start_sec)."""
    from sentrysearch.store import SentryStore

    got = SentryStore(db_path=index_copy, backend="gemini").collection.get(include=["embeddings", "metadatas"])
    return {
        (Path(m["source_file"]).name, float(m["start_time"])): list(e)
        for m, e in zip(got["metadatas"], got["embeddings"])
    }


class FakeEmbedder:
    """Stands in for Gemini: returns a fixed query vector, makes no network calls."""

    def __init__(self, vector=None, error: Exception | None = None, chatter: str = ""):
        self.vector, self.error, self.chatter = vector, error, chatter

    def embed_query(self, text, verbose=False):
        if self.chatter:
            print(self.chatter)
            print(self.chatter, file=sys.stderr)
        if self.error:
            raise self.error
        return self.vector


@pytest.fixture
def fake_embedder(monkeypatch):
    """Install a FakeEmbedder as SentrySearch's active embedder."""
    import sentrysearch.embedder as emb

    def install(**kwargs) -> FakeEmbedder:
        fake = FakeEmbedder(**kwargs)
        monkeypatch.setattr(emb, "_current_embedder", fake)
        return fake

    yield install
    monkeypatch.setattr(emb, "_current_embedder", None)
