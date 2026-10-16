"""Frame extraction with OpenCV: one video in, JPEG frames + timestamps out.

This module knows nothing about the database or Flask.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2


class VideoError(Exception):
    """The video could not be opened or decoded."""


@dataclass
class ExtractedFrame:
    frame_number: int  # index of the frame in the source video
    timestamp_sec: float
    filename: str  # file name inside the output directory


@dataclass
class ExtractionResult:
    fps: float | None
    width: int
    height: int
    duration_sec: float
    frames: list[ExtractedFrame] = field(default_factory=list)


def _valid_fps(fps: float) -> bool:
    return fps is not None and math.isfinite(fps) and 0 < fps < 1000


def extract_frames(
    video_path: Path,
    out_dir: Path,
    interval_sec: float,
    jpeg_quality: int = 90,
) -> ExtractionResult:
    """Save one JPEG every `interval_sec` seconds of video into `out_dir`.

    Frames are picked at timestamps 0, interval, 2*interval, ... (the first decoded
    frame at or after each mark). Raises VideoError if the video is unreadable.
    """
    if interval_sec <= 0:
        raise ValueError("interval_sec must be positive")

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise VideoError("OpenCV could not open the file (corrupt or unsupported format)")

        fps = cap.get(cv2.CAP_PROP_FPS)
        fps = fps if _valid_fps(fps) else None
        out_dir.mkdir(parents=True, exist_ok=True)
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]

        result = ExtractionResult(fps=fps, width=0, height=0, duration_sec=0.0)
        frame_number = -1
        next_mark = 0.0
        last_ts = 0.0

        # Read sequentially with grab() (fast, no decode) and only decode the frames we keep.
        # Sequential reading gives more reliable timestamps than seeking.
        while cap.grab():
            frame_number += 1
            if fps:
                ts = frame_number / fps
            else:
                ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            last_ts = ts

            if ts + 1e-6 < next_mark:
                continue

            ok, image = cap.retrieve()
            if not ok or image is None:
                raise VideoError(f"Could not decode frame {frame_number}")

            if not result.width:
                result.height, result.width = image.shape[:2]

            ok, buf = cv2.imencode(".jpg", image, encode_params)
            if not ok:
                raise VideoError(f"Could not encode frame {frame_number} as JPEG")

            filename = f"frame_{len(result.frames):06d}_{round(ts * 1000):09d}ms.jpg"
            # write_bytes instead of cv2.imwrite: works with non-ASCII Windows paths.
            (out_dir / filename).write_bytes(buf.tobytes())
            result.frames.append(ExtractedFrame(frame_number, round(ts, 3), filename))

            # Next mark strictly after this timestamp, aligned to multiples of the interval.
            next_mark = (math.floor(ts / interval_sec + 1e-9) + 1) * interval_sec

        if not result.frames:
            raise VideoError("No frames could be read (empty, corrupt or unsupported video)")

        frame_duration = 1.0 / fps if fps else 0.0
        result.duration_sec = round(last_ts + frame_duration, 3)
        return result
    finally:
        cap.release()
