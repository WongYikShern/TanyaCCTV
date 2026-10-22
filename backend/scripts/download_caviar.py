"""Download the fixed CAVIAR research subset locally. Never sends footage to an AI service."""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'evaluation/datasets/caviar-small.json'


def download(url, target, limit, expected=None):
    if target.exists():
        if target.stat().st_size > limit:
            raise ValueError(f'Existing file exceeds local size limit: {target.name}')
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if expected and digest != expected:
            raise ValueError(f'Existing file differs from expected hash: {target.name}')
        return dict(bytes=target.stat().st_size, sha256=digest)
    if not url.startswith('https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA'):
        raise ValueError('Only the reviewed publisher URLs may be downloaded')
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.partial')
    try:
        context = ssl.create_default_context()
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        digest, total = hashlib.sha256(), 0
        with urllib.request.urlopen(url, timeout=45, context=context) as response, partial.open('xb') as out:
            if not response.geturl().startswith('https://homepages.inf.ed.ac.uk/'):
                raise ValueError('Publisher redirected to another origin')
            while block := response.read(256 * 1024):
                total += len(block)
                if total > limit:
                    raise ValueError(f'Download exceeded local size limit: {target.name}')
                digest.update(block);out.write(block)
        if expected and digest.hexdigest() != expected:
            raise ValueError(f'Publisher file differs from expected hash: {target.name}')
        partial.replace(target)
        return dict(bytes=total, sha256=digest.hexdigest())
    except BaseException:
        partial.unlink(missing_ok=True)
        raise



def prepare(folder, clips):
    """Local conversion/indexing only; preserve originals and decoded frame order."""
    sys.path.insert(0, str(ROOT / 'backend'))
    import cv2
    from tanya.config import Settings
    from tanya.indexer import Indexer
    from tanya.playback import find_local_ffmpeg
    ffmpeg = find_local_ffmpeg(ROOT)   # PATH, TANYA_FFMPEG, TANYA_SENTRY_PYTHON (Windows) or .venv/sentry
    if not ffmpeg:
        raise ValueError('Local FFmpeg is required for research MP4 copies; originals are unchanged.')
    videos = folder / 'videos';videos.mkdir(parents=True, exist_ok=True)
    manifest = []
    for clip in clips:
        source = folder / 'originals' / (clip['name'] + '.mpg')
        target = videos / (clip['name'] + '.mp4')
        if not source.is_file():
            raise ValueError('Download the reviewed source files before --prepare.')
        if not target.exists():
            partial = target.with_suffix('.partial.mp4')
            try:
                subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-i', str(source),
                    '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-pix_fmt', 'yuv420p', '-vf', 'setpts=N/(25*TB)', '-r', '25',
                    '-fps_mode', 'cfr', '-movflags', '+faststart', str(partial)],
                    capture_output=True, check=True, timeout=180)
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        cap = cv2.VideoCapture(str(target))
        try:
            fps, count = cap.get(cv2.CAP_PROP_FPS), 0
            width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            while True:
                ok, _ = cap.read()
                if not ok:break
                count += 1
        finally:
            cap.release()
        if fps <= 0 or count == 0:
            raise ValueError(f'Cannot decode prepared video: {target.name}')
        manifest.append(dict(filename=target.name, fps=fps, decoded_frames=count,
                             duration_sec=count/fps, width=width, height=height,
                             sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
        print('Prepared',target.name, count,'frames',flush=True)
    settings = Settings(videos, folder/'frames', folder/'videos.db')
    summary = Indexer(settings, log=lambda _: None).run()
    if summary.has_failures:
        raise ValueError('Local indexing reported failures; inspect the separate research database.')
    (folder/'media-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding="utf-8")
    print('Prepared and locally indexed five research clips; no AI search preparation.')



def review_app(folder):
    """View the research library with every search/AI endpoint disabled server-side."""
    sys.path.insert(0, str(ROOT / 'backend'))
    from flask import jsonify, request
    from tanya.config import Settings, SearchSettings
    from tanya.web import create_app
    app = create_app(Settings(folder/'videos', folder/'frames', folder/'videos.db'),
                     SearchSettings(None, ROOT/'search_engine/tanya_bridge.py'))
    app.config['LOCAL_RESEARCH_SOURCE'] = 'https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/'
    @app.before_request
    def local_research_only():
        if request.path.startswith('/api/search'):
            return jsonify(error='Google processing is disabled in this local research viewer.'), 403
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='download public files; default is plan only')
    parser.add_argument('--prepare', action='store_true', help='locally convert/index already downloaded clips; no network')
    parser.add_argument('--serve', action='store_true', help='view the prepared local dataset at localhost:5001; all AI endpoints disabled')
    args = parser.parse_args()
    plan = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print('Source:', plan['source_page']);print('Attribution:', plan['attribution'])
    print('Five staged real-camera clips plus publisher XML labels; no Google processing.')
    if not args.download and not args.prepare and not args.serve:
        print('Nothing downloaded. Use --download to fetch the reviewed subset.');return 0
    folder = ROOT / 'data/cctv_validation/caviar'
    results = []
    try:
        for clip in plan['clips'] if args.download else []:
            entry = dict(name=clip['name'])
            for kind, suffix, limit in [('video', '.mpg', 60_000_000), ('annotation', '.xml', 8_000_000)]:
                url = clip[kind + '_url']
                target = folder / ('originals' if kind == 'video' else 'annotations') / (clip['name'] + suffix)
                entry[kind] = download(url, target, limit, clip.get(kind + '_sha256'))
                print(clip['name'],kind,entry[kind]['bytes'],'bytes',flush=True)
            results.append(entry)
        if args.download:
            (folder/'download-manifest.json').write_text(json.dumps(results,indent=2)+'\n', encoding="utf-8")
        if args.prepare:
            prepare(folder, plan['clips'])
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Download stopped: {error}',file=sys.stderr);return 1
    print('Saved locally in', folder, '; footage and labels are ignored by Git.')
    if args.serve:
        sys.path.insert(0, str(ROOT / 'backend'))
        from tanya.setup_check import check_port, PASS
        if not (folder/'media-manifest.json').is_file():
            print('Run --prepare before --serve.', file=sys.stderr);return 1
        if check_port().status != PASS:
            print('Stop the existing localhost:5001 website before --serve.', file=sys.stderr);return 1
        print('Local research viewer: http://localhost:5001/ — Google processing disabled.',flush=True)
        review_app(folder).run(host='127.0.0.1', port=5001, debug=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
