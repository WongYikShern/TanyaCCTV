"""SQLite schema and small helpers for video and frame metadata."""

from __future__ import annotations

import sqlite3
from pathlib import Path

# status values for videos.status
STATUS_PROCESSING = "processing"  # started but not finished (crash/interrupt leaves this behind)
STATUS_DONE = "done"
STATUS_FAILED = "failed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256              TEXT    NOT NULL UNIQUE,      -- identity of the video content
    filename            TEXT    NOT NULL,
    rel_path            TEXT    NOT NULL,             -- relative to the video directory
    size_bytes          INTEGER NOT NULL,
    duration_sec        REAL,
    fps                 REAL,
    width               INTEGER,
    height              INTEGER,
    frame_interval_sec  REAL    NOT NULL,
    frame_count         INTEGER NOT NULL DEFAULT 0,   -- number of extracted frames
    status              TEXT    NOT NULL CHECK (status IN ('processing', 'done', 'failed')),
    error               TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    indexed_at          TEXT
);

CREATE TABLE IF NOT EXISTS frames (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_number    INTEGER NOT NULL,                 -- index of the frame in the source video
    timestamp_sec   REAL    NOT NULL,                 -- position in the video, in seconds
    image_path      TEXT    NOT NULL,                 -- relative to the frames directory
    UNIQUE (video_id, frame_number)
);

CREATE INDEX IF NOT EXISTS idx_frames_video_ts ON frames (video_id, timestamp_sec);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database (creating it and its folder if needed) and ensure the schema exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_video_by_sha(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM videos WHERE sha256 = ?", (sha256,)).fetchone()


def all_videos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM videos ORDER BY id").fetchall()
