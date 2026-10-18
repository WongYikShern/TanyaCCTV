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
