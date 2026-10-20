"""Browser playback: detect whether a recording can play in a browser, and make a local copy if not.

Browsers (Chrome, Edge, Firefox) play H.264, VP8/VP9 and AV1 video inside MP4/MOV containers.
Many CCTV exports and OpenCV-written test files use MPEG-4 Part 2 ("FMP4"/"mp4v"), MJPEG or
AVI/MKV containers, which browsers refuse ("no supported streams"). For those, a browser-playable
H.264 copy is written to <data>/playback/<sha256>.mp4 with FFmpeg. The copy is local, costs
nothing, is used only for playback, and the original recording is never modified: search,
investigations and reports keep referring to the original's SHA-256.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import cv2

BROWSER_CODECS = {"avc1", "avc3", "h264", "x264", "vp80", "vp08", "vp90", "vp09", "av01"}
BROWSER_CONTAINERS = {".mp4", ".mov", ".m4v"}
CODEC_NAMES = {"fmp4": "MPEG-4 Part 2", "mp4v": "MPEG-4 Part 2", "xvid": "MPEG-4 Part 2 (Xvid)",
               "divx": "MPEG-4 Part 2 (DivX)", "mjpg": "Motion JPEG", "hevc": "H.265/HEVC",
               "hev1": "H.265/HEVC", "hvc1": "H.265/HEVC", "h265": "H.265/HEVC",
               "avc1": "H.264", "avc3": "H.264", "h264": "H.264", "x264": "H.264",
               "vp80": "VP8", "vp08": "VP8", "vp90": "VP9", "vp09": "VP9", "av01": "AV1"}

_probe_cache: dict[tuple, str] = {}
_ffmpeg_cache: dict[str, str | None] = {}


class PlaybackError(RuntimeError):
    """A playback copy could not be made (the message is safe to show to the user)."""


def codec_of(path: Path) -> str:
    """Lower-case FourCC of the first video stream ("" if it cannot be read). Cached per file version."""
    try:
        st = path.stat()
    except OSError:
        return ""
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _probe_cache:
        cap = cv2.VideoCapture(str(path))
        try:
            raw = int(cap.get(cv2.CAP_PROP_FOURCC)) if cap.isOpened() else 0
        finally:
            cap.release()
        code = raw.to_bytes(4, "little", signed=False).decode("latin-1") if raw > 0 else ""
        _probe_cache[key] = code.strip("\x00 ").lower()
    return _probe_cache[key]


def codec_name(code: str) -> str:
    return CODEC_NAMES.get(code, code.upper() if code else "unknown")


def browser_playable(path: Path, code: str | None = None) -> bool:
    code = codec_of(path) if code is None else code
    return path.suffix.lower() in BROWSER_CONTAINERS and code in BROWSER_CODECS


def copy_path(playback_dir: Path, sha256: str) -> Path:
    return playback_dir / f"{sha256}.mp4"


def find_ffmpeg(sentry_python: Path | None = None) -> str | None:
    """FFmpeg from TANYA_FFMPEG, then PATH, then the copy bundled with SentrySearch (imageio-ffmpeg)."""
    explicit = os.environ.get("TANYA_FFMPEG", "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    key = str(sentry_python or "")
    if key in _ffmpeg_cache:
        return _ffmpeg_cache[key]
    found = shutil.which("ffmpeg")
    if not found and sentry_python and Path(sentry_python).is_file():
        try:
            proc = subprocess.run([str(sentry_python), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                                  capture_output=True, text=True, timeout=60)
            exe = proc.stdout.strip()
            found = exe if proc.returncode == 0 and exe and Path(exe).is_file() else None
        except (OSError, subprocess.TimeoutExpired):
            found = None
    _ffmpeg_cache[key] = found
    return found


def find_local_ffmpeg(project_root: Path) -> str | None:
    """FFmpeg for local tools (demo footage, research copies): TANYA_FFMPEG or PATH, else the copy bundled
    with the search environment named by TANYA_SENTRY_PYTHON (the documented Windows setup) or found at
    <project>/.venv/sentry. Only the local encoder is located; no .env, key or Google client is loaded."""
    found = find_ffmpeg(None)
    if found:
        return found
    default = Path(project_root) / ".venv" / "sentry" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    for candidate in (os.environ.get("TANYA_SENTRY_PYTHON", "").strip(), str(default)):
        if candidate and Path(candidate).is_file():
            found = find_ffmpeg(Path(candidate))
            if found:
                return found
    return None


def make_copy(source: Path, target: Path, ffmpeg: str, duration_sec: float | None = None) -> Path:
    """Write a browser-playable H.264 copy of `source` to `target` (atomically). Never touches `source`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.mp4")
    partial.unlink(missing_ok=True)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
           "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(partial)]
    timeout = max(120, int((duration_sec or 0) * 3))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        partial.unlink(missing_ok=True)
        raise PlaybackError(f"Making the browser copy took longer than {timeout} s and was stopped.") from None
    except OSError as e:
        partial.unlink(missing_ok=True)
        raise PlaybackError(f"FFmpeg could not be started ({e}).") from None
    if proc.returncode != 0 or not partial.is_file() or codec_of(partial) not in BROWSER_CODECS:
        detail = (proc.stderr.strip().splitlines() or ["no details"])[-1][:300]
        partial.unlink(missing_ok=True)
        raise PlaybackError(f"FFmpeg could not convert this recording ({detail}).")
    os.replace(partial, target)
    return target
