"""Web integration tests using isolated videos and the existing search result model."""
from io import BytesIO

import pytest

from tanya.config import SearchSettings
from tanya.search import SearchResponse, SearchHit, Chunk
from tanya.web import create_app
from tests.conftest import make_video


@pytest.fixture
def web(workspace):
    app = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "bridge.py"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf"]
    return client, {"X-CSRF-Token": token}, workspace


def test_upload_index_browse_and_range_playback(web, tmp_path):
    client, headers, ws = web
    source = make_video(tmp_path / "source.mp4", seconds=2)
    response = client.post("/api/upload", headers=headers, data={
        "authorized": "yes", "video": (BytesIO(source.read_bytes()), "../../camera.mp4")})
    assert response.status_code == 201
    assert "/" not in response.json["filename"]
    original = next(ws.video_dir.glob("*.mp4")).read_bytes()
    assert client.post("/api/index", headers=headers).status_code == 200
    videos = client.get("/api/videos").json["videos"]
    assert len(videos) == 1 and videos[0]["frame_count"] == 2
    frames = client.get(f'/api/videos/{videos[0]["id"]}/frames').json["frames"]
    assert len(frames) == 2
    assert client.get(frames[0]["url"]).mimetype == "image/jpeg"
    media = client.get(videos[0]["video_url"], headers={"Range": "bytes=0-9"})
    assert media.status_code == 206 and len(media.data) == 10
    assert next(ws.video_dir.glob("*.mp4")).read_bytes() == original


def test_upload_requires_permission_valid_type_and_csrf(web):
    client, headers, ws = web
    assert client.post("/api/index").status_code == 403
    assert client.post("/api/upload", headers=headers, data={
        "video": (BytesIO(b"video"), "camera.mp4")}).status_code == 400
    assert client.post("/api/upload", headers=headers, data={
        "authorized": "yes", "video": (BytesIO(b"script"), "attack.html")}).status_code == 400
    assert not list(ws.video_dir.iterdir())
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_media_cannot_escape_video_folder(web, tmp_path):
    client, _, ws = web
    outside = make_video(tmp_path / "outside.mp4")
    make_video(ws.video_dir / "inside.mp4")
    ws.run()
    video = ws.videos()[0]
    (ws.video_dir / "inside.mp4").unlink()
    (ws.video_dir / "inside.mp4").symlink_to(outside)
    assert client.get(f'/media/videos/{video["id"]}').status_code == 404
    assert client.get("/media/frames/../../README.md").status_code == 404


def test_search_validation_unconfigured_and_translated_media_urls(web, monkeypatch):
    client, headers, ws = web
    assert client.post("/api/search", headers=headers, json={"query": []}).status_code == 400
    make_video(ws.video_dir / "camera.mp4")
    ws.run()
    assert client.post("/api/search", headers=headers, json={"query": "person"}).status_code == 503
    video = ws.videos()[0]
    frame = ws.frames(video["id"])[0]
    hit = SearchHit(video["id"], "camera.mp4", "camera.mp4", 0, 2, .4, .1,
                    [Chunk(1, 0, 2, .4, .1)], thumbnail=frame["image_path"])
    monkeypatch.setattr("tanya.web.search_videos", lambda *a: SearchResponse("person", [hit]))
    response = client.post("/api/search", headers=headers, json={"query": "person"})
    assert response.status_code == 200
    assert response.json["hits"][0]["status"] == "uncertain"
    assert client.get(response.json["hits"][0]["thumbnail_url"]).status_code == 200
    assert "not calibrated probabilities" in response.json["note"]


def test_empty_library_and_missing_media(web):
    client, _, _ = web
    assert client.get("/api/videos").json == {"videos": []}
    assert client.get("/api/videos/999/frames").status_code == 404
    assert client.get("/media/videos/999").status_code == 404
    assert not client.get("/api/status").json["search_ready"]


def test_duplicate_filenames_never_overwrite_originals(web):
    client, headers, ws = web
    for payload in (b"first", b"second"):
        response = client.post("/api/upload", headers=headers, data={
            "authorized": "yes", "video": (BytesIO(payload), "camera.mp4")})
        assert response.status_code == 201
    assert sorted(p.read_bytes() for p in ws.video_dir.iterdir()) == [b"first", b"second"]


def test_ai_sync_needs_consent_and_a_current_plan(web, monkeypatch):
    client, headers, ws = web
    make_video(ws.video_dir / "camera.mp4")
    ws.run()
    monkeypatch.setattr("tanya.web.sentry_client.stats", lambda *a: {"source_files": []})
    applied = []
    monkeypatch.setattr("tanya.web.sentry_cli_command", lambda *a: ["fake-cli"])
    monkeypatch.setattr("tanya.web.apply_plan", lambda *a, **kw: applied.append(a[0]) or True)
    assert client.post("/api/search/sync", headers=headers, json={}).status_code == 400
    assert client.post("/api/search/sync", headers=headers, json={"confirmed": True}).status_code == 409
    plan = client.post("/api/search/plan", headers=headers)
    assert plan.status_code == 200 and plan.json["to_index"] == ["camera.mp4"]
    # A video added since the reviewed plan forces the user to review again.
    make_video(ws.video_dir / "new.mp4", seed=2)
    ws.run()
    assert client.post("/api/search/sync", headers=headers, json={"confirmed": True}).status_code == 409
    client.post("/api/search/plan", headers=headers)
    assert client.post("/api/search/sync", headers=headers, json={"confirmed": True}).json["ok"]
    assert len(applied) == 1 and len(applied[0].to_index) == 2
    assert client.post("/api/search/sync", headers=headers, json={"confirmed": True}).status_code == 409


def test_readiness_distinguishes_frames_from_ai_preparation(web):
    from tanya.search_sync import save_manifest
    client, _, ws = web
    make_video(ws.video_dir / "prepared.mp4")
    make_video(ws.video_dir / "pending.mp4", seed=2)
    make_video(ws.video_dir / "unsupported.avi", seed=3)
    (ws.video_dir / "broken.mp4").write_bytes(b"not a video")
    ws.run()
    prepared = next(v for v in ws.videos() if v["filename"] == "prepared.mp4")
    source = str(ws.video_dir / "prepared.mp4")
    save_manifest(ws.settings(), {source: {"sha256": prepared["sha256"]}})
    states = {v["filename"]: v["search_state"] for v in client.get("/api/videos").json["videos"]}
    assert states == {"prepared.mp4": "prepared", "pending.mp4": "needs_preparation",
                      "unsupported.avi": "unsupported", "broken.mp4": "local_index_needed"}
    coverage = client.get("/api/status").json["coverage"]
    assert coverage["prepared"] == ["prepared.mp4"]
    assert coverage["needs_preparation"] == ["pending.mp4"]
    # Old embeddings must not be presented as preparation of changed footage.
    save_manifest(ws.settings(), {source: {"sha256": "old-content"}})
    assert client.get("/api/status").json["coverage"]["prepared"] == []


def test_search_warns_that_new_uploads_are_missing_from_ai_search(web, monkeypatch):
    client, headers, ws = web
    make_video(ws.video_dir / "new_upload.mp4")
    ws.run()
    monkeypatch.setattr("tanya.web.search_videos", lambda *a: SearchResponse("person", []))
    response = client.post("/api/search", headers=headers, json={"query": "person"})
    assert response.status_code == 200
    assert response.json["coverage"]["needs_preparation"] == ["new_upload.mp4"]
    assert "new_upload.mp4" in response.json["warnings"][0]
    assert "Review the AI indexing plan" in response.json["warnings"][0]


def test_visual_search_requires_specific_consent_before_any_query(web, monkeypatch):
    client, headers, ws = web
    def forbidden(*args):
        pytest.fail("No search or image request is allowed before consent")
    monkeypatch.setattr("tanya.web.search_videos", forbidden)
    for data in ({"query": "black shirt", "visual_check": True},
                 {"query": "black shirt", "visual_check": True, "approve_frame_upload": "yes"},
                 {"query": "black shirt", "visual_check": "true"}):
        assert client.post("/api/search", headers=headers, json=data).status_code == 400


def test_visual_search_failure_does_not_fall_back_to_ranked_matches(web, monkeypatch):
    from tanya.sentry_client import SearchError
    client, headers, ws = web
    monkeypatch.setattr("tanya.web.search_videos", lambda *args: SearchResponse("black shirt", []))
    def failed(*args):
        raise SearchError("Visual checker unavailable")
    monkeypatch.setattr("tanya.web.review_results", failed)
    response = client.post("/api/search", headers=headers,
                           json={"query": "black shirt", "visual_check": True, "approve_frame_upload": True})
    assert response.status_code == 503 and "hits" not in response.json


def test_visual_search_samples_and_serves_all_review_groups(web, monkeypatch):
    """Exercise route -> real frame sampler -> validated decisions -> playable media."""
    client, headers, ws = web
    make_video(ws.video_dir / "camera.mp4", seconds=8)
    ws.run()
    video = ws.videos()[0]
    frame = ws.frames(video["id"])[0]
    hits = [SearchHit(video["id"], "camera.mp4", "camera.mp4", 0, 8, .4, .1,
                      [Chunk(i + 1, 0, 8, .4, .1)], thumbnail=frame["image_path"])
            for i in range(3)]
    monkeypatch.setattr("tanya.web.search_videos", lambda *args: SearchResponse("clothing", hits))
    calls = []
    def reviewer(payload, settings):
        calls.append(payload)
        assert len(payload["candidates"]) == 3
        assert all(len(c["frames"]) == 6 for c in payload["candidates"])
        return [dict(id=c["id"], verdict=verdict, reason="Test evidence.",
                     evidence_timestamps=[c["frames"][0]["timestamp_sec"]] if verdict == "supported" else [])
                for c, verdict in zip(payload["candidates"], ["supported", "unclear", "not_supported"])]
    monkeypatch.setattr("tanya.visual_review.run_review", reviewer)
    response = client.post("/api/search", headers=headers, json={
        "query": "clothing", "visual_check": True, "approve_frame_upload": True})
    assert response.status_code == 200 and len(calls) == 1
    result = response.json
    assert result["visual_review"] == dict(checked_candidates=3, sampled_frames=18,
                                           supported=1, unclear=1, rejected=1)
    for group in ("hits", "unclear_hits", "rejected_hits"):
        assert len(result[group]) == 1
        hit = result[group][0]
        assert hit["status"] == "uncertain"
        assert client.get(hit["thumbnail_url"]).status_code == 200
        assert client.get(hit["video_url"], headers={"Range": "bytes=0-9"}).status_code == 206
