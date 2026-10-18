"""Browser playback: codec detection, local H.264 copies, waiting files and error reporting.

Root cause these guard against: OpenCV writes MPEG-4 Part 2 ("FMP4"), which Chrome/Edge reject with
MEDIA_ERR_SRC_NOT_SUPPORTED, so the player stayed black with no explanation.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import pytest

from tanya import playback
from tanya.config import SearchSettings
from tanya.web import create_app
from tests.conftest import make_video

TRIAL_PY = Path(os.environ.get("TANYA_SENTRY_PYTHON", "") or "Z:/none")


def ffmpeg_or_skip():
    exe = playback.find_ffmpeg(TRIAL_PY if TRIAL_PY.is_file() else None)
    if not exe:
        pytest.skip("FFmpeg not available (PATH, TANYA_FFMPEG or TANYA_SENTRY_PYTHON)")
    return exe


@pytest.fixture
def app(workspace, monkeypatch):
    monkeypatch.delenv("TANYA_FFMPEG", raising=False)
    playback._ffmpeg_cache.clear()
    a = create_app(workspace.settings(), SearchSettings(TRIAL_PY if TRIAL_PY.is_file() else None,
                                                        workspace.video_dir / "bridge.py"))
    client = a.test_client()
    client.get("/")
    with client.session_transaction() as s:
        headers = {"X-CSRF-Token": s["csrf"]}
    return client, headers, workspace


# --------------------------------------------------------------------------- detection


def test_opencv_test_videos_are_detected_as_not_browser_playable(tmp_path):
    mp4v = make_video(tmp_path / "a.mp4")            # OpenCV mp4v, like make_test_video.py
    avi = make_video(tmp_path / "b.avi")             # MJPEG in AVI
    assert playback.codec_of(mp4v) == "fmp4" and playback.codec_name("fmp4") == "MPEG-4 Part 2"
    assert not playback.browser_playable(mp4v) and not playback.browser_playable(avi)
    assert playback.codec_of(tmp_path / "missing.mp4") == ""


@pytest.mark.parametrize("name, code, ok", [("a.mp4", "avc1", True), ("a.mov", "h264", True), ("a.m4v", "vp09", True),
                                            ("a.mp4", "fmp4", False), ("a.mkv", "h264", False), ("a.avi", "h264", False),
                                            ("a.mp4", "hevc", False), ("a.mp4", "", False)])
def test_browser_playability_rules(name, code, ok):
    assert playback.browser_playable(Path(name), code) is ok


# --------------------------------------------------------------------------- library and playback API


def test_library_reports_playback_status_and_waiting_files(app):
    client, headers, ws = app
    make_video(ws.video_dir / "indexed.mp4", seconds=2)
    ws.run()
    make_video(ws.video_dir / "dropped_in_later.mp4", seconds=2)       # copied in, not indexed yet
    (ws.video_dir / "notes.txt").write_text("not a video")
    data = client.get("/api/videos").json
    assert [v["filename"] for v in data["videos"]] == ["indexed.mp4"]
    pb = data["videos"][0]["playback"]
    assert pb["status"] == "needs_copy" and pb["codec_name"] == "MPEG-4 Part 2" and pb["url"] is None
    assert "original is not changed" in pb["message"]
    assert data["waiting_files"] == ["dropped_in_later.mp4"] and data["unsupported_files"] == ["notes.txt"]


def test_missing_original_is_reported_clearly(app):
    client, _, ws = app
    make_video(ws.video_dir / "gone.mp4", seconds=2)
    ws.run()
    vid = ws.videos()[0]["id"]
    (ws.video_dir / "gone.mp4").unlink()
    info = client.get(f"/api/videos/{vid}/playback").json
    assert info["status"] == "missing" and "no longer in the video folder" in info["message"]


def test_no_ffmpeg_gives_an_actionable_error_and_changes_nothing(app, monkeypatch):
    client, headers, ws = app
    make_video(ws.video_dir / "a.mp4", seconds=2)
    ws.run()
    vid = ws.videos()[0]["id"]
    monkeypatch.setattr(playback, "find_ffmpeg", lambda *_: None)
    assert client.get(f"/api/videos/{vid}/playback").json["ffmpeg_available"] is False
    r = client.post(f"/api/videos/{vid}/playback-copy", headers=headers)
    assert r.status_code == 503 and "FFmpeg was not found" in r.json["error"]
    assert not ws.db_path.with_name("playback").exists()


def test_playback_copy_needs_csrf(app):
    client, _, ws = app
    make_video(ws.video_dir / "a.mp4", seconds=2)
    ws.run()
    assert client.post(f"/api/videos/{ws.videos()[0]['id']}/playback-copy").status_code == 403


def test_playback_copy_is_h264_plays_seeks_and_leaves_original_untouched(app):
    ffmpeg_or_skip()
    client, headers, ws = app
    original = make_video(ws.video_dir / "cctv.mp4", seconds=4)
    ws.run()
    before = original.read_bytes()
    video = ws.videos()[0]
    r = client.post(f"/api/videos/{video['id']}/playback-copy", headers=headers)
    assert r.status_code == 200 and r.json["status"] == "copy_ready", r.json
    copy = ws.db_path.with_name("playback") / f"{video['sha256']}.mp4"
    assert playback.codec_of(copy) in playback.BROWSER_CODECS
    assert original.read_bytes() == before                                    # original never modified
    assert [p.name for p in ws.video_dir.iterdir()] == ["cctv.mp4"]           # nothing added to the library
    media = client.get(r.json["url"], headers={"Range": "bytes=100-199"})
    assert media.status_code == 206 and media.mimetype == "video/mp4" and len(media.data) == 100
    cap = cv2.VideoCapture(str(copy))                                          # seeking works in the copy
    cap.set(cv2.CAP_PROP_POS_MSEC, 2500)
    ok, _ = cap.read()
    assert ok and cap.get(cv2.CAP_PROP_POS_MSEC) >= 2000
    cap.release()
    assert client.get(f"/api/videos/{video['id']}/playback").json["status"] == "copy_ready"
    again = client.post(f"/api/videos/{video['id']}/playback-copy", headers=headers)  # idempotent
    assert again.json["status"] == "copy_ready"


def test_h264_original_plays_directly_without_a_copy(app, tmp_path):
    exe = ffmpeg_or_skip()
    client, headers, ws = app
    src = make_video(tmp_path / "src.mp4", seconds=2)
    playback.make_copy(src, ws.video_dir / "h264.mp4", exe)                     # an H.264 original
    ws.run()
    video = ws.videos()[0]
    info = client.get(f"/api/videos/{video['id']}/playback").json
    assert info["status"] == "playable" and info["url"] == f"/media/videos/{video['id']}"
    assert not ws.db_path.with_name("playback").exists()


def test_failed_conversion_reports_error_and_leaves_no_partial_file(app, monkeypatch, tmp_path):
    client, headers, ws = app
    make_video(ws.video_dir / "a.mp4", seconds=2)
    ws.run()
    vid = ws.videos()[0]["id"]
    fake = tmp_path / "ffmpeg.cmd"
    fake.write_text("@exit /b 1\n")
    monkeypatch.setattr(playback, "find_ffmpeg", lambda *_: str(fake))
    r = client.post(f"/api/videos/{vid}/playback-copy", headers=headers)
    assert r.status_code == 500 and "could not convert" in r.json["error"]
    folder = ws.db_path.with_name("playback")
    assert not folder.exists() or not list(folder.iterdir())


def test_playback_route_is_confined_to_its_folder(app):
    client, _, ws = app
    make_video(ws.video_dir / "a.mp4", seconds=2)
    ws.run()
    assert client.get("/media/playback/1").status_code == 404                  # no copy yet
    for bad in ("/media/playback/..%2f..%2ftanya.db", "/media/playback/../tanya.db"):
        assert client.get(bad).status_code == 404
