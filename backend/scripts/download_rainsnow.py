"""Acquire a fixed licensed RainSnow subset; local review only, never cloud processing."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'evaluation/datasets/rainsnow-small.json'
FOLDER = ROOT / 'data/cctv_validation/rainsnow'
LIMIT = 160_000_000


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def acquire(clip):
    """Pin archives and extract only the expected member, never archive paths."""
    name = clip['name']
    archive = FOLDER / (name + '.zip')
    partial = archive.with_suffix('.partial')
    FOLDER.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        path = clip['publisher_path']
        url = 'https://www.kaggle.com/api/v1/datasets/download/aalborguniversity/aau-rainsnow?' + urllib.parse.urlencode({'file_name': path})
        context = ssl.create_default_context()
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        try:
            with urllib.request.urlopen(url, timeout=90, context=context) as response, partial.open('xb') as out:
                total = 0
                while block := response.read(256 * 1024):
                    total += len(block)
                    if total > LIMIT:
                        raise ValueError('Archive exceeds size limit')
                    out.write(block)
            if sha(partial) != clip['archive_sha256']:
                raise ValueError('Publisher archive differs from pinned hash')
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    if archive.stat().st_size > LIMIT or sha(archive) != clip['archive_sha256']:
        raise ValueError('Existing archive differs from pinned source')
    target = FOLDER / 'originals' / (name + '.mkv')
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        with zipfile.ZipFile(archive) as z:
            if z.namelist() != ['cam1.mkv'] or z.getinfo('cam1.mkv').file_size > LIMIT:
                raise ValueError('Unexpected archive contents')
            part = target.with_suffix('.partial')
            try:
                with z.open('cam1.mkv') as source, part.open('xb') as out:
                    shutil.copyfileobj(source, out)
                if sha(part) != clip['video_sha256']:
                    raise ValueError('Extracted source differs from pinned hash')
                part.replace(target)
            finally:
                part.unlink(missing_ok=True)
    if sha(target) != clip['video_sha256']:
        raise ValueError('Existing source differs from pinned hash')
    print('Verified', name, flush=True)


def prepare(clips):
    sys.path.insert(0, str(ROOT / 'backend'))
    import cv2
    from tanya.config import Settings
    from tanya.indexer import Indexer
    from tanya.playback import find_ffmpeg
    executable = ROOT / '.venv/sentry' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    ffmpeg = find_ffmpeg(executable)
    if not ffmpeg:
        raise ValueError('Local FFmpeg is required')
    videos = FOLDER / 'videos'
    videos.mkdir(parents=True, exist_ok=True)
    media = []
    for clip in clips:
        source = FOLDER / 'originals' / (clip['name'] + '.mkv')
        if sha(source) != clip['video_sha256']:
            raise ValueError('Source hash mismatch')
        target = videos / (clip['name'] + '.mp4')
        if not target.exists():
            partial = target.with_suffix('.partial.mp4')
            try:
                subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-i', str(source),
                    '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(partial)],
                    capture_output=True, check=True, timeout=300)
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        cap = cv2.VideoCapture(str(target))
        fps, count = cap.get(cv2.CAP_PROP_FPS), 0
        width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        try:
            while cap.read()[0]:
                count += 1
        finally:
            cap.release()
        if count != clip['decoded_frames'] or abs(fps - clip['fps']) > 0.01:
            raise ValueError('Review copy frame count/rate differs from measured source')
        media.append(dict(filename=target.name, fps=fps, decoded_frames=count, duration_sec=count/fps,
                          width=width, height=height, sha256=sha(target)))
        print('Decoded', target.name, count, 'frames', flush=True)
    summary = Indexer(Settings(videos, FOLDER/'frames', FOLDER/'videos.db'), log=lambda _: None).run()
    if summary.has_failures:
        raise ValueError('Local research indexing failed')
    (FOLDER/'media-manifest.json').write_text(json.dumps(media, indent=2)+'\n', encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--download', action='store_true')
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--serve', action='store_true')
    args = p.parse_args()
    plan = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print(plan['attribution'], '; CC BY 4.0; Google processing disabled.')
    if not any(vars(args).values()):
        print('Plan only: six RGB recordings; use --download, then --prepare, then --serve.')
        return 0
    if args.download:
        for clip in plan['clips']:
            acquire(clip)
    if args.prepare:
        prepare(plan['clips'])
    if args.serve:
        if not (FOLDER/'media-manifest.json').exists():
            raise ValueError('Run --prepare first')
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(Path(__file__).parent))
        from download_caviar import review_app
        from tanya.setup_check import check_port, PASS
        if check_port(5001).status != PASS:
            raise ValueError('Stop the other localhost:5001 viewer first')
        app = review_app(FOLDER)
        app.config['LOCAL_RESEARCH_SOURCE'] = plan['source_page']
        app.config['LOCAL_RESEARCH_TITLE'] = 'AAU RainSnow real traffic-camera research set.'
        app.config['LOCAL_RESEARCH_ATTRIBUTION'] = plan['attribution'] + '. CC BY 4.0.'
        app.run(host='127.0.0.1', port=5001, debug=False)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print('Stopped:', error, file=sys.stderr)
        sys.exit(1)
