"""Tests for search mapping, chunk merging and thumbnails (fake bridge with recorded live scores)."""

from __future__ import annotations

import hashlib
import json

import pytest

import search_videos as search_cli
from tanya import search_sync
from tanya.search import Chunk, merge_chunks, search_videos
from tests.conftest import make_video
from tests.search_fixtures import FAKE_KEY, search_env  # noqa: F401


def C(start, end, score, above, rank=0):
    return Chunk(rank, float(start), float(end), score, above)


def windows(groups):
    return [(g[0].start_sec, max(c.end_sec for c in g)) for g in groups]


# --------------------------------------------------------------------------- merge_chunks (unit)


def test_overlapping_chunks_merge():
    groups = merge_chunks([C(16, 26, .40, .057), C(24, 34, .39, .052), C(32, 42, .39, .048)])
    assert windows(groups) == [(16, 42)] and len(groups[0]) == 3


def test_adjacent_chunks_merge_when_touching():
    assert windows(merge_chunks([C(0, 10, .5, .10), C(10, 20, .5, .09)])) == [(0, 20)]


def test_gap_setting_controls_near_but_not_touching_chunks():
    chunks = [C(0, 10, .5, .10), C(12, 22, .5, .09)]
    assert windows(merge_chunks(chunks, gap_sec=0)) == [(0, 10), (12, 22)]
    assert windows(merge_chunks(chunks, gap_sec=2)) == [(0, 22)]


def test_unrelated_chunks_stay_separate():
    groups = merge_chunks([C(0, 10, .5, .10), C(40, 50, .49, .09)])
    assert windows(groups) == [(0, 10), (40, 50)]


def test_weak_neighbour_not_merged_at_default_ratio():
    # Recorded "a red car": event chunks ~+0.12, empty car-park chunk 8-18 at +0.052 (43%).
    chunks = [C(24, 34, .364, .120), C(16, 26, .359, .115), C(32, 40, .357, .113), C(8, 18, .296, .052)]
    assert windows(merge_chunks(chunks, ratio=0.5)) == [(16, 40), (8, 18)]
    assert windows(merge_chunks(chunks, ratio=0.0)) == [(8, 40)]   # configurable: merge everything touching
    assert len(merge_chunks(chunks, ratio=1.0)) == 4                # only equal-or-better: no merging


def test_seed_at_or_below_median_absorbs_nothing():
    assert len(merge_chunks([C(0, 10, .3, 0.0), C(8, 18, .29, -.01)], ratio=0.0)) == 2


def test_invalid_merge_settings():
    with pytest.raises(ValueError):
        merge_chunks([], ratio=1.5)
    with pytest.raises(ValueError):
        merge_chunks([], gap_sec=-1)


# --------------------------------------------------------------------------- search_videos (integration)


def test_recorded_queries_map_to_expected_windows(search_env):
    s, ss = search_env.settings, search_env.search_settings
    walking = search_videos("a person walking", s, ss, n=5).hits
    assert (walking[0].rel_path, walking[0].start_sec, walking[0].end_sec) == ("cam1_lobby.mp4", 16, 42)
    lying = search_videos("a person lying on the floor", s, ss, n=5).hits
    assert (lying[0].rel_path, lying[0].start_sec, lying[0].end_sec) == ("cam1_lobby.mp4", 40, 60)
    car = search_videos("a red car", s, ss, n=5).hits
    assert (car[0].rel_path, car[0].start_sec, car[0].end_sec) == ("cam2_carpark.mp4", 16, 40)
    assert car[0].video_id == search_env.ws.rows("SELECT id FROM videos WHERE rel_path='cam2_carpark.mp4'")[0][0]


@pytest.mark.parametrize("ratio", [0.0, 0.5, 1.0])
def test_status_is_always_uncertain_whatever_the_merge_ratio(search_env, ratio):
    ss = search_env.with_search(merge_ratio=ratio)
    for q in ("a person walking", "a person lying on the floor", "a red car", "fire and smoke"):
        response = search_videos(q, search_env.settings, ss, n=5)
        assert response.hits and {h.status for h in response.hits} == {"uncertain"}
        assert "not prove" in response.note


def test_negative_query_returns_ranked_uncertain_clips_not_absence_claim(search_env):
    response = search_videos("fire and smoke", search_env.settings, search_env.search_settings, n=5)
    assert response.hits and all(h.status == "uncertain" for h in response.hits)
    assert "absent" in response.note


def test_results_outside_video_folder_are_ignored(search_env, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_VIDEO_DIR", str(tmp_path / "sentrysearch-trial" / "footage"))
    response = search_videos("a red car", search_env.settings, search_env.search_settings, n=5)
    assert response.hits == []
    assert any("outside the video folder" in w for w in response.warnings)


def test_results_for_videos_not_indexed_by_tanya_are_ignored(search_env):
    (search_env.settings.video_dir / "cam2_carpark.mp4").rename(search_env.settings.video_dir / "renamed.mp4")
    search_env.ws.run()  # TanyaCCTV now knows the video only as renamed.mp4
    response = search_videos("a red car", search_env.settings, search_env.search_settings, n=5)
    assert all(h.rel_path != "cam2_carpark.mp4" for h in response.hits)
    assert any("cam2_carpark.mp4 is not indexed by TanyaCCTV" in w for w in response.warnings)


def test_thumbnail_is_nearest_frame_inside_window(search_env):
    hit = search_videos("a person lying on the floor", search_env.settings, search_env.search_settings, n=5).hits[0]
    assert hit.thumbnail and (search_env.settings.frames_dir / hit.thumbnail).is_file()
    assert hit.thumbnail_timestamp_sec == 50.0  # middle of 40-60


def test_missing_thumbnail_files_are_reported_not_fatal(search_env):
    for jpg in search_env.settings.frames_dir.rglob("*.jpg"):
        jpg.unlink()
    response = search_videos("a red car", search_env.settings, search_env.search_settings, n=5)
    assert response.hits and all(h.thumbnail is None for h in response.hits)
    assert any("no thumbnail" in w for w in response.warnings)


def test_unsearchable_formats_are_listed(search_env):
    make_video(search_env.settings.video_dir / "old_cam.avi", seconds=3)
    search_env.ws.run()
    response = search_videos("a red car", search_env.settings, search_env.search_settings, n=5)
    assert any("old_cam.avi" in w and ".mp4/.mov" in w for w in response.warnings)


def test_stale_warning_until_videos_are_synced(search_env):
    s, ss = search_env.settings, search_env.search_settings
    assert any("may be stale" in w for w in search_videos("a red car", s, ss).warnings)
    sha = search_env.ws.rows("SELECT sha256 FROM videos WHERE rel_path='cam2_carpark.mp4'")[0][0]
    search_sync.save_manifest(s, {search_env.source("cam2_carpark.mp4"): {"sha256": sha}})
    warnings = search_videos("a red car", s, ss, n=3).warnings  # top 3 are all cam2_carpark
    assert not any("may be stale" in w for w in warnings)


def test_search_never_indexes_removes_or_writes_the_database(search_env):
    db = search_env.settings.db_path
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    search_videos("a person walking", search_env.settings, search_env.search_settings)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert [c[0] for c in search_env.calls()] == ["search"]
    assert not search_sync.manifest_path(search_env.settings).exists()


# --------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_env(search_env, monkeypatch):
    s = search_env.settings
    monkeypatch.setenv("TANYA_VIDEO_DIR", str(s.video_dir))
    monkeypatch.setenv("TANYA_FRAMES_DIR", str(s.frames_dir))
    monkeypatch.setenv("TANYA_DB_PATH", str(s.db_path))
    monkeypatch.setenv("TANYA_SENTRY_PYTHON", str(search_env.search_settings.sentry_python))
    monkeypatch.setenv("TANYA_SENTRY_BRIDGE", str(search_env.search_settings.bridge_path))
    for name in ("TANYA_SENTRY_DB", "TANYA_MERGE_RATIO", "TANYA_MERGE_GAP_SEC", "TANYA_SEARCH_TIMEOUT_SEC"):
        monkeypatch.delenv(name, raising=False)
    return search_env


def test_cli_json_output(cli_env, capsys):
    assert search_cli.main(["a red car", "--n", "5", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["hits"][0]["rel_path"] == "cam2_carpark.mp4"
    assert {h["status"] for h in data["hits"]} == {"uncertain"}


def test_cli_text_output(cli_env, capsys):
    assert search_cli.main(["a person walking", "--n", "5"]) == 0
    out = capsys.readouterr().out
    assert "cam1_lobby.mp4  00:16-00:42" in out and "[uncertain]" in out and "needs review" in out


def test_cli_not_configured(cli_env, monkeypatch, capsys):
    monkeypatch.setenv("TANYA_SENTRY_PYTHON", "")
    assert search_cli.main(["x"]) == 2
    assert "TANYA_SENTRY_PYTHON" in capsys.readouterr().err


def test_cli_engine_error_hides_key(cli_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_BRIDGE_MODE", "error")
    assert search_cli.main(["x"]) == 3
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out + captured.err


def test_cli_rejects_bad_merge_ratio(cli_env, monkeypatch, capsys):
    monkeypatch.setenv("TANYA_MERGE_RATIO", "2")
    assert search_cli.main(["x"]) == 2


def test_hit_for_deleted_video_file_is_skipped_with_warning(search_env):
    """Regression: a video deleted from disk (database not yet re-indexed) was still returned."""
    (search_env.settings.video_dir / "cam2_carpark.mp4").unlink()
    response = search_videos("a red car", search_env.settings, search_env.search_settings, n=5)
    assert all(h.rel_path != "cam2_carpark.mp4" for h in response.hits)
    assert any("cam2_carpark.mp4 is in the database but the video file is missing" in w for w in response.warnings)


def test_cli_survives_console_that_cannot_show_the_query(cli_env):
    """Regression: a Chinese query crashed the CLI with UnicodeEncodeError on a cp1252 console."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(search_cli.__file__)
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    proc = subprocess.run([sys.executable, str(script), "有人跌倒"], capture_output=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode("cp1252", "replace")
    assert b"Results for" in proc.stdout


def test_missing_tanya_database_is_a_clear_error_and_engine_not_started(search_env, tmp_path):
    from dataclasses import replace

    from tanya.sentry_client import SearchError

    settings = replace(search_env.settings, db_path=tmp_path / "nope" / "tanya.db")
    with pytest.raises(SearchError, match="Run index_videos.py first"):
        search_videos("a red car", settings, search_env.search_settings)
    assert search_env.calls() == [] and not settings.db_path.exists()
