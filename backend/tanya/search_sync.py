"""Opt-in synchronisation of the SentrySearch index with TanyaCCTV's indexed videos.

SentrySearch identifies videos by absolute path, not content, so on its own it would keep stale
chunks for a changed file and old paths for renamed/deleted files. This module compares:

  * TanyaCCTV's database (videos with status 'done', their SHA-256), read-only,
  * the SentrySearch index (exact source_file strings, via the bridge's free `stats` command),
  * a small manifest (data/search_index_manifest.json) recording which SHA-256 was indexed per path,

and builds a plan. Nothing is removed or indexed unless apply_plan() is called (the script only
does so with --yes). Entries outside the video folder are never touched, and removals use the
bridge's exact-match `remove`, never `sentrysearch remove` (which matches substrings).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import sentry_client
from .config import SEARCHABLE_EXTENSIONS, SearchSettings, Settings

CHUNK_DURATION_SEC = 10
CHUNK_OVERLAP_SEC = 2
# Gemini Embedding 2 paid-tier video price, USD per frame (1 frame/s), from
# https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-16). Free tier: $0, but Google
# may use free-tier content to improve its products.
USD_PER_FRAME = 0.00079
MANIFEST_NAME = "search_index_manifest.json"


@dataclass
class PlannedVideo:
    rel_path: str
    source_file: str
    sha256: str
    duration_sec: float
    reason: str
    chunks: int = 0
    frames: int = 0


@dataclass
class PlannedRemoval:
    source_file: str
    reason: str


@dataclass
class SyncPlan:
    to_index: list[PlannedVideo] = field(default_factory=list)
    to_remove: list[PlannedRemoval] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    untouched_outside: int = 0          # indexed files outside the video folder (left alone)
    not_searchable: list[str] = field(default_factory=list)

    @property
    def frames(self) -> int:
        return sum(v.frames for v in self.to_index)

    @property
    def estimated_cost_usd(self) -> float:
        return self.frames * USD_PER_FRAME

    @property
    def is_empty(self) -> bool:
        return not self.to_index and not self.to_remove


def expected_chunk_spans(duration: float, chunk: int = CHUNK_DURATION_SEC, overlap: int = CHUNK_OVERLAP_SEC):
    """Same spans as sentrysearch.chunker.expected_chunk_spans (pinned d3efd6a)."""
    if duration <= chunk:
        return [(0.0, float(duration))]
    step = chunk - overlap
    spans, start = [], 0.0
    while start < duration:
        spans.append((start, min(start + chunk, duration)))
        start += step
        if start + overlap >= duration:
            break
    return spans


def estimate(duration_sec: float) -> tuple[int, int]:
    """(chunks, billed frames) for one video. Gemini bills 1 frame per second of each chunk."""
    spans = expected_chunk_spans(duration_sec)
    frames = sum(max(1, int(round(end - start))) for start, end in spans)
    return len(spans), frames


def _within(path: str, folder: Path) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    f = os.path.normcase(os.path.abspath(folder))
    try:
        return os.path.commonpath([p, f]) == f and p != f
    except ValueError:
        return False


# --------------------------------------------------------------------------- manifest


def manifest_path(settings: Settings) -> Path:
    return settings.db_path.parent / MANIFEST_NAME


def load_manifest(settings: Settings) -> dict[str, dict]:
    path = manifest_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_manifest(settings: Settings, manifest: dict[str, dict]) -> None:
    path = manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- planning


def build_plan(settings: Settings, indexed_source_files: list[str], manifest: dict[str, dict]) -> SyncPlan:
    """Compare TanyaCCTV's videos with the SentrySearch index. Pure planning: changes nothing."""
    plan = SyncPlan()
    video_dir = settings.video_dir.resolve()
    conn = sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT rel_path, sha256, duration_sec FROM videos WHERE status = 'done' "
                            "ORDER BY rel_path").fetchall()
    finally:
        conn.close()

    wanted: dict[str, sqlite3.Row] = {}
    for r in rows:
        if Path(r["rel_path"]).suffix.lower() not in SEARCHABLE_EXTENSIONS:
            plan.not_searchable.append(r["rel_path"])
            continue
        # SentrySearch stores os.path.abspath() of the path it was given; we always give this one.
        wanted[os.path.abspath(video_dir / Path(r["rel_path"]))] = r

    indexed_inside = set()
    for src in indexed_source_files:
        if not _within(src, video_dir):
            plan.untouched_outside += 1
            continue
        indexed_inside.add(src)
        row = wanted.get(src)
        recorded = manifest.get(src, {}).get("sha256")
        if row is None:
            plan.to_remove.append(PlannedRemoval(src, "no longer an indexed TanyaCCTV video (deleted, renamed or failed)"))
        elif recorded is None:
            plan.to_remove.append(PlannedRemoval(src, "indexed outside this tool; content cannot be verified"))
        elif recorded != row["sha256"]:
            plan.to_remove.append(PlannedRemoval(src, "video content changed since it was indexed"))
        else:
            plan.up_to_date.append(row["rel_path"])

    removing = {r.source_file for r in plan.to_remove}
    for src, row in wanted.items():
        if src in indexed_inside and src not in removing:
            continue
        reason = "re-index after removal" if src in removing else "not in search index yet"
        chunks, frames = estimate(float(row["duration_sec"] or 0))
        plan.to_index.append(PlannedVideo(row["rel_path"], src, row["sha256"],
                                          float(row["duration_sec"] or 0), reason, chunks, frames))
    return plan


def describe(plan: SyncPlan) -> str:
    lines = ["Search index sync plan", "======================"]
    lines.append(f"Videos to index: {len(plan.to_index)}")
    for v in plan.to_index:
        lines.append(f"  + {v.rel_path} ({v.duration_sec:.0f}s, {v.chunks} chunks, ~{v.frames} frames): {v.reason}")
    lines.append(f"Index entries to remove: {len(plan.to_remove)}")
    for r in plan.to_remove:
        lines.append(f"  - {r.source_file}: {r.reason}")
    lines.append(f"Already up to date: {len(plan.up_to_date)}")
    lines.append(f"Entries outside the video folder (never touched): {plan.untouched_outside}")
    if plan.not_searchable:
        lines.append("Not searchable (.mp4/.mov only): " + ", ".join(plan.not_searchable))
    lines.append(f"Estimated frames: {plan.frames}  |  estimated cost: ~US${plan.estimated_cost_usd:.2f} "
                 f"on the paid tier (${USD_PER_FRAME}/frame; free tier $0). Still-frame skipping may lower this.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- applying


def sentry_cli_command(search_settings: SearchSettings) -> list[str]:
    """The pinned `sentrysearch` executable that sits next to TANYA_SENTRY_PYTHON."""
    if search_settings.sentry_python is None:
        raise sentry_client.SearchNotConfiguredError("Set TANYA_SENTRY_PYTHON first")
    folder = search_settings.sentry_python.parent
    for name in ("sentrysearch.exe", "sentrysearch"):
        if (folder / name).is_file():
            return [str(folder / name)]
    raise sentry_client.SearchNotConfiguredError(f"sentrysearch executable not found next to {search_settings.sentry_python}")


def apply_plan(plan: SyncPlan, settings: Settings, search_settings: SearchSettings,
               cli_command: list[str], log: Callable[[str], None] = print,
               timeout_per_video_sec: float = 3600) -> bool:
    """Remove stale entries, then index planned videos. Returns True if everything succeeded."""
    if search_settings.sentry_db is not None:
        raise sentry_client.SearchError("sync supports only SentrySearch's default index; unset TANYA_SENTRY_DB")
    if plan.to_index and not os.environ.get("GEMINI_API_KEY"):
        raise sentry_client.SearchError("GEMINI_API_KEY is not set in this environment; nothing was changed")

    manifest = load_manifest(settings)
    video_dir = settings.video_dir.resolve()
    ok = True
    for r in plan.to_remove:
        removed = sentry_client.remove(search_settings, r.source_file, video_dir)
        manifest.pop(r.source_file, None)
        save_manifest(settings, manifest)
        log(f"[removed] {r.source_file} ({removed} chunks)")

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for v in plan.to_index:
        cmd = [*cli_command, "index", v.source_file,
               "--chunk-duration", str(CHUNK_DURATION_SEC), "--overlap", str(CHUNK_OVERLAP_SEC)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  env=env, timeout=timeout_per_video_sec)
        except (OSError, subprocess.TimeoutExpired) as e:
            ok = False
            log(sentry_client.redact(f"[failed]  {v.rel_path}: {e}"))
            continue
        if proc.returncode != 0:
            ok = False
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no details"]
            log(sentry_client.redact(f"[failed]  {v.rel_path}: exit {proc.returncode}: {tail[0][:300]}"))
            continue
        # `sentrysearch index` can exit 0 when chunks failed (they go to its dead-letter queue),
        # so confirm the file is really in the index before recording it (free, no API call).
        if v.source_file not in sentry_client.stats(search_settings)["source_files"]:
            ok = False
            log(f"[failed]  {v.rel_path}: no chunks were stored (check `sentrysearch dlq list`)")
            continue
        manifest[v.source_file] = {"rel_path": v.rel_path, "sha256": v.sha256,
                                   "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        save_manifest(settings, manifest)
        log(f"[indexed] {v.rel_path}")
    return ok
