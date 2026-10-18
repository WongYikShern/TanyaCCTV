"""The documented 8-step demo (docs/demo.md), end to end through the real Flask app.

Uses the synthetic demo scenes and the fake bridge, which replays recorded real Gemini scores.
Nothing is sent to Google; the only thing substituted is the search engine subprocess.
"""

from __future__ import annotations

import csv
import io

import pytest

from tanya import search_sync
from tanya.web import create_app
from tests.search_fixtures import search_env  # noqa: F401


@pytest.fixture
def demo(search_env):  # noqa: F811
    app = create_app(search_env.settings, search_env.search_settings)
    client = app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    return client, headers, search_env


def test_documented_demo_workflow(demo):
    client, headers, env = demo

    # 1. Import or select a recording (synthetic clips copied into the video folder, then indexed).
    summary = client.post("/api/index", headers=headers).json
    assert all(o["status"] in ("indexed", "skipped") for o in summary["outcomes"])
    videos = {v["filename"]: v for v in client.get("/api/videos").json["videos"]}
    assert set(videos) == {"cam1_lobby.mp4", "cam2_carpark.mp4"}

    # 2. Check readiness: frames are ready, AI preparation is a separate, visible step.
    assert all(v["status"] == "done" and v["frame_count"] > 0 for v in videos.values())
    assert {v["search_state"] for v in videos.values()} == {"needs_preparation"}
    sha = env.ws.rows("SELECT rel_path, sha256 FROM videos")
    search_sync.save_manifest(env.settings, {env.source(r): {"sha256": h} for r, h in sha})  # as after "Prepare AI search"
    status = client.get("/api/status").json
    assert status["coverage"]["prepared"] and not status["coverage"]["needs_preparation"]

    # 3. Natural-language query (ranked mode; visual checking needs separate consent).
    response = client.post("/api/search", headers=headers, json={"query": "a red car"})
    assert response.status_code == 200
    result = response.json

    # 4. Ranked results with bounded timestamps, all unverified and unreviewed.
    top = result["hits"][0]
    assert (top["filename"], top["start_sec"], top["end_sec"]) == ("cam2_carpark.mp4", 16.0, 40.0)
    for hit in result["hits"]:
        duration = videos[hit["filename"]]["duration_sec"]
        assert 0 <= hit["start_sec"] < hit["end_sec"] <= duration
        assert hit["status"] == "uncertain" and hit["human_review"] is None
    assert "not calibrated probabilities" in result["note"]

    # 5. Open the actual recording (byte-range playback, as the browser player does).
    media = client.get(top["video_url"], headers={"Range": "bytes=0-1023"})
    assert media.status_code == 206 and len(media.data) == 1024

    # 6. Inspect frames inside the matched window, and the window's thumbnail.
    assert client.get(top["thumbnail_url"]).mimetype == "image/jpeg"
    frames = client.get(f"/api/videos/{top['video_id']}/frames").json["frames"]
    inside = [f for f in frames if top["start_sec"] <= f["timestamp_sec"] <= top["end_sec"]]
    assert inside and all(client.get(f["url"]).status_code == 200 for f in inside[:3])

    # 7. Record a human review decision; it shows on the next identical search.
    assert client.post("/api/feedback", headers=headers, json=dict(
        query="a red car", video_id=top["video_id"], start_sec=top["start_sec"], end_sec=top["end_sec"],
        search_mode="ranked", assessment="correct")).json == {"ok": True}
    again = client.post("/api/search", headers=headers, json={"query": "a red car"}).json["hits"][0]
    assert again["human_review"]["assessment"] == "correct" and again["status"] == "uncertain"

    # 8. Export review results.
    export = client.get("/api/feedback/export")
    rows = list(csv.DictReader(io.StringIO(export.text)))
    assert rows == [dict(rows[0], query="a red car", filename="cam2_carpark.mp4", start_sec="16.0",
                         end_sec="40.0", search_mode="ranked", assessment="correct")]

    # Searching never indexed or removed anything in the search engine.
    assert {c[0] for c in env.calls()} <= {"search", "stats"}
