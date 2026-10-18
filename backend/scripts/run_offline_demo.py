"""Start an isolated synthetic, recorded-search demo. No API key or network search needed."""
import argparse
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_demo_footage import make
from tanya.config import PROJECT_ROOT, Settings, SearchSettings
from tanya.indexer import Indexer
from tanya.offline_demo import QUERIES, replay_search
from tanya.playback import find_ffmpeg
from tanya.search_sync import save_manifest
from tanya.setup_check import check_port, PASS
from tanya.web import create_app
import sqlite3
import os


def prepare(root):
    if root.exists() and any(root.iterdir()):
        raise ValueError('Choose a new empty workspace; existing files are never overwritten.')
    settings = Settings(root / 'videos', root / 'frames', root / 'index.db')
    # Discover only the local encoder; never load .env or configure a Google client.
    sentry = PROJECT_ROOT / '.venv/sentry' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    make(settings.video_dir, find_ffmpeg(sentry), log=print)
    Indexer(settings).run()
    with sqlite3.connect(settings.db_path) as conn:
        videos = conn.execute('SELECT rel_path,sha256 FROM videos').fetchall()
    save_manifest(settings, {os.path.abspath(settings.video_dir / name): {'sha256': sha} for name, sha in videos})
    return create_app(settings, SearchSettings(None, PROJECT_ROOT / 'search_engine/tanya_bridge.py'),
                      offline_search=replay_search)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, help='new empty folder; default: a new temporary folder')
    args = parser.parse_args()
    port = check_port()
    if port.status != PASS:
        print(f'Cannot start: {port.detail}. Stop the existing website first.', file=sys.stderr)
        return 1
    root = args.workspace.expanduser().resolve() if args.workspace else Path(tempfile.mkdtemp(prefix='tanya-offline-demo-'))
    try:
        app = prepare(root)
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f'OFFLINE REPLAY — no live AI. Workspace: {root}\nOpen http://localhost:5001/\nQueries: ' + '; '.join(QUERIES), flush=True)
    app.run(host='127.0.0.1', port=5001, debug=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
