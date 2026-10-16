"""Repeatable video indexing: scan -> hash -> extract frames -> store metadata.

Safe to run again and again:
* Videos are identified by the SHA-256 of their content, so renames are detected.
* Videos already indexed with the same frame interval are skipped (unless force=True).
* Frames are written to a temporary folder and only published after extraction succeeds.
* A video left in 'processing' or 'failed' state is simply processed again next run.
* Index data (DB rows + extracted frames) for videos that were deleted or whose content
  changed is removed. Original video files are never modified or deleted.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .config import SUPPORTED_EXTENSIONS, ConfigError, Settings
from .frames import VideoError, extract_frames

TMP_DIR_NAME = ".tmp"
# Only directories that look like ours are ever deleted from the frames folder.
_FRAME_DIR_RE = re.compile(r"^[0-9a-f]{64}(\.old-[0-9a-f]+)?$")

# outcome statuses
INDEXED = "indexed"
SKIPPED = "skipped"
FAILED = "failed"
UNSUPPORTED = "unsupported"


@dataclass
class FileOutcome:
    rel_path: str
    status: str
    message: str = ""
    frame_count: int = 0


@dataclass
class IndexSummary:
    outcomes: list[FileOutcome] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # rel paths whose index data was removed

    def by_status(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def has_failures(self) -> bool:
        return bool(self.by_status(FAILED))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def scan_video_dir(video_dir: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (supported, unsupported, outside) files under video_dir, sorted.

    Hidden files (starting with '.') are ignored. 'outside' holds files (e.g. symlinks)
    that resolve to a location outside video_dir; those are never processed.
    """
    if not video_dir.is_dir():
        raise ConfigError(f"Video directory does not exist: {video_dir}")
    root = video_dir.resolve()
    supported, unsupported, outside = [], [], []
    for path in sorted(root.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(root):
            outside.append(path)
        elif path.suffix.lower() in SUPPORTED_EXTENSIONS:
            supported.append(path)
        else:
            unsupported.append(path)
    return supported, unsupported, outside


class Indexer:
    def __init__(
        self,
        settings: Settings,
        force: bool = False,
        log: Callable[[str], None] = print,
    ):
        self.settings = settings
        self.force = force
        self.log = log
        self.video_dir = settings.video_dir.resolve()
        self.frames_dir = settings.frames_dir.resolve()
        self.tmp_root = self.frames_dir / TMP_DIR_NAME

    # ------------------------------------------------------------------ public

    def run(self) -> IndexSummary:
        if self.frames_dir == self.video_dir or self.frames_dir.is_relative_to(self.video_dir):
            raise ConfigError("The frames directory must not be inside the video directory")

        supported, unsupported, outside = scan_video_dir(self.video_dir)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        # Leftovers from an interrupted earlier run are never valid; start clean.
        shutil.rmtree(self.tmp_root, ignore_errors=True)
        self.tmp_root.mkdir(parents=True, exist_ok=True)

        summary = IndexSummary()
        for path in unsupported:
            summary.outcomes.append(
                FileOutcome(self._rel(path), UNSUPPORTED, f"extension '{path.suffix}' not supported")
            )
        for path in outside:
            summary.outcomes.append(
                FileOutcome(self._rel(path), FAILED, "points outside the video directory; not processed")
            )

        conn = db.connect(self.settings.db_path)
        try:
            groups, protected = self._hash_files(supported, summary)
            for sha, paths in groups.items():
                self._index_group(conn, sha, paths, summary)
            self._remove_stale(conn, set(groups), protected, summary)
            self._remove_orphan_frame_dirs(conn)
        finally:
            conn.close()
            shutil.rmtree(self.tmp_root, ignore_errors=True)
        return summary

    # ----------------------------------------------------------------- helpers

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.video_dir).as_posix()
        except ValueError:
            return str(path)

    def _hash_files(
        self, paths: list[Path], summary: IndexSummary
    ) -> tuple[dict[str, list[Path]], set[str]]:
        """Group files by content hash. Returns (groups, rel paths that could not be read)."""
        groups: dict[str, list[Path]] = {}
        unreadable: set[str] = set()
        for path in paths:
            rel = self._rel(path)
            try:
                if path.stat().st_size == 0:
                    summary.outcomes.append(FileOutcome(rel, FAILED, "file is empty (0 bytes)"))
                    continue
                sha = sha256_file(path)
            except OSError as e:
                unreadable.add(rel)
                summary.outcomes.append(FileOutcome(rel, FAILED, f"could not read file: {e}"))
                continue
            groups.setdefault(sha, []).append(path)
        return groups, unreadable

    def _index_group(
        self, conn: sqlite3.Connection, sha: str, paths: list[Path], summary: IndexSummary
    ) -> None:
        """Index one unique piece of content (possibly present under several file names)."""
        row = db.get_video_by_sha(conn, sha)
        # Prefer the path already recorded, so duplicates don't make the record flip around.
        primary = paths[0]
        if row is not None:
            primary = next((p for p in paths if self._rel(p) == row["rel_path"]), paths[0])
        for dup in paths:
            if dup is not primary:
                summary.outcomes.append(
                    FileOutcome(self._rel(dup), SKIPPED, f"duplicate content of {self._rel(primary)}")
                )

        rel = self._rel(primary)
        reason = self._reindex_reason(row)
        if reason is None:
            if row["rel_path"] != rel:
                with conn:
                    conn.execute(
                        "UPDATE videos SET rel_path = ?, filename = ?, updated_at = datetime('now') "
                        "WHERE id = ?",
                        (rel, primary.name, row["id"]),
                    )
                msg = f"already indexed; renamed from {row['rel_path']}"
            else:
                msg = "already indexed"
            summary.outcomes.append(FileOutcome(rel, SKIPPED, msg, row["frame_count"]))
            self.log(f"[skip]    {rel}: {msg}")
            return

        self.log(f"[index]   {rel}: {reason}")
        summary.outcomes.append(self._process(conn, primary, rel, sha, row))

    def _reindex_reason(self, row: sqlite3.Row | None) -> str | None:
        """Why this video needs (re)processing, or None if it can be skipped."""
        if row is None:
            return "new video"
        if self.force:
            return "forced re-index"
        if row["status"] == db.STATUS_FAILED:
            return "retrying previously failed video"
        if row["status"] == db.STATUS_PROCESSING:
            return "previous run was interrupted"
        if abs(row["frame_interval_sec"] - self.settings.frame_interval_sec) > 1e-9:
            return (
                f"frame interval changed ({row['frame_interval_sec']}s -> "
                f"{self.settings.frame_interval_sec}s)"
            )
        frame_dir = self.frames_dir / row["sha256"]
        on_disk = len(list(frame_dir.glob("*.jpg"))) if frame_dir.is_dir() else 0
        if on_disk != row["frame_count"]:
            return "extracted frames missing on disk"
        return None

    def _process(
        self,
        conn: sqlite3.Connection,
        path: Path,
        rel: str,
        sha: str,
        row: sqlite3.Row | None,
    ) -> FileOutcome:
        interval = self.settings.frame_interval_sec
        try:
            size = path.stat().st_size
        except OSError as e:  # e.g. deleted while the run was in progress
            self.log(f"[failed]  {rel}: {e}")
            return FileOutcome(rel, FAILED, f"could not read file: {e}")

        # 1. Record that we started. If we crash after this, status stays 'processing'
        #    and the next run knows to redo this video.
        with conn:
            if row is None:
                cur = conn.execute(
                    "INSERT INTO videos (sha256, filename, rel_path, size_bytes, "
                    "frame_interval_sec, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (sha, path.name, rel, size, interval, db.STATUS_PROCESSING),
                )
                video_id = cur.lastrowid
            else:
                video_id = row["id"]
                conn.execute(
                    "UPDATE videos SET filename = ?, rel_path = ?, size_bytes = ?, "
                    "frame_interval_sec = ?, status = ?, error = NULL, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (path.name, rel, size, interval, db.STATUS_PROCESSING, video_id),
                )

        tmp_dir = Path(tempfile.mkdtemp(prefix=sha[:12] + "-", dir=self.tmp_root))
        final_dir = self.frames_dir / sha
        old_dir: Path | None = None
        try:
            # 2. Extract into a private temp folder.
            result = extract_frames(path, tmp_dir, interval, self.settings.jpeg_quality)

            # 3. Publish: move the old frames aside, move the new frames into place.
            if final_dir.exists():
                old_dir = final_dir.with_name(f"{sha}.old-{uuid.uuid4().hex[:8]}")
                final_dir.rename(old_dir)
            tmp_dir.rename(final_dir)

            # 4. Replace frame rows and mark done in a single transaction.
            with conn:
                conn.execute("DELETE FROM frames WHERE video_id = ?", (video_id,))
                conn.executemany(
                    "INSERT INTO frames (video_id, frame_number, timestamp_sec, image_path) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (video_id, f.frame_number, f.timestamp_sec, f"{sha}/{f.filename}")
                        for f in result.frames
                    ],
                )
                conn.execute(
                    "UPDATE videos SET status = ?, error = NULL, duration_sec = ?, fps = ?, "
                    "width = ?, height = ?, frame_count = ?, indexed_at = datetime('now'), "
                    "updated_at = datetime('now') WHERE id = ?",
                    (
                        db.STATUS_DONE,
                        result.duration_sec,
                        result.fps,
                        result.width,
                        result.height,
                        len(result.frames),
                        video_id,
                    ),
                )
        except (VideoError, OSError, sqlite3.Error) as e:
            self._mark_failed(conn, video_id, sha, str(e))
            self.log(f"[failed]  {rel}: {e}")
            return FileOutcome(rel, FAILED, str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if old_dir is not None:
                shutil.rmtree(old_dir, ignore_errors=True)

        n = len(result.frames)
        msg = f"{n} frames, {result.duration_sec:.1f}s, every {interval}s"
        self.log(f"[done]    {rel}: {msg}")
        return FileOutcome(rel, INDEXED, msg, n)

    def _mark_failed(self, conn: sqlite3.Connection, video_id: int, sha: str, error: str) -> None:
        """Mark a video failed and drop any frames it had, so nothing half-done remains."""
        shutil.rmtree(self.frames_dir / sha, ignore_errors=True)
        with conn:
            conn.execute("DELETE FROM frames WHERE video_id = ?", (video_id,))
            conn.execute(
                "UPDATE videos SET status = ?, error = ?, frame_count = 0, "
                "updated_at = datetime('now') WHERE id = ?",
                (db.STATUS_FAILED, error[:1000], video_id),
            )

    def _remove_stale(
        self,
        conn: sqlite3.Connection,
        present_shas: set[str],
        protected_paths: set[str],
        summary: IndexSummary,
    ) -> None:
        """Drop index data for content that is no longer in the video directory.

        Covers deleted videos and videos whose content was modified (new hash).
        Records for files that exist but could not be read this run are kept.
        """
        current_paths = {o.rel_path for o in summary.outcomes}
        for row in db.all_videos(conn):
            if row["sha256"] in present_shas or row["rel_path"] in protected_paths:
                continue
            reason = "content changed" if row["rel_path"] in current_paths else "file no longer present"
            with conn:
                conn.execute("DELETE FROM videos WHERE id = ?", (row["id"],))  # frames cascade
            shutil.rmtree(self.frames_dir / row["sha256"], ignore_errors=True)
            summary.removed.append(row["rel_path"])
            self.log(f"[removed] {row['rel_path']}: {reason}; old index data deleted (video files untouched)")

    def _remove_orphan_frame_dirs(self, conn: sqlite3.Connection) -> None:
        """Delete frame folders that no finished video in the database refers to."""
        keep = {
            r["sha256"]
            for r in conn.execute("SELECT sha256 FROM videos WHERE status = ?", (db.STATUS_DONE,))
        }
        for entry in self.frames_dir.iterdir():
            if entry.is_dir() and _FRAME_DIR_RE.match(entry.name) and entry.name not in keep:
                shutil.rmtree(entry, ignore_errors=True)
