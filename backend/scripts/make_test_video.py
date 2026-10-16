"""Create a small synthetic test video (a moving square) for trying out the indexer.

Usage:
    python backend/scripts/make_test_video.py data/videos/synthetic_cam1.mp4 --seconds 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a synthetic test video.")
    parser.add_argument("output", type=Path, help="output file (.mp4 or .avi)")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0, help="change this to get different content")
    args = parser.parse_args(argv)

    if args.output.exists():
        print(f"Refusing to overwrite existing file: {args.output}", file=sys.stderr)
        return 1
    if not 0 < args.seconds <= 600 or not 1 <= args.fps <= 60:
        print("--seconds must be in (0, 600] and --fps in [1, 60]", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fourcc = "mp4v" if args.output.suffix.lower() == ".mp4" else "MJPG"
    w, h = 320, 240
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*fourcc), args.fps, (w, h))
    if not writer.isOpened():
        print(f"OpenCV could not create {args.output}", file=sys.stderr)
        return 1
    rng = np.random.default_rng(args.seed)
    color = tuple(int(c) for c in rng.integers(50, 255, 3))
    total = int(args.seconds * args.fps)
    for i in range(total):
        frame = np.full((h, w, 3), 30, np.uint8)
        x = int((w - 40) * i / max(total - 1, 1))
        cv2.rectangle(frame, (x, 100), (x + 40, 140), color, -1)
        cv2.putText(frame, f"t={i / args.fps:5.2f}s", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    print(f"Wrote {args.output} ({args.seconds}s at {args.fps} fps, {total} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
