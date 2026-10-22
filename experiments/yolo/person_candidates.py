"""Person detection on ONE local video, for the TanyaCCTV app's optional "find people" step.

Runs only inside the separate YOLO environment (see README.md), never the app's .venv:

    python experiments/yolo/person_candidates.py --video C:\\path\\clip.mp4 --weights C:\\...\\yolo26n.pt --out result.json

Reuses the experiment's offline guards (YOLO_OFFLINE, no auto-install, settings sync off, socket guard that
blocks and counts every connection attempt) and its detection format:
[{"frame": n, "t": seconds, "boxes": [[x1, y1, x2, y2, conf], ...]}] with person boxes >= --min-conf.

The output records the identity of everything that produced it (video and weights SHA-256, image size,
confidence floor, this script's SHA-256, package versions, device), so the app can tell when a cached
result no longer matches the footage or model. Person boxes are person-presence candidates only: a box
per frame says nothing about falls, fights or any other action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from caviar_yolo import DEFAULT_HOME, PERSON, NetworkGuard, offline_guards  # noqa: E402

FORMAT = "tanyacctv-person-detections/1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def script_sha256() -> str:
    """Line-ending independent, so a Windows CRLF checkout and a Mac LF checkout give the same identity."""
    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def detect(video: Path, weights: Path, imgsz: int, min_conf: float, device: str | None) -> dict:
    os.environ.setdefault("YOLO_CONFIG_DIR", str(DEFAULT_HOME / "config"))
    with NetworkGuard() as guard:
        offline_guards()
        import cv2
        import torch
        import ultralytics
        from ultralytics import YOLO
        device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        started = time.perf_counter()
        model = YOLO(str(weights))
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise SystemExit(f"Cannot open video: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frames, index = [], 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                # Batch 1, FP32, person class only: tens of MB of GPU memory on the 4 GB RTX 3050 Ti.
                r = model.predict(frame, imgsz=imgsz, conf=min_conf, classes=[PERSON], device=device,
                                  verbose=False)[0]
                boxes = r.boxes
                dets = ([[round(v, 1) for v in b] + [round(float(c), 3)]
                         for b, c in zip(boxes.xyxy.tolist(), boxes.conf.tolist())] if boxes is not None else [])
                frames.append({"frame": index, "t": round(index / fps, 3), "boxes": dets})
                index += 1
        finally:
            cap.release()
        peak = round(torch.cuda.max_memory_allocated() / 2**20, 1) if device.startswith("cuda") else None
        seconds = round(time.perf_counter() - started, 2)
    if guard.attempts:
        raise SystemExit(f"Refusing to save: {len(guard.attempts)} network attempt(s) were blocked.")
    return {
        "format": FORMAT,
        "kind": "person_detection",
        "caution": "Person boxes are person-presence candidates for human review. They are not falls, "
                   "fights, entries or any other recognised action.",
        "video": {"name": video.name, "sha256": sha256(video), "frames": len(frames), "fps": fps},
        "model": {"weights": weights.name, "weights_sha256": sha256(weights), "imgsz": imgsz,
                  "min_conf": min_conf, "classes": ["person"], "batch": 1, "half": False},
        "runner": {"script": "experiments/yolo/person_candidates.py", "script_sha256": script_sha256(),
                   "python": platform.python_version(), "torch": torch.__version__,
                   "ultralytics": ultralytics.__version__, "device": device, "seconds": seconds,
                   "peak_gpu_allocated_mb": peak, "network_attempts_blocked": 0},
        "detections": frames,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--weights", type=Path, required=True, help="local weights file (never downloaded)")
    p.add_argument("--out", type=Path, required=True, help="new JSON file; an existing file is never overwritten")
    p.add_argument("--imgsz", type=int, default=384, choices=(320, 384, 480, 640))
    p.add_argument("--min-conf", type=float, default=0.10)
    p.add_argument("--device", help="cuda:0 or cpu (default: GPU if available)")
    args = p.parse_args(argv)
    for path, what in ((args.video, "video"), (args.weights, "weights")):
        if not path.is_file():
            print(f"{what} not found: {path}", file=sys.stderr)
            return 2
    if args.out.exists():
        print(f"Refusing to overwrite {args.out}", file=sys.stderr)
        return 2
    if not 0.01 <= args.min_conf <= 0.9:
        print("--min-conf must be between 0.01 and 0.9", file=sys.stderr)
        return 2
    result = detect(args.video, args.weights, args.imgsz, args.min_conf, args.device)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_name(args.out.name + ".partial")
    partial.write_text(json.dumps(result), encoding="utf-8")
    os.replace(partial, args.out)
    print(json.dumps({"frames": result["video"]["frames"], "seconds": result["runner"]["seconds"],
                      "device": result["runner"]["device"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
