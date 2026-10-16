"""Tests for settings validation and the command-line script."""

from __future__ import annotations

import pytest

import index_videos
from tanya.config import ConfigError, load_settings, validate_interval
from tests.conftest import make_video


@pytest.mark.parametrize("value", [1, 1.0, 1.5, "2", 2.0])
def test_valid_intervals(value):
    assert 1.0 <= validate_interval(value) <= 2.0


@pytest.mark.parametrize("value", [0, 0.5, 2.01, 10, -1, "abc", None])
def test_invalid_intervals(value):
    with pytest.raises(ConfigError):
        validate_interval(value)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Point the CLI at temporary folders through environment variables."""
    videos = tmp_path / "videos"
    videos.mkdir()
    monkeypatch.setenv("TANYA_VIDEO_DIR", str(videos))
    monkeypatch.setenv("TANYA_FRAMES_DIR", str(tmp_path / "frames"))
    monkeypatch.setenv("TANYA_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TANYA_FRAME_INTERVAL_SEC", "1.0")
    monkeypatch.setenv("TANYA_JPEG_QUALITY", "90")
    return videos


def test_settings_from_env(cli_env, tmp_path):
    s = load_settings()
    assert s.video_dir == cli_env.resolve()
    assert s.db_path == (tmp_path / "test.db").resolve()
    assert load_settings(interval=1.5).frame_interval_sec == 1.5


def test_bad_env_interval(cli_env, monkeypatch):
    monkeypatch.setenv("TANYA_FRAME_INTERVAL_SEC", "5")
    with pytest.raises(ConfigError):
        load_settings()


def test_cli_end_to_end(cli_env, capsys):
    make_video(cli_env / "cam1.avi")

    assert index_videos.main([]) == 0
    out = capsys.readouterr().out
    assert "Indexed: 1" in out and "cam1.avi: 5 frames" in out

    assert index_videos.main([]) == 0
    assert "Skipped: 1" in capsys.readouterr().out

    assert index_videos.main(["--force", "--interval", "2"]) == 0
    out = capsys.readouterr().out
    assert "Indexed: 1" in out and "3 frames" in out


def test_cli_reports_failures_with_exit_code(cli_env, capsys):
    (cli_env / "broken.mp4").write_bytes(b"nope" * 100)
    assert index_videos.main([]) == 1
    assert "Failed: 1" in capsys.readouterr().out


def test_cli_rejects_bad_interval(cli_env, capsys):
    assert index_videos.main(["--interval", "3"]) == 2
    assert "between 1.0 and 2.0" in capsys.readouterr().err


def test_cli_missing_video_dir(cli_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TANYA_VIDEO_DIR", str(tmp_path / "does-not-exist"))
    assert index_videos.main([]) == 2
    assert "Video directory does not exist" in capsys.readouterr().err
