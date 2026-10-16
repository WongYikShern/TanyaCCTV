"""End-to-end test through the REAL SentrySearch environment and bridge, without an API key.

TanyaCCTV search -> sentry_client -> subprocess (Python 3.12) -> tanya_bridge -> real Chroma index
-> SentrySearch search_footage -> JSON -> path mapping -> merging -> thumbnails.
Only Gemini's text embedding is replaced (see search_engine/tests/e2e_shim_bridge.py).

Skipped unless TANYA_SENTRY_PYTHON points at the SentrySearch env and the synthetic trial index
(cam1_lobby.mp4 + cam2_carpark.mp4) and its footage exist. The index is copied; the footage is
only read; TanyaCCTV's database and frames for it are created in a temporary folder.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from tanya import sentry_client
from tanya.config import SearchSettings, Settings
from tanya.indexer import Indexer
from tanya.search import search_videos

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "search_engine" / "tests" / "e2e_shim_bridge.py"
SOURCE_INDEX = Path(os.environ.get("TANYA_BRIDGE_TEST_INDEX", Path.home() / ".sentrysearch" / "db"))
PY = os.environ.get("TANYA_SENTRY_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not (PY and Path(PY).is_file() and (SOURCE_INDEX / "chroma.sqlite3").exists()),
    reason="needs TANYA_SENTRY_PYTHON and the synthetic SentrySearch trial index",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    index = tmp / "index"
    shutil.copytree(SOURCE_INDEX, index)
    search_settings = SearchSettings(sentry_python=Path(PY), bridge_path=SHIM, sentry_db=index, timeout_sec=180)
    files = sentry_client.stats(search_settings)["source_files"]
    names = sorted(Path(f).name for f in files)
    footage = Path(files[0]).parent if files else None
    if names != ["cam1_lobby.mp4", "cam2_carpark.mp4"] or not all(Path(f).is_file() for f in files):
        pytest.skip("index does not hold exactly the synthetic trial footage")
    footage_hashes = {f: sha(Path(f)) for f in files}

    settings = Settings(video_dir=footage, frames_dir=tmp / "frames", db_path=tmp / "tanya.db")
    summary = Indexer(settings, log=lambda _m: None).run()   # reads footage, writes only to tmp
    assert not summary.has_failures
    yield settings, search_settings, footage_hashes, index
    assert {f: sha(Path(f)) for f in footage_hashes} == footage_hashes  # footage never modified


def run(e2e, chunk: str, monkeypatch):
    settings, search_settings, *_ = e2e
    monkeypatch.setenv("E2E_QUERY_CHUNK", chunk)
    return search_videos("e2e query", settings, search_settings, n=13)


def test_lobby_query_maps_to_lobby_video_with_valid_window_and_thumbnail(e2e, monkeypatch):
    settings = e2e[0]
    response = run(e2e, "cam1_lobby.mp4@24", monkeypatch)

    top = response.hits[0]
    assert top.rel_path == "cam1_lobby.mp4" and top.filename == "cam1_lobby.mp4"
    assert top.best_score == pytest.approx(1.0, abs=1e-3)               # the query chunk itself
    assert any(c.start_sec == 24.0 and c.end_sec == 34.0 for c in top.chunks)
    assert 0 <= top.start_sec <= 24.0 and 34.0 <= top.end_sec <= 60.0
    assert top.thumbnail and (settings.frames_dir / top.thumbnail).is_file()
    assert top.start_sec <= top.thumbnail_timestamp_sec <= top.end_sec
    video_id = sqlite3.connect(settings.db_path).execute(
        "SELECT id FROM videos WHERE rel_path = 'cam1_lobby.mp4'").fetchone()[0]
    assert top.video_id == video_id
    assert {h.status for h in response.hits} == {"uncertain"}
    assert not any("outside the video folder" in w for w in response.warnings)


def test_carpark_query_ranks_carpark_first(e2e, monkeypatch):
    response = run(e2e, "cam2_carpark.mp4@24", monkeypatch)
    assert response.hits[0].rel_path == "cam2_carpark.mp4"
    assert {h.status for h in response.hits} == {"uncertain"}


def test_every_chunk_is_accounted_for_and_windows_are_within_videos(e2e, monkeypatch):
    response = run(e2e, "cam1_lobby.mp4@40", monkeypatch)
    chunks = [c for h in response.hits for c in h.chunks]
    assert len(chunks) == 13                                            # 8 lobby + 5 car park, none dropped
    durations = {"cam1_lobby.mp4": 60.0, "cam2_carpark.mp4": 40.0}
    for h in response.hits:
        assert 0 <= h.start_sec < h.end_sec <= durations[h.rel_path] + 0.01
        assert h.start_sec == min(c.start_sec for c in h.chunks) and h.end_sec == max(c.end_sec for c in h.chunks)


def test_search_is_read_only(e2e, monkeypatch):
    settings, _, _, index = e2e
    db_before = sha(settings.db_path)
    run(e2e, "cam2_carpark.mp4@16", monkeypatch)
    assert sha(settings.db_path) == db_before
    assert not (settings.db_path.parent / "search_index_manifest.json").exists()
