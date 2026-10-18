"""Local human search reviews, kept separately from the video index."""
import csv
from datetime import datetime, timezone
import io
import sqlite3

COLUMNS = ('reviewed_at', 'query', 'video_id', 'filename', 'start_sec', 'end_sec',
           'search_mode', 'assessment')


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS feedback (
        reviewed_at TEXT NOT NULL, query TEXT NOT NULL, video_id INTEGER NOT NULL,
        filename TEXT NOT NULL, start_sec REAL NOT NULL, end_sec REAL NOT NULL,
        search_mode TEXT NOT NULL, assessment TEXT NOT NULL,
        UNIQUE(query, video_id, start_sec, end_sec, search_mode))''')
    return conn


def save(path, review):
    conn = connect(path)
    try:
        conn.execute('''INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(query,video_id,start_sec,end_sec,search_mode) DO UPDATE SET
            reviewed_at=excluded.reviewed_at, assessment=excluded.assessment''',
            (datetime.now(timezone.utc).isoformat(), *(review[k] for k in COLUMNS[1:])))
        conn.commit()
    finally:
        conn.close()


def lookup(path, query, search_mode, windows):
    """Earlier human reviews for (query, mode) and the given (video_id, start, end) windows.

    Read-only: never creates the database. Returns {(video_id, start, end): {assessment,
    reviewed_at}}. Times are compared to the millisecond, as sent back by the dashboard.
    """
    if not path.exists() or not windows:
        return {}
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        found = {}
        for video_id, start, end in windows:
            row = conn.execute(
                "SELECT assessment, reviewed_at FROM feedback WHERE query=? AND search_mode=? AND video_id=? "
                "AND ROUND(start_sec, 3)=ROUND(?, 3) AND ROUND(end_sec, 3)=ROUND(?, 3)",
                (query, search_mode, video_id, start, end)).fetchone()
            if row:
                found[(video_id, start, end)] = dict(row)
        return found
    except sqlite3.Error:
        return {}  # an unreadable review file must never break searching
    finally:
        conn.close()


def export_csv(path):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    if path.exists():
        conn = connect(path)
        try:
            for row in conn.execute('SELECT * FROM feedback ORDER BY reviewed_at'):
                # Spreadsheet apps can execute formulas even inside quoted CSV cells.
                writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(
                    ('=', '+', '-', '@', '\t', '\r', '\n')) else v for v in row])
        finally:
            conn.close()
    return output.getvalue()
