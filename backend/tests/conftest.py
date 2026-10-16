"""Shared fixtures: temporary data folders and synthetic test videos made with OpenCV."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from tanya import db
from tanya.config import Settings
from tanya.indexer import Indexer


def make_video(path: Path, seconds: float = 5.0, fps: int = 10, seed: int = 0, size=(64, 48)) -> Path:
    """Write a small synthetic video. Different seeds give different content (and hashes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = "mp4v" if path.suffix.lower() == ".mp4" else "MJPG"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, size)
    assert writer.isOpened(), f"OpenCV could not create test video {path}"
    rng = np.random.default_rng(seed)
    w, h = size
    for i in range(int(seconds * fps)):
        frame = np.full((h, w, 3), (seed * 37) % 255, np.uint8)
        x = (i * 3) % (w - 8)
        frame[10:18, x : x + 8] = rng.integers(0, 255, 3, dtype=np.uint8)  # a moving square
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture
def workspace(tmp_path: Path):
    """Isolated video/frames/db locations for one test."""

    class Workspace:
        video_dir = tmp_path / "videos"
        frames_dir = tmp_path / "frames"
        db_path = tmp_path / "tanya.db"

        def settings(self, interval: float = 1.0) -> Settings:
            return Settings(self.video_dir, self.frames_dir, self.db_path, interval)

        def run(self, interval: float = 1.0, force: bool = False):
            return Indexer(self.settings(interval), force=force, log=lambda _msg: None).run()

        def rows(self, sql: str, params=()):
            conn = db.connect(self.db_path)
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()

        def videos(self):
            return self.rows("SELECT * FROM videos ORDER BY id")

        def frames(self, video_id: int):
            return self.rows(
                "SELECT * FROM frames WHERE video_id = ? ORDER BY timestamp_sec", (video_id,)
            )

        def frame_dirs(self):
            return sorted(p.name for p in self.frames_dir.iterdir() if p.is_dir())

    ws = Workspace()
    ws.video_dir.mkdir()
    return ws
