"""Web integration tests using isolated videos and the existing search result model."""
from io import BytesIO

import pytest

from tanya.config import SearchSettings
from tanya.search import SearchResponse, SearchHit, Chunk
from tanya.web import create_app
from tests.conftest import junction_or_skip, make_video, symlink_or_skip


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
    symlink_or_skip(ws.video_dir / "inside.mp4", outside)
    assert client.get(f'/media/videos/{video["id"]}').status_code == 404


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
    assert client.get("/api/videos").json == {"videos": [], "waiting_files": [], "unsupported_files": []}
    assert client.get("/api/videos/999/frames").status_code == 404
    assert client.get("/media/videos/999").status_code == 404
    assert client.get("/media/playback/999").status_code == 404
    assert client.get("/api/videos/999/playback").status_code == 404
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


def test_feedback_persists_updates_and_exports_without_changing_index(web):
    import csv
    from io import StringIO
    from tanya.web import create_app
    client, headers, ws = web
    assert len(list(csv.reader(StringIO(client.get('/api/feedback/export').text)))) == 1
    make_video(ws.video_dir / 'camera.mp4', seconds=3)
    ws.run()
    video = ws.videos()[0]
    original = ws.db_path.read_bytes()
    review = dict(query='=HYPERLINK("bad")', video_id=video['id'], start_sec=0, end_sec=3,
                  search_mode='visual', assessment='correct')
    assert client.post('/api/feedback', json=review).status_code == 403
    assert client.post('/api/feedback', headers=headers, json=review).json == {'ok': True}
    review['assessment'] = 'wrong'
    assert client.post('/api/feedback', headers=headers, json=review).status_code == 200
    # A new app instance still sees the saved review, with updates replacing duplicates.
    other = create_app(ws.settings(), SearchSettings(None, ws.video_dir / 'bridge.py')).test_client()
    response = other.get('/api/feedback/export')
    records = list(csv.DictReader(StringIO(response.text)))
    assert len(records) == 1 and records[0]['assessment'] == 'wrong'
    assert records[0]['query'].startswith("'=")
    assert records[0]['filename'] == 'camera.mp4'
    assert 'attachment' in response.headers['Content-Disposition']
    assert ws.db_path.read_bytes() == original


@pytest.mark.parametrize('change', [dict(query=''), dict(query=[]), dict(assessment=[]),
    dict(assessment='confirmed'), dict(search_mode='other'), dict(video_id=True),
    dict(start_sec=-1), dict(end_sec=99), dict(start_sec=2, end_sec=1),
    dict(start_sec=float('nan')), dict(end_sec=float('inf'))])
def test_invalid_feedback_is_not_saved(web, change):
    client, headers, ws = web
    make_video(ws.video_dir / 'camera.mp4', seconds=3)
    ws.run()
    review = dict(query='person', video_id=ws.videos()[0]['id'], start_sec=0, end_sec=3,
                  search_mode='visual', assessment='unsure')
    review.update(change)
    assert client.post('/api/feedback', headers=headers, json=review).status_code == 400
    assert not ws.db_path.with_name('search_feedback.db').exists()


# --------------------------------------------------------------------------- non-Latin upload names


@pytest.mark.parametrize("original, expected", [
    ("监控录像.mp4", "video.mp4"),            # regression: was rejected ("mp4" had no extension)
    ("கண்காணிப்பு.MOV", "video.mov"),          # Tamil
    ("كاميرا.avi", "video.avi"),               # Arabic
    ("カメラ1.MOV", "1.MOV"),                  # some ASCII survives: keep it
    ("lobby cam.mp4", "lobby_cam.mp4"),
    ("../../监控.mp4", "video.mp4"),           # directories are never kept
    (r"..\..\camera.m4v", "camera.m4v"),
    ("C:evil.mkv", "Cevil.mkv"),
    ("clip.mp4.", "clip.mp4"),                 # Windows drops trailing dots
])
def test_safe_upload_name_keeps_allowed_extension(original, expected):
    from tanya.web import safe_upload_name
    assert safe_upload_name(original) == expected


@pytest.mark.parametrize("original", [
    "", ".mp4", "监控录像", "监控录像.exe", "clip.mp4.exe", "clip.mp4\x00.exe", "clip.html", "../.mp4", "clip.",
])
def test_safe_upload_name_still_rejects_disallowed_types(original):
    from tanya.web import safe_upload_name
    assert safe_upload_name(original) is None


def test_non_latin_upload_is_accepted_indexed_and_never_overwrites(web, tmp_path):
    client, headers, ws = web
    source = make_video(tmp_path / "source.mp4", seconds=2)
    names = []
    for _ in range(2):  # same name twice: second upload must not replace the first
        response = client.post("/api/upload", headers=headers, data={
            "authorized": "yes", "video": (BytesIO(source.read_bytes()), "监控录像.mp4")})
        assert response.status_code == 201, response.json
        names.append(response.json["filename"])
    assert names[0] != names[1] and all(n.endswith("_video.mp4") for n in names)
    assert sorted(p.name for p in ws.video_dir.iterdir()) == sorted(names)   # nothing outside or extra
    assert all((ws.video_dir / n).read_bytes() == source.read_bytes() for n in names)  # neither replaced
    assert client.post("/api/index", headers=headers).status_code == 200
    # Identical content is indexed once (Milestone 1 de-duplicates by SHA-256); frames are extracted.
    videos = client.get("/api/videos").json["videos"]
    assert len(videos) == 1 and videos[0]["filename"] in names and videos[0]["frame_count"] == 2


def test_non_latin_name_with_disallowed_extension_is_rejected(web):
    client, headers, ws = web
    response = client.post("/api/upload", headers=headers, data={
        "authorized": "yes", "video": (BytesIO(b"MZ"), "监控录像.exe")})
    assert response.status_code == 400 and not list(ws.video_dir.iterdir())


# --------------------------------------------------------------------------- outside paths (Windows-runnable)
# The symlink test above is skipped on Windows without Developer Mode. These tests exercise the same
# confinement (media_path: resolve() + is_relative_to) through database paths and, on Windows,
# directory junctions, which need no special privilege. Each first proves the legitimate path works.


def _set(ws, sql, params):
    import sqlite3
    conn = sqlite3.connect(ws.db_path)
    with conn:
        conn.execute(sql, params)
    conn.close()


def test_video_db_path_outside_video_folder_is_not_served(web, tmp_path):
    client, _, ws = web
    make_video(ws.video_dir / "inside.mp4")
    outside = make_video(tmp_path / "outside.mp4", seed=9)        # exists, so a 404 is not "missing file"
    ws.run()
    video_id = ws.videos()[0]["id"]
    assert client.get(f"/media/videos/{video_id}").status_code == 200   # control
    for rel in ("../outside.mp4", str(outside), str(outside).replace("\\", "/")):
        _set(ws, "UPDATE videos SET rel_path = ? WHERE id = ?", (rel, video_id))
        assert (ws.video_dir / rel).resolve().is_file()                # the target really exists
        assert client.get(f"/media/videos/{video_id}").status_code == 404, rel


def test_frame_db_path_outside_frames_folder_is_not_served(web, tmp_path):
    client, _, ws = web
    make_video(ws.video_dir / "inside.mp4", seconds=2)
    ws.run()
    video_id = ws.videos()[0]["id"]
    good = client.get("/api/videos").json["videos"][0]["thumbnail_url"]
    assert client.get(good).status_code == 200                          # control
    private = tmp_path / "private.jpg"                                  # a real JPEG outside frames/
    private.write_bytes(next(ws.frames_dir.rglob("*.jpg")).read_bytes())
    for rel in ("../private.jpg", str(private).replace("\\", "/")):
        _set(ws, "UPDATE frames SET image_path = ? WHERE video_id = ?", (rel, video_id))
        thumb = client.get("/api/videos").json["videos"][0]["thumbnail_url"]
        listed = client.get(f"/api/videos/{video_id}/frames").json["frames"]
        assert client.get(thumb).status_code == 404, rel
        assert all(client.get(f["url"]).status_code == 404 for f in listed), rel
    assert client.get("/media/frames/../../README.md").status_code == 404
    assert client.get("/media/frames/..%2f..%2fprivate.jpg").status_code == 404


def test_video_and_frames_behind_a_junction_are_not_served(web, tmp_path):
    """Genuine link escape on Windows without admin rights: a junction inside the allowed folder."""
    client, _, ws = web
    make_video(ws.video_dir / "inside.mp4", seconds=2)
    ws.run()
    video_id = ws.videos()[0]["id"]
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    make_video(outside_dir / "outside.mp4", seed=9)
    (outside_dir / "private.jpg").write_bytes(next(ws.frames_dir.rglob("*.jpg")).read_bytes())
    junction_or_skip(ws.video_dir / "linked", outside_dir)
    junction_or_skip(ws.frames_dir / "linked", outside_dir)
    assert (ws.video_dir / "linked" / "outside.mp4").is_file()          # the junction really works

    _set(ws, "UPDATE videos SET rel_path = ? WHERE id = ?", ("linked/outside.mp4", video_id))
    assert client.get(f"/media/videos/{video_id}").status_code == 404
    assert client.get("/media/frames/linked/private.jpg").status_code == 404


# --------------------------------------------------------------------------- duplicate uploads


def test_identical_upload_of_indexed_video_is_not_stored_twice(web, tmp_path):
    client, headers, ws = web
    source = make_video(tmp_path / "source.mp4", seconds=2)
    first = client.post("/api/upload", headers=headers, data={
        "authorized": "yes", "video": (BytesIO(source.read_bytes()), "lobby.mp4")})
    assert first.status_code == 201
    assert client.post("/api/index", headers=headers).status_code == 200
    stored = ws.video_dir / first.json["filename"]
    original = stored.read_bytes()

    again = client.post("/api/upload", headers=headers, data={
        "authorized": "yes", "video": (BytesIO(source.read_bytes()), "renamed copy.mp4")})
    assert again.status_code == 200
    assert again.json == {"filename": None, "duplicate_of": first.json["filename"]}
    assert [p.name for p in ws.video_dir.iterdir()] == [first.json["filename"]]   # no second copy
    assert stored.read_bytes() == original                                       # existing file untouched

    different = make_video(tmp_path / "other.mp4", seconds=2, seed=7)
    response = client.post("/api/upload", headers=headers, data={
        "authorized": "yes", "video": (BytesIO(different.read_bytes()), "lobby.mp4")})
    assert response.status_code == 201 and len(list(ws.video_dir.iterdir())) == 2


# --------------------------------------------------------------------------- earlier human reviews on results


@pytest.fixture
def reviewed_search(web, monkeypatch):
    client, headers, ws = web
    make_video(ws.video_dir / "camera.mp4", seconds=6)
    ws.run()
    video = ws.videos()[0]
    hits = [SearchHit(video["id"], "camera.mp4", "camera.mp4", 0, 3, .41, .1, [Chunk(1, 0, 3, .41, .1)]),
            SearchHit(video["id"], "camera.mp4", "camera.mp4", 3, 6, .33, .02, [Chunk(2, 3, 6, .33, .02)])]
    monkeypatch.setattr("tanya.web.search_videos", lambda q, *a: SearchResponse(q, [h for h in hits]))

    def search(query="person", **extra):
        response = client.post("/api/search", headers=headers, json={"query": query, **extra})
        assert response.status_code == 200
        return response.json["hits"]

    def review(assessment, start=0, end=3, query="person", mode="ranked"):
        assert client.post("/api/feedback", headers=headers, json=dict(
            query=query, video_id=video["id"], start_sec=start, end_sec=end,
            search_mode=mode, assessment=assessment)).status_code == 200
    return search, review


def test_results_start_unreviewed_and_show_the_earlier_review(reviewed_search):
    search, review = reviewed_search
    assert [h["human_review"] for h in search()] == [None, None]
    review("wrong")
    first, second = search()
    assert first["human_review"]["assessment"] == "wrong" and first["human_review"]["reviewed_at"]
    assert second["human_review"] is None                                  # a different window
    review("correct")                                                      # changing it updates
    assert search()[0]["human_review"]["assessment"] == "correct"


def test_reviews_do_not_leak_across_queries_or_modes(reviewed_search):
    search, review = reviewed_search
    review("correct")
    assert search("a different query")[0]["human_review"] is None
    review("unsure", mode="visual")
    assert search()[0]["human_review"]["assessment"] == "correct"          # ranked mode unchanged


def test_reviews_never_change_ranking_scores_or_status(reviewed_search):
    search, review = reviewed_search
    before = [(h["start_sec"], h["best_score"], h["status"]) for h in search()]
    review("wrong")
    review("correct", start=3, end=6)
    after = search()
    assert [(h["start_sec"], h["best_score"], h["status"]) for h in after] == before
    assert {h["status"] for h in after} == {"uncertain"}


def test_unreadable_review_file_does_not_break_search(reviewed_search, web):
    search, _ = reviewed_search
    _, _, ws = web
    (ws.db_path.with_name("search_feedback.db")).write_bytes(b"not a database" * 50)
    assert [h["human_review"] for h in search()] == [None, None]


def test_each_server_process_identifies_itself_so_a_page_can_detect_a_restart(web):
    """An open page compares this id with the one it was rendered with; after a restart (e.g. switching to the
    offline demo on the same port) the same video id may name other footage, so the page must not reuse it."""
    client, _headers, ws = web
    page = client.get("/")
    served = page.headers["X-TanyaCCTV-Instance"]
    assert f'<meta name="tanya-instance" content="{served}">' in page.text
    assert client.get("/api/videos").headers["X-TanyaCCTV-Instance"] == served          # same process: same id
    assert client.get("/api/missing").headers["X-TanyaCCTV-Instance"] == served          # errors carry it too
    other = create_app(ws.settings(), SearchSettings(None, ws.video_dir / "bridge.py")).test_client()
    assert other.get("/api/videos").headers["X-TanyaCCTV-Instance"] != served             # restarted process


def test_dashboard_explains_an_unreachable_or_restarted_server_instead_of_failed_to_fetch():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "tanya" / "static"
    dashboard = (root / "dashboard.js").read_text(encoding="utf-8")
    investigations = (root / "investigations.js").read_text(encoding="utf-8")
    assert "catch(e){ throw new Error(SERVER_GONE); }" in dashboard
    assert 'served!==instance) throw new Error(SERVER_CHANGED)' in dashboard
    # Every request goes through serverFetch, so none can surface the browser's bare "Failed to fetch".
    assert dashboard.count("fetch(") == 1 and "fetch(" not in investigations
