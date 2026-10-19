"""Investigations: saved queries, evidence clips, human reviews and an append-only audit log.

Stored in their own SQLite file (investigations.db next to the index); the video index and the
search-feedback store are never modified here.

Principles:
* Evidence points at the video's SHA-256 content hash (plus the file name/path and time window
  recorded when it was added). Stored references are never rewritten; availability is resolved
  against the current library when read (see resolve_sources).
* Nothing is silently changed: evidence removal is a soft removal, and every meaningful change
  is appended to the audit log, including a review's previous value.
* Retrieval scores are stored only as context ("how it was found"), never as evidence.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DECISIONS = ("correct", "wrong", "unsure")
MODES = ("ranked", "visual")
# Evidence can also be a moment an operator chose by hand in the video player (not a search result),
# or a window from a direct footage scan (sampled images checked in order; no similarity ranking).
EVIDENCE_MODES = MODES + ("manual", "scan")
VISUAL_VERDICTS = ("supported", "not_supported", "unclear")
STATUSES = ("open", "closed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_queries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id  INTEGER NOT NULL REFERENCES investigations(id),
    query             TEXT NOT NULL,
    search_mode       TEXT NOT NULL CHECK (search_mode IN ('ranked', 'visual')),
    settings_json     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    last_run_at       TEXT,
    last_result_count INTEGER,
    removed_at        TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id    INTEGER NOT NULL REFERENCES investigations(id),
    video_sha256        TEXT NOT NULL,
    video_filename      TEXT NOT NULL,
    video_rel_path      TEXT NOT NULL,
    video_duration_sec  REAL,
    start_sec           REAL NOT NULL,
    end_sec             REAL NOT NULL,
    query               TEXT NOT NULL,
    search_mode         TEXT NOT NULL,
    rank                INTEGER,
    best_score          REAL,
    score_above_median  REAL,
    visual_verdict      TEXT,
    visual_reason       TEXT,
    thumbnail           TEXT,
    added_at            TEXT NOT NULL,
    decision            TEXT CHECK (decision IS NULL OR decision IN ('correct', 'wrong', 'unsure')),
    note                TEXT NOT NULL DEFAULT '',
    reviewed_at         TEXT,
    removed_at          TEXT,
    removal_reason      TEXT
);
CREATE TABLE IF NOT EXISTS recording_clocks (
    investigation_id  INTEGER NOT NULL REFERENCES investigations(id),
    video_sha256      TEXT NOT NULL,
    recorded_start    TEXT NOT NULL,
    PRIMARY KEY (investigation_id, video_sha256)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id  INTEGER NOT NULL REFERENCES investigations(id),
    at                TEXT NOT NULL,
    action            TEXT NOT NULL,
    detail_json       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_inv ON evidence (investigation_id);
CREATE INDEX IF NOT EXISTS idx_audit_inv ON audit_log (investigation_id, id);
-- History cannot be rewritten, even by a bug: the audit log is append-only and evidence rows are
-- never deleted (removal is the removed_at marker).
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence
    BEGIN SELECT RAISE(ABORT, 'evidence is never deleted; it is marked as removed'); END;
CREATE TRIGGER IF NOT EXISTS evidence_reference_fixed BEFORE UPDATE OF video_sha256, video_filename,
    video_rel_path, start_sec, end_sec, query, search_mode, added_at ON evidence
    BEGIN SELECT RAISE(ABORT, 'evidence references cannot be changed'); END;
"""


class InvestigationError(ValueError):
    """Invalid request (HTTP 400)."""


class NotFound(InvestigationError):
    """Unknown investigation, query or evidence item (HTTP 404)."""


class StoreUnavailable(RuntimeError):
    """The investigations file cannot be read (e.g. corrupted). It is never modified or deleted."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, name: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        raise InvestigationError(f"{name} must be {low}-{high} characters")
    return value.strip()


def _number(value, name: str):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise InvestigationError(f"{name} must be a finite number")
    return float(value)


def _optional_number(value, name: str):
    return None if value is None else _number(value, name)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    # ------------------------------------------------------------------ plumbing

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(self.path, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA)
            return conn
        except sqlite3.DatabaseError as e:
            raise StoreUnavailable(
                f"The investigations file {self.path.name} cannot be read ({e}). It was left unchanged; "
                "restore it from a backup or move it aside to start a new one.") from None

    def _run(self, fn):
        conn = self._connect()
        try:
            with conn:
                return fn(conn)
        except sqlite3.DatabaseError as e:
            raise StoreUnavailable(f"Investigation data could not be read or saved ({e}). Nothing was changed.") from None
        finally:
            conn.close()

    @staticmethod
    def _audit(conn, inv_id: int, action: str, **detail) -> None:
        conn.execute("INSERT INTO audit_log (investigation_id, at, action, detail_json) VALUES (?,?,?,?)",
                     (inv_id, now(), action, json.dumps(detail, sort_keys=True)))

    @staticmethod
    def _investigation(conn, inv_id) -> sqlite3.Row:
        if type(inv_id) is not int:
            raise NotFound("Unknown investigation.")
        row = conn.execute("SELECT * FROM investigations WHERE id=?", (inv_id,)).fetchone()
        if row is None:
            raise NotFound("Unknown investigation.")
        return row

    def _open_investigation(self, conn, inv_id) -> sqlite3.Row:
        row = self._investigation(conn, inv_id)
        if row["status"] != "open":
            raise InvestigationError("This investigation is closed. Reopen it to make changes.")
        return row

    @staticmethod
    def _touch(conn, inv_id) -> None:
        conn.execute("UPDATE investigations SET updated_at=? WHERE id=?", (now(), inv_id))

    # ------------------------------------------------------------------ investigations

    def create(self, title, description="") -> dict:
        title = _text(title, "Title", 1, 200)
        description = "" if description in (None, "") else _text(description, "Description", 1, 2000)

        def fn(conn):
            t = now()
            cur = conn.execute("INSERT INTO investigations (title, description, created_at, updated_at) "
                               "VALUES (?,?,?,?)", (title, description, t, t))
            self._audit(conn, cur.lastrowid, "created", title=title)
            return cur.lastrowid
        return self.get(self._run(fn))

    def list(self) -> list[dict]:
        def fn(conn):
            rows = conn.execute("""SELECT i.*,
                   (SELECT COUNT(*) FROM evidence e WHERE e.investigation_id=i.id AND e.removed_at IS NULL) AS evidence_count,
                   (SELECT COUNT(*) FROM evidence e WHERE e.investigation_id=i.id AND e.removed_at IS NULL
                        AND e.decision IS NULL) AS unreviewed_count
                   FROM investigations i ORDER BY i.updated_at DESC, i.id DESC""").fetchall()
            return [dict(r) for r in rows]
        return self._run(fn)

    def get(self, inv_id) -> dict:
        def fn(conn):
            inv = dict(self._investigation(conn, inv_id))
            inv["queries"] = [dict(r, settings=json.loads(r["settings_json"])) for r in conn.execute(
                "SELECT * FROM saved_queries WHERE investigation_id=? AND removed_at IS NULL ORDER BY id", (inv_id,))]
            for q in inv["queries"]:
                q.pop("settings_json")
            inv["evidence"] = [dict(r) for r in conn.execute(
                "SELECT * FROM evidence WHERE investigation_id=? AND removed_at IS NULL ORDER BY id", (inv_id,))]
            inv["removed_evidence"] = [dict(r) for r in conn.execute(
                "SELECT * FROM evidence WHERE investigation_id=? AND removed_at IS NOT NULL ORDER BY id", (inv_id,))]
            inv["recording_clocks"] = {r["video_sha256"]: r["recorded_start"] for r in conn.execute(
                "SELECT * FROM recording_clocks WHERE investigation_id=?", (inv_id,))}
            return inv
        return self._run(fn)

    def update(self, inv_id, title=None, description=None) -> dict:
        def fn(conn):
            row = self._open_investigation(conn, inv_id)
            changes = {}
            if title is not None:
                new = _text(title, "Title", 1, 200)
                if new != row["title"]:
                    changes["title"] = {"from": row["title"], "to": new}
                    conn.execute("UPDATE investigations SET title=? WHERE id=?", (new, inv_id))
            if description is not None:
                new = "" if description == "" else _text(description, "Description", 1, 2000)
                if new != row["description"]:
                    changes["description"] = {"from": row["description"], "to": new}
                    conn.execute("UPDATE investigations SET description=? WHERE id=?", (new, inv_id))
            if changes:
                self._touch(conn, inv_id)
                self._audit(conn, inv_id, "details_changed", **changes)
        self._run(fn)
        return self.get(inv_id)

    def set_status(self, inv_id, status) -> dict:
        if status not in STATUSES:
            raise InvestigationError("Status must be open or closed.")

        def fn(conn):
            row = self._investigation(conn, inv_id)
            if row["status"] != status:
                conn.execute("UPDATE investigations SET status=? WHERE id=?", (status, inv_id))
                self._touch(conn, inv_id)
                self._audit(conn, inv_id, "closed" if status == "closed" else "reopened")
        self._run(fn)
        return self.get(inv_id)

    # ------------------------------------------------------------------ saved queries

    def save_query(self, inv_id, query, search_mode, settings: dict, result_count=None) -> dict:
        query = _text(query, "Query", 1, 500)
        if search_mode not in MODES:
            raise InvestigationError("Search mode must be ranked or visual.")
        if not isinstance(settings, dict):
            raise InvestigationError("Search settings must be an object.")
        settings_json = json.dumps(settings, sort_keys=True)
        if len(settings_json) > 2000:
            raise InvestigationError("Search settings are too large.")
        if result_count is not None and (type(result_count) is not int or result_count < 0):
            raise InvestigationError("Result count must be a non-negative integer.")

        def fn(conn):
            self._open_investigation(conn, inv_id)
            t = now()
            row = conn.execute("SELECT id FROM saved_queries WHERE investigation_id=? AND query=? AND search_mode=? "
                               "AND settings_json=? AND removed_at IS NULL", (inv_id, query, search_mode,
                                                                            settings_json)).fetchone()
            if row:
                conn.execute("UPDATE saved_queries SET last_run_at=?, last_result_count=? WHERE id=?",
                             (t, result_count, row["id"]))
                self._audit(conn, inv_id, "query_run", query_id=row["id"], query=query, results=result_count)
                qid = row["id"]
            else:
                qid = conn.execute("INSERT INTO saved_queries (investigation_id, query, search_mode, settings_json, "
                                   "created_at, last_run_at, last_result_count) VALUES (?,?,?,?,?,?,?)",
                                   (inv_id, query, search_mode, settings_json, t, t, result_count)).lastrowid
                self._audit(conn, inv_id, "query_saved", query_id=qid, query=query, search_mode=search_mode,
                            settings=settings, results=result_count)
            self._touch(conn, inv_id)
            return qid
        qid = self._run(fn)
        return next(q for q in self.get(inv_id)["queries"] if q["id"] == qid)

    def remove_query(self, inv_id, query_id) -> dict:
        def fn(conn):
            self._open_investigation(conn, inv_id)
            row = conn.execute("SELECT * FROM saved_queries WHERE id=? AND investigation_id=? AND removed_at IS NULL",
                               (query_id, inv_id)).fetchone() if type(query_id) is int else None
            if row is None:
                raise NotFound("Unknown saved query.")
            conn.execute("UPDATE saved_queries SET removed_at=? WHERE id=?", (now(), query_id))
            self._touch(conn, inv_id)
            self._audit(conn, inv_id, "query_removed", query_id=query_id, query=row["query"])
        self._run(fn)
        return self.get(inv_id)

    # ------------------------------------------------------------------ evidence

    def add_evidence(self, inv_id, item: dict) -> dict:
        """`item` must already contain server-verified video fields (sha256, filename, rel_path,
        duration); retrieval context (query, mode, rank, scores, verdict) is validated here."""
        start, end = _number(item.get("start_sec"), "start_sec"), _number(item.get("end_sec"), "end_sec")
        duration = _optional_number(item.get("video_duration_sec"), "video_duration_sec")
        if not 0 <= start < end or (duration is not None and end > duration + 1e-6):
            raise InvestigationError("The clip must lie inside the recording.")
        query = _text(item.get("query"), "Query", 1, 500)
        mode = item.get("search_mode")
        if mode not in EVIDENCE_MODES:
            raise InvestigationError("Search mode must be ranked, visual, scan or manual.")
        if mode == "scan" and (item.get("rank") is not None or item.get("best_score") is not None):
            raise InvestigationError("A footage-scan clip has no similarity rank or score.")
        rank = item.get("rank")
        if rank is not None and (type(rank) is not int or rank < 1):
            raise InvestigationError("rank must be a positive integer.")
        verdict = item.get("visual_verdict")
        if verdict is not None and verdict not in VISUAL_VERDICTS:
            raise InvestigationError("Unknown visual verdict.")
        reason = item.get("visual_reason")
        if reason is not None:
            reason = _text(reason, "Visual reason", 0, 1000)
        sha = item.get("video_sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            raise InvestigationError("A source video reference is required.")
        values = dict(video_sha256=sha, video_filename=_text(item.get("video_filename"), "File name", 1, 500),
                      video_rel_path=_text(item.get("video_rel_path"), "Path", 1, 1000),
                      video_duration_sec=duration, start_sec=start, end_sec=end, query=query, search_mode=mode,
                      rank=rank, best_score=_optional_number(item.get("best_score"), "best_score"),
                      score_above_median=_optional_number(item.get("score_above_median"), "score_above_median"),
                      visual_verdict=verdict, visual_reason=reason, thumbnail=item.get("thumbnail"))
        if values["thumbnail"] is not None and not isinstance(values["thumbnail"], str):
            raise InvestigationError("Invalid thumbnail reference.")

        def fn(conn):
            self._open_investigation(conn, inv_id)
            dup = conn.execute("SELECT id FROM evidence WHERE investigation_id=? AND video_sha256=? AND "
                               "ROUND(start_sec,3)=ROUND(?,3) AND ROUND(end_sec,3)=ROUND(?,3) AND removed_at IS NULL",
                               (inv_id, sha, start, end)).fetchone()
            if dup:
                raise InvestigationError("This clip is already in the investigation.")
            cols = ", ".join(values) + ", investigation_id, added_at"
            marks = ", ".join("?" * (len(values) + 2))
            ev_id = conn.execute(f"INSERT INTO evidence ({cols}) VALUES ({marks})",
                                 (*values.values(), inv_id, now())).lastrowid
            self._touch(conn, inv_id)
            self._audit(conn, inv_id, "evidence_added", evidence_id=ev_id, video=values["video_filename"],
                        video_sha256=sha, start_sec=start, end_sec=end, query=query, search_mode=mode)
            return ev_id
        ev_id = self._run(fn)
        return next(e for e in self.get(inv_id)["evidence"] if e["id"] == ev_id)

    def _evidence(self, conn, inv_id, ev_id) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM evidence WHERE id=? AND investigation_id=? AND removed_at IS NULL",
                           (ev_id, inv_id)).fetchone() if type(ev_id) is int else None
        if row is None:
            raise NotFound("Unknown evidence item.")
        return row

    def remove_evidence(self, inv_id, ev_id, reason="") -> dict:
        reason = "" if reason in (None, "") else _text(reason, "Reason", 1, 500)

        def fn(conn):
            self._open_investigation(conn, inv_id)
            row = self._evidence(conn, inv_id, ev_id)
            conn.execute("UPDATE evidence SET removed_at=?, removal_reason=? WHERE id=?", (now(), reason, ev_id))
            self._touch(conn, inv_id)
            self._audit(conn, inv_id, "evidence_removed", evidence_id=ev_id, video=row["video_filename"],
                        start_sec=row["start_sec"], end_sec=row["end_sec"], decision=row["decision"], reason=reason)
        self._run(fn)
        return self.get(inv_id)

    def review_evidence(self, inv_id, ev_id, decision=None, note=None) -> dict:
        """Set the human decision and/or note. Previous values are kept in the audit log."""
        if decision is not None and decision not in DECISIONS:
            raise InvestigationError("Decision must be correct, wrong or unsure.")
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise InvestigationError("Notes must be text of at most 2000 characters.")
        if decision is None and note is None:
            raise InvestigationError("Nothing to change.")

        def fn(conn):
            self._open_investigation(conn, inv_id)
            row = self._evidence(conn, inv_id, ev_id)
            t = now()
            if decision is not None and decision != row["decision"]:
                conn.execute("UPDATE evidence SET decision=?, reviewed_at=? WHERE id=?", (decision, t, ev_id))
                self._audit(conn, inv_id, "decision_changed" if row["decision"] else "decision_recorded",
                            evidence_id=ev_id, **{"from": row["decision"], "to": decision})
            if note is not None and note.strip() != row["note"]:
                conn.execute("UPDATE evidence SET note=? WHERE id=?", (note.strip(), ev_id))
                self._audit(conn, inv_id, "note_changed", evidence_id=ev_id, **{"from": row["note"], "to": note.strip()})
            self._touch(conn, inv_id)
            return dict(conn.execute("SELECT * FROM evidence WHERE id=?", (ev_id,)).fetchone())
        return self._run(fn)

    # ------------------------------------------------------------------ recording clocks

    def set_recording_start(self, inv_id, video_sha256, recorded_start) -> dict:
        """Operator-entered camera start time for one recording, used only to order the timeline."""
        if not isinstance(video_sha256, str) or len(video_sha256) != 64:
            raise InvestigationError("Unknown recording.")
        if recorded_start not in (None, ""):
            try:
                parsed = datetime.fromisoformat(recorded_start)
            except (TypeError, ValueError):
                raise InvestigationError("Use a date and time such as 2026-10-19T14:30:00.") from None
            if parsed.tzinfo is not None:
                # Camera clocks are local time; mixing zones would make the order ambiguous.
                raise InvestigationError("Enter the camera's local time without a time zone.")
            recorded_start = parsed.replace(microsecond=0).isoformat()

        def fn(conn):
            self._open_investigation(conn, inv_id)
            old = conn.execute("SELECT recorded_start FROM recording_clocks WHERE investigation_id=? AND video_sha256=?",
                               (inv_id, video_sha256)).fetchone()
            old_value = old["recorded_start"] if old else None
            if recorded_start in (None, ""):
                conn.execute("DELETE FROM recording_clocks WHERE investigation_id=? AND video_sha256=?",
                             (inv_id, video_sha256))
                new_value = None
            else:
                conn.execute("INSERT INTO recording_clocks VALUES (?,?,?) ON CONFLICT(investigation_id, video_sha256) "
                             "DO UPDATE SET recorded_start=excluded.recorded_start", (inv_id, video_sha256, recorded_start))
                new_value = recorded_start
            if old_value != new_value:
                self._touch(conn, inv_id)
                self._audit(conn, inv_id, "recording_start_set", video_sha256=video_sha256,
                            **{"from": old_value, "to": new_value})
        self._run(fn)
        return self.get(inv_id)

    # ------------------------------------------------------------------ history

    def audit(self, inv_id) -> list[dict]:
        def fn(conn):
            self._investigation(conn, inv_id)
            return [dict(r, detail=json.loads(r["detail_json"])) for r in conn.execute(
                "SELECT id, at, action, detail_json FROM audit_log WHERE investigation_id=? ORDER BY id", (inv_id,))]
        rows = self._run(fn)
        for r in rows:
            r.pop("detail_json")
        return rows

    def record_export(self, inv_id, fmt: str) -> None:
        self._run(lambda conn: (self._investigation(conn, inv_id), self._audit(conn, inv_id, "report_exported", format=fmt)))


# ---------------------------------------------------------------------- reading helpers


def verify_sources(items: list[dict], video_dir: Path, hasher) -> list[dict]:
    """Re-hash each available source file and compare it with the evidence reference.

    Used at report export. "verified" = the file's current content has the referenced SHA-256;
    a mismatch marks the item "changed" (the file was modified after it was referenced).
    Each file is hashed once, however many clips refer to it. Missing sources stay missing.
    """
    root, cache, out = video_dir.resolve(), {}, []
    for e in items:
        e = dict(e)
        if e["source_status"] == "missing" or not e.get("current_rel_path"):
            e["content_verified"] = False
        else:
            path = (root / e["current_rel_path"]).resolve()
            if path not in cache:
                try:
                    cache[path] = hasher(path)
                except OSError:
                    cache[path] = None
            e["content_verified"] = cache[path] == e["video_sha256"]
            if not e["content_verified"]:
                e["source_status"] = "changed"
        out.append(e)
    return out


def resolve_sources(evidence: list[dict], library: dict[str, dict], video_dir: Path) -> list[dict]:
    """Annotate evidence with where its source recording is now. Never rewrites stored references.

    library: {sha256: current video row}. source_status is "available", "renamed" (same content,
    new name), "missing" (content no longer in the library, or its file is gone) or "changed" (the
    file's size no longer matches the indexed size: a cheap hint; exports re-hash every source)."""
    out = []
    root = video_dir.resolve()
    for e in evidence:
        e = dict(e)
        current = library.get(e["video_sha256"])
        path = (root / current["rel_path"]).resolve() if current else None
        if current is None or not path.is_relative_to(root) or not path.is_file():
            e.update(source_status="missing", current_video_id=None, current_filename=None, current_rel_path=None)
        else:
            status = "available" if current["rel_path"] == e["video_rel_path"] else "renamed"
            if current.get("size_bytes") is not None and path.stat().st_size != current["size_bytes"]:
                status = "changed"
            e.update(source_status=status,
                     current_video_id=current["id"], current_filename=current["filename"],
                     current_rel_path=current["rel_path"])
        out.append(e)
    return out


def timeline(evidence: list[dict], clocks: dict[str, str]) -> tuple[list[dict], str]:
    """Order evidence chronologically. Returns (items, basis).

    With an operator-entered start time for a recording, clip times become absolute and clips
    from different cameras interleave. Recordings without one are grouped by file, in order of
    position within the recording, after the absolutely-timed clips.
    """
    timed, untimed = [], []
    for e in evidence:
        e = dict(e)
        start = clocks.get(e["video_sha256"])
        if start:
            base = datetime.fromisoformat(start)
            e["absolute_start"] = (base + timedelta(seconds=e["start_sec"])).isoformat(timespec="milliseconds")
            e["absolute_end"] = (base + timedelta(seconds=e["end_sec"])).isoformat(timespec="milliseconds")
            timed.append((base + timedelta(seconds=e["start_sec"]), e))
        else:
            e["absolute_start"] = e["absolute_end"] = None
            untimed.append(e)
    timed = [e for _, e in sorted(timed, key=lambda pair: (pair[0], pair[1]["id"]))]
    untimed.sort(key=lambda e: (e["video_filename"].lower(), e["video_sha256"], e["start_sec"], e["id"]))
    if not evidence:
        basis = "empty"
    elif not untimed:
        basis = "absolute"
    elif not timed:
        basis = "within_recording"
    else:
        basis = "mixed"
    return timed + untimed, basis
