"""Tests for the OpenCV frame extractor on its own."""

from __future__ import annotations

import cv2
import pytest

from tanya.frames import VideoError, extract_frames
from tests.conftest import make_video


def test_extracts_readable_jpegs(tmp_path):
    video = make_video(tmp_path / "v.avi", seconds=3.5, fps=8)
    result = extract_frames(video, tmp_path / "out", interval_sec=1.0)

    assert [f.timestamp_sec for f in result.frames] == [0.0, 1.0, 2.0, 3.0]
    assert result.duration_sec == pytest.approx(3.5)
    for f in result.frames:
        img = cv2.imread(str(tmp_path / "out" / f.filename))
        assert img is not None and img.shape[:2] == (48, 64)


def test_non_integer_fps_and_interval(tmp_path):
    video = make_video(tmp_path / "v.avi", seconds=6, fps=7)
    result = extract_frames(video, tmp_path / "out", interval_sec=1.5)
    ts = [f.timestamp_sec for f in result.frames]
    # first frame at or after each 1.5 s mark, at 7 fps
    assert ts == [0.0, pytest.approx(1.571, abs=1e-3), 3.0, pytest.approx(4.571, abs=1e-3)]


def test_short_video_gives_one_frame(tmp_path):
    video = make_video(tmp_path / "v.avi", seconds=0.5, fps=10)
    assert len(extract_frames(video, tmp_path / "out", 1.0).frames) == 1


def test_unreadable_file_raises(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x01garbage" * 200)
    with pytest.raises(VideoError):
        extract_frames(bad, tmp_path / "out", 1.0)
