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


def test_documented_investigation_workflow(demo):
    """docs/demo.md, part 2: investigation, evidence timeline, decisions and the report."""
    client, headers, env = demo
    client.post("/api/index", headers=headers)
    sha = dict(env.ws.rows("SELECT rel_path, sha256 FROM videos"))
    search_sync.save_manifest(env.settings, {env.source(r): {"sha256": h} for r, h in sha.items()})

    def post(url, payload, expect=200):
        r = client.post(url, headers=headers, json=payload)
        assert r.status_code == expect, r.get_json()
        return r

    # Create an investigation and search with it selected: queries are saved with their settings.
    iid = post("/api/investigations", {"title": "Lobby and car park, Monday"}, 201).json["id"]
    car = post("/api/search", {"query": "a red car", "investigation_id": iid}).json
    walk = post("/api/search", {"query": "a person walking", "investigation_id": iid}).json
    assert car["saved_query"]["settings"]["merge_ratio"] == 0.5

    # Add the top candidate of each search; references come from the server's records.
    for result in (car, walk):
        hit = result["hits"][0]
        post(f"/api/investigations/{iid}/evidence", dict(
            video_id=hit["video_id"], start_sec=hit["start_sec"], end_sec=hit["end_sec"], query=result["query"],
            search_mode="ranked", rank=1, best_score=hit["best_score"],
            score_above_median=hit["best_score_above_median"], thumbnail=hit["thumbnail"]), 201)

    # Arrange by camera time: car park camera started 10 s after the lobby camera.
    post(f"/api/investigations/{iid}/clock", {"video_sha256": sha["cam1_lobby.mp4"], "recorded_start": "2026-10-19T08:59:50"})
    view = post(f"/api/investigations/{iid}/clock", {"video_sha256": sha["cam2_carpark.mp4"],
                                                     "recorded_start": "2026-10-19T09:00:00"}).json
    assert view["timeline_basis"] == "absolute"
    assert [(e["video_filename"], e["absolute_start"]) for e in view["evidence"]] == [
        ("cam1_lobby.mp4", "2026-10-19T09:00:06.000"), ("cam2_carpark.mp4", "2026-10-19T09:00:16.000")]

    # Inspect the footage and record decisions with notes.
    lobby, carpark = view["evidence"]
    assert client.get(lobby["video_url"], headers={"Range": "bytes=0-99"}).status_code == 206
    post(f"/api/investigations/{iid}/evidence/{carpark['id']}/review", {"decision": "correct", "note": "Red car enters at about 0:20."})
    post(f"/api/investigations/{iid}/evidence/{lobby['id']}/review", {"decision": "unsure", "note": "Person partly hidden."})

    # Export: categories, verified sources, camera times and the full history.
    report = post(f"/api/investigations/{iid}/report", {"format": "json"}).get_json()
    assert (report["summary"]["human_confirmed"], report["summary"]["unsure"], report["summary"]["unreviewed_candidate"]) == (1, 1, 0)
    assert all(e["source"]["content_verified_at_export"] for e in report["evidence"])
    assert [e["window"]["absolute_start"] for e in report["evidence"]] == ["2026-10-19T09:00:06.000", "2026-10-19T09:00:16.000"]
    assert [a["action"] for a in report["audit_log"]][:3] == ["created", "query_saved", "query_saved"]
    html = post(f"/api/investigations/{iid}/report", {"format": "html"}).data.decode()
    assert "Human-confirmed (marked Correct)" in html and "Reviewer unsure" in html and "Red car enters" in html
    assert {c[0] for c in env.calls()} <= {"search", "stats"}            # nothing indexed or removed
