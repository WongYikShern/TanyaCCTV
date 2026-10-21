"""Optional YOLO person-presence candidates (the app side; never imports torch or Ultralytics).

The detector itself runs only in the separate YOLO environment from experiments/yolo/README.md, via
experiments/yolo/person_candidates.py, for ONE video the user selected. Nothing runs at start-up.

Results are cached per (video SHA-256, weights SHA-256, image size) under <data>/person_detections/.
A cached result whose video hash differs from the library's is never used; one made with different
weights than the configured ones is reported as stale. Person boxes become person-presence candidates
for human review. They are never treated as falls, fights, entries or any other action.

Configuration (all optional; YOLO is simply unavailable without it):
  TANYA_YOLO_HOME     folder with venv/ and weights/ (default %LOCALAPPDATA%\\TanyaCCTV-YOLO)
  TANYA_YOLO_PYTHON   the YOLO environment's python (default <home>/venv/Scripts/python.exe)
  TANYA_YOLO_WEIGHTS  local weights file (default <home>/weights/yolo26n.pt); never downloaded
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT

FORMAT = "tanyacctv-person-detections/1"
SCRIPT = PROJECT_ROOT / "experiments" / "yolo" / "person_candidates.py"
IMGSZ = 384
# Presence threshold. Measured only on the five CAVIAR clips (saved GPU 384 run, cached recount vs publisher
# boxes): precision 0.987, recall 0.267 at >= 0.40. Not a deployment setting; tiny/overhead people are missed.
PRESENCE_CONF = 0.40
MERGE_GAP_SEC = 0.5
MIN_DURATION_SEC = 0.5
CAUTION = ("YOLO person detection only: a candidate that someone may be in view. It is not a fall, fight, "
           "entry or any other action, can miss small or overhead people, and needs human review.")
_sha_cache: dict[tuple, str] = {}


class PersonDetectionError(RuntimeError):
    """Safe to show to the user."""


@dataclass(frozen=True)
class YoloConfig:
    python: Path | None
    weights: Path | None
    home: Path | None
    imgsz: int = IMGSZ

    @property
    def available(self) -> bool:
        return bool(self.python and self.python.is_file() and self.weights and self.weights.is_file()
                    and SCRIPT.is_file())

    def reason(self) -> str | None:
        if self.available:
            return None
        if not (self.python and self.python.is_file()):
            return "The separate YOLO environment was not found (set TANYA_YOLO_HOME or TANYA_YOLO_PYTHON)."
        if not (self.weights and self.weights.is_file()):
            return "No local YOLO weights file was found (set TANYA_YOLO_WEIGHTS). Weights are never downloaded."
        return "experiments/yolo/person_candidates.py is missing."


def load_config() -> YoloConfig:
    home_env = os.environ.get("TANYA_YOLO_HOME", "").strip()
    local = os.environ.get("LOCALAPPDATA")
    home = Path(home_env) if home_env else (Path(local) / "TanyaCCTV-YOLO" if local else None)
    default_python = home / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python") if home else None
    python = os.environ.get("TANYA_YOLO_PYTHON", "").strip()
    weights = os.environ.get("TANYA_YOLO_WEIGHTS", "").strip()
    return YoloConfig(Path(python) if python else default_python,
                      Path(weights) if weights else (home / "weights" / "yolo26n.pt" if home else None), home)


def file_sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _sha_cache:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


def cache_dir(settings) -> Path:
    return Path(settings.db_path).parent / "person_detections"


def presence_intervals(detections: list[dict], conf: float = PRESENCE_CONF, gap: float = MERGE_GAP_SEC,
                       min_duration: float = MIN_DURATION_SEC, fps: float = 25.0) -> list[dict]:
    """Merge frames with a person box >= conf into intervals; report detector-score statistics per interval."""
    out, cur = [], None
    step = 1.0 / fps if fps else 0.04
    for d in sorted(detections, key=lambda d: d["frame"]):
        scores = [b[4] for b in d["boxes"] if b[4] >= conf]
        if not scores:
            continue
        t = float(d["t"])
        if cur and t - cur["end_sec"] <= gap:
            cur["end_sec"] = t + step
            cur["frames"] += 1
            cur["scores"].append(max(scores))
        else:
            cur = {"start_sec": t, "end_sec": t + step, "frames": 1, "scores": [max(scores)]}
            out.append(cur)
    result = []
    for c in out:
        if c["end_sec"] - c["start_sec"] >= min_duration:
            s = c.pop("scores")
            result.append(dict(c, start_sec=round(c["start_sec"], 2), end_sec=round(c["end_sec"], 2),
                               max_conf=round(max(s), 3), mean_conf=round(sum(s) / len(s), 3)))
    return result


def _validate(data: dict, video_sha: str) -> dict:
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("kind") != "person_detection":
        raise PersonDetectionError("Not a TanyaCCTV person-detection result.")
    if data.get("video", {}).get("sha256") != video_sha:
        raise PersonDetectionError("This result was made from different footage (video hash differs); it is not used.")
    frames = [d["frame"] for d in data.get("detections", [])]
    if frames != list(range(len(frames))) or len(frames) != data["video"].get("frames"):
        raise PersonDetectionError("The saved detections have missing or duplicate frames; they are not used.")
    return data


def summary(data: dict, config: YoloConfig | None = None) -> dict:
    """What the UI and search show: intervals plus full identity and staleness."""
    model = data["model"]
    configured = None
    if config and config.weights and config.weights.is_file():
        configured = file_sha256(config.weights)
    recorded = model.get("weights_sha256")
    stale = bool(configured and recorded and configured != recorded)
    fps = float(data["video"].get("fps") or 25.0)
    return {"intervals": presence_intervals(data["detections"], fps=fps), "presence_conf": PRESENCE_CONF,
            "video": {k: data["video"][k] for k in ("name", "sha256", "frames")}, "model": model,
            "runner": data.get("runner", {}), "provenance": data.get("provenance"),
            "stale": stale, "weights_verified": bool(configured and recorded and configured == recorded),
            "caution": CAUTION}


def load_cached(settings, video_sha: str, config: YoloConfig | None = None) -> dict | None:
    """Newest valid cached result for this exact video, or None. Invalid files are skipped, never trusted."""
    folder = cache_dir(settings)
    if not folder.is_dir():
        return None
    best = None
    for path in sorted(folder.glob(f"{video_sha}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = _validate(json.loads(path.read_text(encoding="utf-8")), video_sha)
        except (OSError, ValueError, KeyError, TypeError, PersonDetectionError):
            continue
        result = summary(data, config)
        if not result["stale"]:
            return result
        best = best or result
    return best


def store(settings, data: dict, video_sha: str) -> Path:
    _validate(data, video_sha)
    folder = cache_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    weights = (data["model"].get("weights_sha256") or "unrecorded")[:16]
    target = folder / f"{video_sha}_{weights}_{data['model'].get('imgsz')}.json"
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(data), encoding="utf-8")
    os.replace(partial, target)
    return target


def run(settings, source: Path, video_sha: str, duration_sec: float | None, config: YoloConfig) -> dict:
    """Run the detector on one video in the YOLO environment and cache the result (local only)."""
    if not config.available:
        raise PersonDetectionError(config.reason())
    folder = cache_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"run-{video_sha[:16]}-{os.getpid()}.tmp.json"
    out.unlink(missing_ok=True)
    env = dict(os.environ, YOLO_OFFLINE="1", YOLO_AUTOINSTALL="False")
    if config.home:
        env["YOLO_CONFIG_DIR"] = str(config.home / "config")
    env.pop("GEMINI_API_KEY", None)
    cmd = [str(config.python), str(SCRIPT), "--video", str(source), "--weights", str(config.weights),
           "--out", str(out), "--imgsz", str(config.imgsz)]
    timeout = max(180, int((duration_sec or 0) * 4))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        out.unlink(missing_ok=True)
        raise PersonDetectionError(f"Person detection took longer than {timeout} s and was stopped.") from None
    except OSError as error:
        raise PersonDetectionError(f"The YOLO environment could not be started ({error}).") from None
    try:
        if proc.returncode != 0 or not out.is_file():
            detail = (proc.stderr.strip().splitlines() or ["no details"])[-1][:300]
            raise PersonDetectionError(f"Person detection failed ({detail}).")
        data = json.loads(out.read_text(encoding="utf-8"))
        store(settings, data, video_sha)
    finally:
        out.unlink(missing_ok=True)
    return summary(data, config)


def import_saved_run(settings, run_dir: Path, video_name: str, video_sha: str, manifest_sha: str | None) -> Path | None:
    """Reuse a saved experiment run (experiments/yolo/caviar_yolo.py) as a cache entry, if it is bound to this video.

    Those runs did not record the input video's hash, so the binding is the prepared-media manifest that
    was in place when they ran: the library file's hash must equal the manifest hash for the same name.
    The weights hash was not recorded either; the entry says so instead of guessing."""
    if not manifest_sha or manifest_sha != video_sha:
        return None
    results = run_dir / "results.json"
    detections = run_dir / f"{Path(video_name).stem}_detections.json"
    if not (results.is_file() and detections.is_file()):
        return None
    r = json.loads(results.read_text(encoding="utf-8"))
    clip = next((c for c in r.get("clips", []) if c.get("video") == video_name), None)
    if clip is None:
        return None
    env = r["environment"]
    frames = json.loads(detections.read_text(encoding="utf-8"))
    data = {
        "format": FORMAT, "kind": "person_detection", "caution": CAUTION,
        "video": {"name": video_name, "sha256": video_sha, "frames": len(frames), "fps": 25.0},
        "model": {"weights": env.get("weights"), "weights_sha256": None, "imgsz": env.get("imgsz"),
                  "min_conf": env.get("conf_recorded"), "classes": ["person"], "batch": env.get("batch"),
                  "half": env.get("half")},
        "runner": {"script": "experiments/yolo/caviar_yolo.py", "device": env.get("inference_device"),
                   "torch": env.get("torch"), "ultralytics": env.get("ultralytics"),
                   "network_attempts_blocked": r.get("totals", {}).get("network_attempts_blocked")},
        "provenance": (f"Saved experiment run {run_dir.name} (results.json SHA-256 {file_sha256(results)[:12]}…). "
                       "Video identity is inferred from the prepared-media manifest; that run did not record "
                       "the video or weights hash, so the model file cannot be verified."),
        "detections": frames,
    }
    if clip.get("frames") != len(frames):
        return None
    return store(settings, data, video_sha)
