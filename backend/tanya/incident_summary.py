"""AI-drafted incident summary for an investigation: text facts in, a short draft out.

Only text leaves the computer (times, camera names and places, human decisions and notes, the AI
image check's own sentence). The draft is shown to a person, who decides whether to save it as the
case summary; nothing is saved automatically.
"""
import json
import os
import subprocess

from .config import PROJECT_ROOT
from .sentry_client import SearchError, redact

DECISIONS = {"correct": "relevant", "wrong": "not relevant", "unsure": "uncertain", None: "not reviewed"}


def _clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def facts(investigation, cameras_by_sha):
    """The evidence of one investigation as plain facts, in timeline order. Removed clips are left out."""
    out = []
    for e in investigation["evidence"]:
        camera = cameras_by_sha.get(e["video_sha256"], {})
        item = {"camera": camera.get("name") or e.get("current_filename") or e["video_filename"],
                "place": camera.get("place", ""),
                "time_in_recording": f"{_clock(e['start_sec'])}-{_clock(e['end_sec'])}",
                "human_decision": DECISIONS.get(e.get("decision"), "not reviewed"),
                "found_by": "chosen manually" if e["search_mode"] == "manual" else f"search “{e['query']}”"}
        if e.get("absolute_start"):
            item["camera_time"] = e["absolute_start"].replace("T", " ")[:19]
        if e.get("visual_verdict"):
            item["ai_image_check"] = f"{e['visual_verdict'].replace('_', ' ')}: {e.get('visual_reason') or ''}".strip()
        if e.get("note"):
            item["investigator_note"] = e["note"]
        out.append({k: redact(v) if isinstance(v, str) else v for k, v in item.items()})
    return out


def run_summary(payload, search_settings):
    if search_settings.sentry_python is None:
        raise SearchError("The separate search Python environment is required to write a summary.")
    script = PROJECT_ROOT / "search_engine" / "summary_bridge.py"
    try:
        proc = subprocess.run([str(search_settings.sentry_python), str(script)], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", timeout=120, env=dict(os.environ))
    except (OSError, subprocess.TimeoutExpired):
        raise SearchError("The summary could not be written in time. Nothing was saved.") from None
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise SearchError("The summary writer returned an unreadable response.") from None
    if proc.returncode or not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("summary"), str):
        raise SearchError(redact(str(data.get("error", "The summary could not be written."))) if isinstance(data, dict)
                          else "The summary could not be written.")
    return redact(data["summary"].strip())[:2000]
