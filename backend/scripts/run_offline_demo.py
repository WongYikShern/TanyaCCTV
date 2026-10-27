"""Start an isolated offline demo. No API key, Google client or network search is used.

    python backend/scripts/run_offline_demo.py                  # preset event index (default)
    python backend/scripts/run_offline_demo.py --search replay  # the older recorded-search replay

Event index (default): a new workspace gets the five generated synthetic clips (scripted events) and, if
they are prepared locally, the five CAVIAR clips (data/cctv_validation/caviar/videos), copied only when
their SHA-256 matches the labelled video. Searches match plain words to those annotated events. Cached
YOLO person detections from the saved experiment run are attached to the CAVIAR clips when they are bound
to the same footage; any other video can be analysed from its player page if the YOLO environment is set
up. No detector runs at start-up.

Replay: the previous demo (two synthetic clips, four recorded ranked-search queries).
"""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_demo_footage import EVENT_SCENES, SCENES, make
from tanya import event_index, person_detection
from tanya.config import PROJECT_ROOT, Settings, SearchSettings
from tanya.indexer import Indexer, sha256_file
from tanya.offline_demo import QUERIES, replay_search
from tanya.playback import find_local_ffmpeg
from tanya.search_sync import save_manifest
from tanya.setup_check import check_port, PASS
from tanya.web import create_app

CAVIAR_DIR = PROJECT_ROOT / 'data' / 'cctv_validation' / 'caviar'
PROVISIONAL_EVENTS = PROJECT_ROOT / 'evaluation' / 'provisional' / 'caviar-events.provisional_single_reviewer.json'
PUBLISHER_EVENTS = PROJECT_ROOT / 'evaluation' / 'datasets' / 'caviar-events.json'


def local_ffmpeg():
    """The local FFmpeg encoder only (see tanya.playback.find_local_ffmpeg). Never loads .env or a Google client."""
    return find_local_ffmpeg(PROJECT_ROOT)


def caviar_label_file():
    """The reviewed (provisional, single-reviewer) labels when present locally, else the publisher labels."""
    return PROVISIONAL_EVENTS if PROVISIONAL_EVENTS.is_file() else PUBLISHER_EVENTS


def copy_caviar(video_dir, labels, log=print):
    """Copy prepared CAVIAR clips whose bytes match the labelled video hash. Returns the names copied."""
    import json
    if not labels.is_file():
        log('CAVIAR labels not found; the demo uses synthetic clips only.')
        return []
    clips = json.loads(labels.read_text(encoding='utf-8'))['clips']
    copied = []
    for clip in clips:
        source = CAVIAR_DIR / 'videos' / clip['video']
        if not source.is_file():
            log(f"CAVIAR {clip['video']}: not prepared locally (run download_caviar.py --download, then --prepare); skipped.")
        elif sha256_file(source) != clip['video_sha256']:
            log(f"CAVIAR {clip['video']}: prepared file differs from the labelled video (hash mismatch); skipped.")
        else:
            shutil.copy2(source, video_dir / clip['video'])
            copied.append(clip['video'])
    return copied


def yolo_run_dir():
    """Saved GPU 384 px experiment run (highest measured precision of the saved runs), if present."""
    explicit = os.environ.get('TANYA_YOLO_RESULTS', '').strip()
    if explicit:
        return Path(explicit)
    config = person_detection.load_config()
    return config.home / 'results-384' if config.home else None


def attach_yolo(settings, library, log=print):
    import json
    run_dir = yolo_run_dir()
    manifest_path = CAVIAR_DIR / 'media-manifest.json'
    if not (run_dir and (run_dir / 'results.json').is_file() and manifest_path.is_file()):
        log('No saved YOLO run found; person detections can still be made per video if YOLO is set up.')
        return 0
    manifest = {m['filename']: m['sha256'] for m in json.loads(manifest_path.read_text(encoding='utf-8'))}
    attached = 0
    for name, sha in library.items():
        if person_detection.import_saved_run(settings, run_dir, name, sha, manifest.get(name)):
            attached += 1
    log(f'Attached cached YOLO person detections to {attached} clip(s) from {run_dir.name}.')
    return attached


def prepare(root, search='index', dataset='all', log=print):
    if root.exists() and any(root.iterdir()):
        raise ValueError('Choose a new empty workspace; existing files are never overwritten.')
    settings = Settings(root / 'videos', root / 'frames', root / 'index.db')
    ffmpeg = local_ffmpeg()
    if ffmpeg:
        # Lets the website make local browser copies of uploads too (the demo has no search interpreter).
        os.environ.setdefault('TANYA_FFMPEG', ffmpeg)
    else:
        print('WARNING: FFmpeg was not found, so the demo videos will NOT play in the browser (frames, search '
              'replay and reports still work). Set TANYA_SENTRY_PYTHON or TANYA_FFMPEG and start again.',
              file=sys.stderr, flush=True)
    scenes = dict(SCENES)
    if search == 'replay':
        make(settings.video_dir, ffmpeg, log=log)
    else:
        if dataset in ('all', 'synthetic'):
            scenes.update(EVENT_SCENES)
            make(settings.video_dir, ffmpeg, log=log, scenes=scenes)
        else:
            scenes = {}
            settings.video_dir.mkdir(parents=True, exist_ok=True)
        if dataset in ('all', 'caviar'):
            copy_caviar(settings.video_dir, caviar_label_file(), log)
    Indexer(settings).run()
    with sqlite3.connect(settings.db_path) as conn:
        videos = conn.execute("SELECT rel_path,sha256 FROM videos WHERE status='done'").fetchall()
    save_manifest(settings, {os.path.abspath(settings.video_dir / name): {'sha256': sha} for name, sha in videos})
    search_settings = SearchSettings(None, PROJECT_ROOT / 'search_engine/tanya_bridge.py')
    if search == 'replay':
        return create_app(settings, search_settings, offline_search=replay_search)
    library = dict(videos)
    attach_yolo(settings, library, log)
    index_path = root / 'event-index.json'
    index = event_index.build(index_path, library=library, scenes=scenes, caviar_events=caviar_label_file())
    for note in index['notes']:
        log('Note: ' + note)
    log(f"Event index: {len(index['entries'])} annotated events across {len(library)} video(s) "
        f"(CAVIAR labels: {(index['caviar'] or {}).get('verification', 'none')}).")
    return create_app(settings, search_settings,
                      offline_search=event_index.EventIndexSearch(index_path, person_detection.load_config()))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', type=Path, help='new empty folder; default: a new temporary folder')
    parser.add_argument('--search', choices=('index', 'replay'), default='index')
    parser.add_argument('--dataset', choices=('all', 'synthetic', 'caviar'), default='all',
                        help='footage for the event index (default: all available)')
    parser.add_argument('--host', default=os.environ.get('TANYA_HOST', '127.0.0.1'),
                        help='address to listen on (default: 127.0.0.1; 0.0.0.0 inside a hosted container)')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5001)),
                        help='port to listen on (default: $PORT, else 5001)')
    args = parser.parse_args()
    port = check_port(args.port)
    if port.status != PASS:
        print(f'Cannot start: {port.detail}. Stop the existing website first.', file=sys.stderr)
        return 1
    root = args.workspace.expanduser().resolve() if args.workspace else Path(tempfile.mkdtemp(prefix='tanya-offline-demo-'))
    try:
        app = prepare(root, args.search, args.dataset)
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.search == 'replay':
        print(f'OFFLINE REPLAY — no live AI. Workspace: {root}\nOpen http://localhost:{args.port}/\nQueries: ' + '; '.join(QUERIES), flush=True)
    else:
        print(f'OFFLINE DEMO — preset event index, no live AI. Workspace: {root}\nOpen http://localhost:{args.port}/\n'
              'Try: a person falling; someone entering a shop; a red car; people meeting; a person in the corridor; '
              'a fight (no match).', flush=True)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
