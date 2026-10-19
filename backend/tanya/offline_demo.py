"""Replay recorded results locally; never imports a Google client or calls a bridge."""
import json
import os
import sqlite3

from .config import PROJECT_ROOT
from .search import SearchResponse, build_hits
from .sentry_client import SearchError

QUERIES = ('a person walking', 'a person lying on the floor', 'a red car', 'fire and smoke')


def replay_search(query, settings, search_settings):
    if query not in QUERIES:
        raise SearchError('Offline replay supports only: ' + '; '.join(QUERIES) + '. No live search was run.')
    recording = json.loads((PROJECT_ROOT / 'evaluation/recordings/2026-10-17-gemini-embedding-2.json').read_text(encoding="utf-8"))
    results = recording['responses'][query]
    # Recorded paths are placeholders, never a second source of local files.
    results = [dict(r, source_file=os.path.abspath(settings.video_dir / r['filename'])) for r in results]
    conn = sqlite3.connect(f'{settings.db_path.resolve().as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        hits, warnings = build_hits(results, settings, search_settings, conn)
    finally:
        conn.close()
    warnings.insert(0, 'OFFLINE REPLAY: recorded synthetic results, not a new AI evaluation.')
    return SearchResponse(query, hits, warnings)
