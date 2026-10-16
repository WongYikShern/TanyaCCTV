"""Natural-language search over indexed videos: SentrySearch results -> TanyaCCTV videos.

1. Ask the search engine (via sentry_client) for the top-ranked 10 s chunks.
2. Map each chunk's absolute path to a video in our database (inside the video folder only).
3. Group overlapping/adjacent chunks of the same video into one time window (configurable).
4. Attach the extracted frame nearest the window's middle as a thumbnail.

Every hit has status "uncertain": these are similarity rankings for a person to review, never
confirmed incidents, and a low score does not prove that something is absent. The merge ratio
only decides which chunks are shown together; it never changes a status.

The TanyaCCTV database is opened read-only. Nothing here indexes, re-indexes or removes anything.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import sentry_client
from .config import SEARCHABLE_EXTENSIONS, SearchSettings, Settings

STATUS = "uncertain"


@dataclass
class Chunk:
    rank: int
    start_sec: float
    end_sec: float
    score: float
    score_above_median: float


@dataclass
class SearchHit:
    video_id: int
    rel_path: str
    filename: str
    start_sec: float
    end_sec: float
    best_score: float
    best_score_above_median: float
    chunks: list[Chunk]
    thumbnail: str | None = None  # relative to the frames directory
    thumbnail_timestamp_sec: float | None = None
    status: str = STATUS


@dataclass
class SearchResponse:
    query: str
    hits: list[SearchHit]
    warnings: list[str] = field(default_factory=list)
    note: str = ("Ranked similarity results for human review, not detections. Scores are ranking "
                 "signals, not calibrated probabilities. Results are unverified until a person "
                 "independently confirms them; a low score does not prove an incident is absent.")

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- merging


def merge_chunks(chunks: list[Chunk], ratio: float = 0.5, gap_sec: float = 0.0) -> list[list[Chunk]]:
    """Group one video's chunks into time windows.

    Starting from the best-scoring chunk, a group absorbs any chunk that overlaps it or lies
    within `gap_sec` of it, provided that chunk's score_above_median is at least `ratio` times
    the group's best. ratio=0 merges every touching chunk; ratio=1 merges only chunks scoring as
    high as the best. A group whose best chunk is at or below the median never absorbs others.
    Returns groups ordered by best score, each group ordered by time.
    """
    if not 0.0 <= ratio <= 1.0:
        raise ValueError("ratio must be between 0 and 1")
    if gap_sec < 0:
        raise ValueError("gap_sec must not be negative")
    remaining = sorted(chunks, key=lambda c: (-c.score, c.start_sec))
    groups: list[list[Chunk]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        if seed.score_above_median > 0:
            needed = ratio * seed.score_above_median
            changed = True
            while changed:
                changed = False
                lo = min(c.start_sec for c in group) - gap_sec
                hi = max(c.end_sec for c in group) + gap_sec
                for c in list(remaining):
                    if c.start_sec <= hi and c.end_sec >= lo and c.score_above_median >= needed:
                        group.append(c)
                        remaining.remove(c)
                        changed = True
        groups.append(sorted(group, key=lambda c: c.start_sec))
    return groups


# --------------------------------------------------------------------------- mapping


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise sentry_client.SearchError(f"No TanyaCCTV database at {db_path}. Run index_videos.py first.")
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _map_to_video(source_file: str, video_dir: Path, conn: sqlite3.Connection) -> tuple[sqlite3.Row | None, str]:
    """Return (video row or None, reason)."""
    path = Path(source_file)
    if not path.is_absolute():
        return None, "path is not absolute"
    root = video_dir.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return None, "outside the video folder"
    rel = resolved.relative_to(root).as_posix()
    row = conn.execute("SELECT * FROM videos WHERE rel_path = ? AND status = 'done'", (rel,)).fetchone()
    if row is None:
        return None, f"{rel} is not indexed by TanyaCCTV (run index_videos.py)"
    if not (root / rel).is_file():
        return None, f"{rel} is in the database but the video file is missing (run index_videos.py)"
    return row, ""


def _thumbnail(conn: sqlite3.Connection, frames_dir: Path, video_id: int, start: float, end: float):
    mid = (start + end) / 2
    row = conn.execute(
        "SELECT timestamp_sec, image_path FROM frames WHERE video_id = ? AND timestamp_sec BETWEEN ? AND ? "
        "ORDER BY ABS(timestamp_sec - ?) LIMIT 1",
        (video_id, start, end, mid),
    ).fetchone()
    if row is None or not (frames_dir / row["image_path"]).is_file():
        return None, None
    return row["image_path"], row["timestamp_sec"]


def build_hits(results: list[dict], settings: Settings, search_settings: SearchSettings,
               conn: sqlite3.Connection) -> tuple[list[SearchHit], list[str]]:
    """Turn bridge results into merged, thumbnailed hits plus human-readable warnings."""
    warnings: list[str] = []
    by_video: dict[int, tuple[sqlite3.Row, list[Chunk]]] = {}
    skipped: dict[str, str] = {}
    for r in results:
        row, reason = _map_to_video(r["source_file"], settings.video_dir, conn)
        if row is None:
            skipped.setdefault(r["filename"], reason)
            continue
        chunk = Chunk(r["rank"], float(r["start_sec"]), float(r["end_sec"]),
                      float(r["score"]), float(r["score_above_median"]))
        by_video.setdefault(row["id"], (row, []))[1].append(chunk)
    for name, reason in skipped.items():
        warnings.append(f"Ignored results from {name}: {reason}")

    hits: list[SearchHit] = []
    missing_thumbs = 0
    for row, chunks in by_video.values():
        for group in merge_chunks(chunks, search_settings.merge_ratio, search_settings.merge_gap_sec):
            best = max(group, key=lambda c: c.score)
            start, end = min(c.start_sec for c in group), max(c.end_sec for c in group)
            thumb, thumb_ts = _thumbnail(conn, settings.frames_dir, row["id"], start, end)
            missing_thumbs += thumb is None
            hits.append(SearchHit(
                video_id=row["id"], rel_path=row["rel_path"], filename=row["filename"],
                start_sec=start, end_sec=end, best_score=best.score,
                best_score_above_median=best.score_above_median, chunks=group,
                thumbnail=thumb, thumbnail_timestamp_sec=thumb_ts,
            ))
    hits.sort(key=lambda h: -h.best_score)
    if missing_thumbs:
        warnings.append(f"{missing_thumbs} result(s) have no thumbnail (frames missing; re-run index_videos.py)")
    return hits, warnings


def unsearchable_videos(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT rel_path FROM videos WHERE status = 'done' ORDER BY rel_path").fetchall()
    return [r["rel_path"] for r in rows if Path(r["rel_path"]).suffix.lower() not in SEARCHABLE_EXTENSIONS]


def stale_warnings(hits: list[SearchHit], settings: Settings, conn: sqlite3.Connection) -> list[str]:
    """Warn (never fix) when a hit's video may not match what SentrySearch indexed."""
    from .search_sync import load_manifest  # read-only

    manifest = load_manifest(settings)
    flagged = []
    for rel in sorted({h.rel_path for h in hits}):
        src = os.path.abspath(settings.video_dir.resolve() / Path(rel))
        sha = conn.execute("SELECT sha256 FROM videos WHERE rel_path = ?", (rel,)).fetchone()["sha256"]
        recorded = manifest.get(src, {}).get("sha256")
        if recorded != sha:
            flagged.append(rel)
    if not flagged:
        return []
    return ["Timestamps may be stale for " + ", ".join(flagged) + " (not indexed via sync, or content "
            "changed). Run sync_search_index.py to review."]


def search_videos(query: str, settings: Settings, search_settings: SearchSettings, n: int = 10) -> SearchResponse:
    """Run a natural-language search. Raises sentry_client.SearchError on engine/config problems."""
    conn = _connect_readonly(settings.db_path)
    try:
        data = sentry_client.search(search_settings, query, n)
        hits, warnings = build_hits(data["results"], settings, search_settings, conn)
        warnings += stale_warnings(hits, settings, conn)
        not_searchable = unsearchable_videos(conn)
    finally:
        conn.close()
    if not_searchable:
        warnings.append("Not searchable (SentrySearch indexes only .mp4/.mov): " + ", ".join(not_searchable))
    return SearchResponse(query=query, hits=hits, warnings=warnings)
