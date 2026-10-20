"""Opt-in visual review of retrieved windows; never interprets rankings as detections."""
import base64
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess

import cv2

from .config import PROJECT_ROOT
from .sentry_client import SearchError, redact

MAX_CANDIDATES = 5
MAX_FRAMES = 6


def frame_samples(settings, hit):
    """Select at most six different extracted frames distributed across one time window."""
    root = settings.frames_dir.resolve()
    conn = sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        count = conn.execute("SELECT COUNT(*) FROM frames WHERE video_id=? AND timestamp_sec BETWEEN ? AND ?",
                             (hit["video_id"], hit["start_sec"], hit["end_sec"])).fetchone()[0]
        n = min(MAX_FRAMES, count)
        chosen = {}
        for i in range(n):
            target = hit["start_sec"] + (hit["end_sec"] - hit["start_sec"]) * i / max(n - 1, 1)
            row = conn.execute("SELECT timestamp_sec,image_path FROM frames WHERE video_id=? "
                               "AND timestamp_sec BETWEEN ? AND ? ORDER BY ABS(timestamp_sec-?) LIMIT 1",
                               (hit["video_id"], hit["start_sec"], hit["end_sec"], target)).fetchone()
            if row is None or row[0] in chosen:
                continue
            path = (root / row[1]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                continue
            image = cv2.imread(str(path))
            if image is None:
                continue
            h, w = image.shape[:2]
            if max(h, w) > 1024:
                image = cv2.resize(image, (max(1, round(w * 1024 / max(h, w))),
                                          max(1, round(h * 1024 / max(h, w)))))
            ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                chosen[row[0]] = {"timestamp_sec": row[0], "jpeg": base64.b64encode(jpeg).decode("ascii")}
        return [chosen[t] for t in sorted(chosen)]
    finally:
        conn.close()


def run_review(payload, search_settings):
    if search_settings.sentry_python is None:
        raise SearchError("The separate search Python environment is required for visual checking.")
    script = PROJECT_ROOT / "search_engine" / "visual_review_bridge.py"
    try:
        proc = subprocess.run([str(search_settings.sentry_python), str(script)],
                              input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", timeout=180, env=dict(os.environ))
    except (OSError, subprocess.TimeoutExpired):
        raise SearchError("Visual checking could not finish. No candidate was marked as a match.") from None
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise SearchError("Visual checker returned an unreadable response.") from None
    if proc.returncode or not isinstance(data, dict) or not data.get("ok"):
        raise SearchError(redact(str(data.get("error", "Visual check failed."))) if isinstance(data, dict)
                          else "Visual check failed.")
    return data.get("results")


def evidence_span(window_start, window_end, sampled, evidence):
    """Tighter time range from the frames the checker cited: [first cited - g/2, last cited + g/2],
    g = mean spacing of the sampled frames, clipped to the scanned window. None without evidence.

    The scanned window stays the provenance; this is a localisation hint only. Measured on recorded
    checker output (synthetic footage, 3 supported windows) it never lowered IoU and raised it from
    0.357 to 0.825 and 0.125 to 0.312 where the checker cited a subset of frames (docs/real-cctv-evaluation.md).
    """
    if not evidence:
        return None
    sampled = sorted(sampled) or sorted(evidence)
    gap = (sampled[-1] - sampled[0]) / (len(sampled) - 1) if len(sampled) > 1 else 1.0
    start = max(window_start, min(evidence) - gap / 2)
    end = min(window_end, max(evidence) + gap / 2)
    if end <= start:
        return None
    return {"start_sec": round(start, 2), "end_sec": round(end, 2)}


def review_results(result, settings, search_settings, reviewer=None):
    """Keep visual candidates separate from unclear and rejected windows. Errors fail closed."""
    reviewer = reviewer or run_review
    original = result["hits"]
    candidates = []
    samples = {}
    for i, hit in enumerate(original[:MAX_CANDIDATES]):
        frames = frame_samples(settings, hit)
        samples[str(i)] = frames
        if frames:
            candidates.append({"id": str(i), "frames": frames})
    decisions = {}
    if candidates:
        response = reviewer({"query": result["query"], "candidates": candidates}, search_settings)
        if not isinstance(response, list):
            raise SearchError("Visual checker did not return candidate decisions.")
        expected = {c["id"] for c in candidates}
        for decision in response:
            if (not isinstance(decision, dict) or not isinstance(decision.get("id"), str)
                    or decision["id"] not in expected):
                raise SearchError("Visual checker returned an unknown candidate.")
            ident = decision["id"]
            if ident in decisions or decision.get("verdict") not in {"supported", "not_supported", "unclear"}:
                raise SearchError("Visual checker returned an invalid candidate decision.")
            reason = decision.get("reason")
            evidence = decision.get("evidence_timestamps")
            allowed_times = {f["timestamp_sec"] for f in samples[ident]}
            if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, list):
                raise SearchError("Visual checker returned incomplete evidence.")
            if any(type(t) not in (int, float) or not math.isfinite(t) or t not in allowed_times for t in evidence):
                raise SearchError("Visual checker cited a frame that was not sampled.")
            if decision["verdict"] == "supported" and not evidence:
                raise SearchError("Visual checker marked a match without frame evidence.")
            decisions[ident] = {"verdict": decision["verdict"], "reason": redact(reason[:1000]),
                                "evidence_timestamps": evidence}
        if set(decisions) != expected:
            raise SearchError("Visual checker did not assess every sampled candidate.")
    groups = {"supported": [], "not_supported": [], "unclear": []}
    for i, hit in enumerate(original):
        ident = str(i)
        decision = decisions.get(ident, {"verdict": "unclear", "reason":
            f"Outside the first {MAX_CANDIDATES} candidates; not visually checked." if i >= MAX_CANDIDATES else
            "No readable extracted frames in this time window.", "evidence_timestamps": []})
        sampled = [f["timestamp_sec"] for f in samples.get(ident, [])]
        hit["visual_review"] = dict(decision, sampled_timestamps=sampled,
                                    evidence_span=evidence_span(hit["start_sec"], hit["end_sec"], sampled,
                                                                decision["evidence_timestamps"]))
        groups[decision["verdict"]].append(hit)
    result["hits"] = groups["supported"]
    result["unclear_hits"] = groups["unclear"]
    result["rejected_hits"] = groups["not_supported"]
    result["visual_review"] = {"checked_candidates": len(candidates),
                               "sampled_frames": sum(len(c["frames"]) for c in candidates),
                               "supported": len(groups["supported"]),
                               "unclear": len(groups["unclear"]), "rejected": len(groups["not_supported"])}
    result["warnings"].append("Visual checking covers sampled frames from at most five retrieved windows. "
                              "It can miss events, misread clothing, and is not a confirmed detection.")
    return result
