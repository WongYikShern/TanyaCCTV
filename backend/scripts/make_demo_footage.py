"""Generate synthetic CCTV-style demo footage with known events (cartoon scenes; no real people).

    python backend/scripts/make_demo_footage.py                 # demo set, into data/videos
    python backend/scripts/make_demo_footage.py --set events    # extra event clips (evaluation)
    python backend/scripts/make_demo_footage.py --out C:\\demo   # any folder

Demo set (default; evaluation/synthetic_ground_truth.json):
  cam1_lobby.mp4      60 s: empty lobby 0-20 s, person walking 20-40 s, person lying on the floor 40-60 s
  cam2_carpark.mp4    40 s: empty car park 0-20 s, red car driving through 20-40 s
Events set (evaluation/synthetic_events_v2.json, which annotates all five clips):
  cam3_entrance.mp4   60 s: person enters through a door 10-20 s, stands still 20-45 s, leaves 45-55 s
  cam4_driveway.mp4   50 s: blue car arrives and parks 10-20 s, parked 20-35 s, drives away 35-45 s
  cam5_corridor.mp4   40 s: person walking 5-20 s, falls 20-23 s, lying on the floor 23-40 s

Tests keep these events in sync with the ground-truth files.
Existing files are never overwritten. Browsers play only H.264 MP4: when FFmpeg is available
(on PATH, via --ffmpeg, or inside the SentrySearch environment) the clips are converted to
H.264; otherwise OpenCV writes MPEG-4 Part 2 ("mp4v"), which indexes and searches fine but
will not play in the browser (extracted frames still work).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tanya.config import PROJECT_ROOT, load_search_settings  # noqa: E402

W, H, FPS = 640, 360, 15

# Ground truth: (file, duration_sec, [(event, start_sec, end_sec), ...])
SCENES = {
    "cam1_lobby.mp4": (60, [("a person walking", 20, 40), ("a person lying on the floor", 40, 60)]),
    "cam2_carpark.mp4": (40, [("a red car", 20, 40)]),
}


def _person(img, x, y, t, lying=False):
    skin, shirt, pants = (150, 180, 220), (200, 80, 30), (60, 50, 40)
    if lying:
        cv2.circle(img, (x, y), 14, skin, -1)
        cv2.rectangle(img, (x + 14, y - 12), (x + 80, y + 12), shirt, -1)
        cv2.line(img, (x + 80, y - 6), (x + 140, y - 10), pants, 10)
        cv2.line(img, (x + 80, y + 6), (x + 140, y + 12), pants, 10)
        return
    swing = int(18 * np.sin(t * 6))
    cv2.circle(img, (x, y - 95), 15, skin, -1)
    cv2.rectangle(img, (x - 14, y - 80), (x + 14, y - 25), shirt, -1)
    cv2.line(img, (x, y - 70), (x - swing, y - 35), skin, 6)
    cv2.line(img, (x, y - 70), (x + swing, y - 35), skin, 6)
    cv2.line(img, (x, y - 25), (x - swing, y + 20), pants, 9)
    cv2.line(img, (x, y - 25), (x + swing, y + 20), pants, 9)


def _car(img, x, y):
    red = (30, 30, 200)
    cv2.rectangle(img, (x, y), (x + 150, y + 45), red, -1)
    cv2.rectangle(img, (x + 30, y - 30), (x + 115, y), red, -1)
    cv2.rectangle(img, (x + 40, y - 24), (x + 105, y - 4), (200, 170, 120), -1)
    for wx in (x + 30, x + 120):
        cv2.circle(img, (wx, y + 45), 16, (20, 20, 20), -1)


def _stamp(img, cam, t):
    cv2.putText(img, f"{cam}  00:{int(t) // 60:02d}:{int(t) % 60:02d}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


def lobby_frame(t: float) -> np.ndarray:
    img = np.full((H, W, 3), (170, 175, 180), np.uint8)
    img[220:] = (110, 120, 130)
    cv2.rectangle(img, (480, 60), (580, 220), (60, 90, 140), -1)
    cv2.rectangle(img, (60, 150), (200, 220), (90, 70, 50), -1)
    if 20 <= t < 40:
        _person(img, int(80 + (t - 20) * 25), 300, t)
    elif t >= 40:
        _person(img, 260, 300, t, lying=True)
    _stamp(img, "CAM1 LOBBY", t)
    return img


def carpark_frame(t: float) -> np.ndarray:
    img = np.full((H, W, 3), (80, 80, 80), np.uint8)
    for x in range(40, W, 110):
        cv2.line(img, (x, 40), (x, 140), (230, 230, 230), 3)
        cv2.line(img, (x, 230), (x, 330), (230, 230, 230), 3)
    if 20 <= t < 40:
        _car(img, int(-150 + (t - 20) * 40), 175)
    _stamp(img, "CAM2 CARPARK", t)
    return img


# --------------------------------------------------------------------------- events set

EVENT_SCENES = {
    "cam3_entrance.mp4": (60, [("a person entering through a door", 10, 20),
                               ("a person standing still for a long time", 20, 45),
                               ("a person leaving through a door", 45, 55)]),
    "cam4_driveway.mp4": (50, [("a car arriving and parking", 10, 20), ("a parked car", 20, 35),
                               ("a car driving away", 35, 45)]),
    "cam5_corridor.mp4": (40, [("a person walking", 5, 20), ("a person falling down", 20, 23),
                               ("a person lying on the floor", 23, 40)]),
}


def _door(img, open_):
    cv2.rectangle(img, (480, 60), (580, 220), (25, 25, 25) if open_ else (60, 90, 140), -1)
    cv2.rectangle(img, (474, 54), (586, 222), (40, 60, 90), 4)


def entrance_frame(t: float) -> np.ndarray:
    img = np.full((H, W, 3), (165, 172, 176), np.uint8)
    img[220:] = (105, 112, 122)
    _door(img, 9 <= t < 21 or 44 <= t < 56)
    if 10 <= t < 20:                                   # walks in from the door
        _person(img, int(530 - (t - 10) * 23), 300, t)
    elif 20 <= t < 45:                                 # stands still (loitering)
        _person(img, 300, 300, 0.0)
    elif 45 <= t < 55:                                 # walks back out through the door
        _person(img, int(300 + (t - 45) * 23), 300, t)
    _stamp(img, "CAM3 ENTRANCE", t)
    return img


def _blue_car(img, x, y):
    blue = (170, 90, 30)
    cv2.rectangle(img, (x, y), (x + 150, y + 45), blue, -1)
    cv2.rectangle(img, (x + 30, y - 30), (x + 115, y), blue, -1)
    cv2.rectangle(img, (x + 40, y - 24), (x + 105, y - 4), (200, 170, 120), -1)
    for wx in (x + 30, x + 120):
        cv2.circle(img, (wx, y + 45), 16, (20, 20, 20), -1)


def driveway_frame(t: float) -> np.ndarray:
    img = np.full((H, W, 3), (95, 98, 92), np.uint8)
    cv2.rectangle(img, (240, 150), (420, 260), (230, 230, 230), 3)  # parking bay
    if 10 <= t < 20:
        _blue_car(img, int(-150 + (t - 10) * 40), 190)
    elif 20 <= t < 35:
        _blue_car(img, 250, 190)
    elif 35 <= t < 45:
        _blue_car(img, int(250 + (t - 35) * 45), 190)
    _stamp(img, "CAM4 DRIVEWAY", t)
    return img


def _falling(img, x, y, frac):
    """Body rotating from upright (frac 0) to lying (frac 1) around the feet at (x, y + 20)."""
    import math
    angle = frac * math.pi / 2
    fx, fy = x, y + 20
    def at(d):  # point at distance d up the body axis
        return int(fx + d * math.sin(angle)), int(fy - d * math.cos(angle))
    cv2.line(img, (fx, fy), at(45), (60, 50, 40), 9)
    cv2.line(img, at(45), at(100), (200, 80, 30), 26)
    cv2.circle(img, at(115), 15, (150, 180, 220), -1)


def corridor_frame(t: float) -> np.ndarray:
    img = np.full((H, W, 3), (185, 180, 168), np.uint8)
    img[230:] = (120, 118, 110)
    cv2.line(img, (0, 230), (W, 230), (90, 90, 85), 3)
    if 5 <= t < 20:
        _person(img, int(60 + (t - 5) * 16), 300, t)
    elif 20 <= t < 23:
        _falling(img, 300, 300, (t - 20) / 3)
    elif t >= 23:
        _person(img, 300, 315, t, lying=True)
    _stamp(img, "CAM5 CORRIDOR", t)
    return img


RENDERERS = {"cam1_lobby.mp4": lobby_frame, "cam2_carpark.mp4": carpark_frame,
             "cam3_entrance.mp4": entrance_frame, "cam4_driveway.mp4": driveway_frame,
             "cam5_corridor.mp4": corridor_frame}
SETS = {"demo": SCENES, "events": EVENT_SCENES, "all": {**SCENES, **EVENT_SCENES}}


def write_frames(path: Path, seconds: int, render, fourcc: str) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), FPS, (W, H))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not create {path}")
    rng = np.random.default_rng(0)
    for i in range(seconds * FPS):
        img = render(i / FPS)
        noise = rng.integers(-6, 7, img.shape, dtype=np.int16)  # sensor noise
        writer.write(np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8))
    writer.release()


def find_ffmpeg(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else None
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    python = load_search_settings().sentry_python  # SentrySearch bundles imageio-ffmpeg
    if python and python.is_file():
        try:
            proc = subprocess.run([str(python), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                                  capture_output=True, text=True, timeout=60)
            exe = proc.stdout.strip()
            if proc.returncode == 0 and exe and Path(exe).is_file():
                return exe
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def make(out_dir: Path, ffmpeg: str | None, log=print, scenes: dict | None = None) -> list[Path]:
    scenes = SCENES if scenes is None else scenes
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = [name for name in scenes if (out_dir / name).exists()]
    if existing:
        raise FileExistsError("refusing to overwrite existing file(s): " + ", ".join(existing))
    written = []
    for name, (seconds, _) in scenes.items():
        target = out_dir / name
        if ffmpeg:
            with tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp) / "raw.avi"
                write_frames(raw, seconds, RENDERERS[name], "MJPG")
                proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-i", str(raw),
                                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                                       str(target)], capture_output=True, text=True, timeout=600)
                if proc.returncode != 0:
                    raise RuntimeError(f"FFmpeg failed for {name}: {proc.stderr.strip()[-300:]}")
            log(f"Wrote {target} ({seconds} s, H.264: plays in the browser)")
        else:
            write_frames(target, seconds, RENDERERS[name], "mp4v")
            log(f"Wrote {target} ({seconds} s, mp4v: searchable, but will not play in the browser)")
        written.append(target)
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Generate synthetic demo footage with known events.")
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "videos")
    p.add_argument("--ffmpeg", help="path to ffmpeg (default: PATH, then the SentrySearch environment)")
    p.add_argument("--no-ffmpeg", action="store_true", help="skip H.264 conversion")
    p.add_argument("--set", choices=sorted(SETS), default="demo", help="which clips to make (default: demo)")
    args = p.parse_args(argv)
    ffmpeg = None if args.no_ffmpeg else find_ffmpeg(args.ffmpeg)
    if args.ffmpeg and not ffmpeg:
        print(f"FFmpeg not found at {args.ffmpeg}", file=sys.stderr)
        return 2
    try:
        make(args.out, ffmpeg, scenes=SETS[args.set])
    except FileExistsError as e:
        print(f"{e}. Delete or move them yourself, or choose another --out folder.", file=sys.stderr)
        return 1
    print("Events: " + "; ".join(f"{f}: " + ", ".join(f"{e} {s}-{t}s" for e, s, t in ev)
                                  for f, (_, ev) in SETS[args.set].items()))
    print("Next: python backend/scripts/index_videos.py (or 'Index local videos' in the website).")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
