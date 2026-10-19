"""Investigations: storage rules, audit history, timeline, source resolution and the web API."""

from __future__ import annotations

import json

import pytest

from tanya.config import SearchSettings
from tanya.investigations import (InvestigationError, NotFound, Store, StoreUnavailable, resolve_sources,
                                  timeline)
from tanya.search import Chunk, SearchHit, SearchResponse
from tanya.web import create_app
from tests.conftest import make_video

SHA_A, SHA_B = "a" * 64, "b" * 64


def clip(**kw):
    base = dict(video_sha256=SHA_A, video_filename="lobby.mp4", video_rel_path="lobby.mp4", video_duration_sec=60.0,
                start_sec=16.0, end_sec=42.0, query="a person walking", search_mode="ranked", rank=1,
                best_score=0.401, score_above_median=0.057, visual_verdict=None, visual_reason=None, thumbnail=None)
    base.update(kw)
    return base


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "investigations.db")


def actions(store, inv_id):
    return [a["action"] for a in store.audit(inv_id)]


# --------------------------------------------------------------------------- storage


def test_create_rename_list_and_audit(store):
    inv = store.create("Lobby incident", "Reported 14:00")
    assert inv["status"] == "open" and inv["evidence"] == [] and inv["queries"] == []
    store.update(inv["id"], title="Lobby incident, Monday")
    assert store.list()[0]["title"] == "Lobby incident, Monday"
    history = store.audit(inv["id"])
    assert [a["action"] for a in history] == ["created", "details_changed"]
    assert history[1]["detail"]["title"] == {"from": "Lobby incident", "to": "Lobby incident, Monday"}


@pytest.mark.parametrize("title", ["", "   ", "x" * 201, None, 5])
def test_invalid_titles_rejected(store, title):
    with pytest.raises(InvestigationError):
        store.create(title)


def test_closed_investigation_is_read_only_until_reopened(store):
    inv = store.create("Case")
    store.set_status(inv["id"], "closed")
    for change in (lambda: store.update(inv["id"], title="New"),
                   lambda: store.add_evidence(inv["id"], clip()),
                   lambda: store.save_query(inv["id"], "q", "ranked", {})):
        with pytest.raises(InvestigationError, match="closed"):
            change()
    store.set_status(inv["id"], "open")
    store.add_evidence(inv["id"], clip())
    assert actions(store, inv["id"]) == ["created", "closed", "reopened", "evidence_added"]


def test_saved_query_reruns_update_instead_of_duplicating(store):
    inv = store.create("Case")
    q1 = store.save_query(inv["id"], "a red car", "ranked", {"merge_ratio": 0.5}, result_count=4)
    q2 = store.save_query(inv["id"], "a red car", "ranked", {"merge_ratio": 0.5}, result_count=3)
    assert q1["id"] == q2["id"] and q2["last_result_count"] == 3
    store.save_query(inv["id"], "a red car", "visual", {"merge_ratio": 0.5})   # other mode = new query
    assert len(store.get(inv["id"])["queries"]) == 2
    assert actions(store, inv["id"]).count("query_run") == 1


@pytest.mark.parametrize("change, message", [
    (dict(end_sec=61.0), "inside the recording"), (dict(start_sec=10.0, end_sec=10.0), "inside the recording"),
    (dict(start_sec=float("nan")), "finite"), (dict(video_sha256="short"), "source video"),
    (dict(search_mode="auto"), "Search mode"), (dict(visual_verdict="confirmed"), "verdict"),
    (dict(rank=0), "rank"), (dict(query=""), "Query"),
])
def test_invalid_evidence_rejected(store, change, message):
    inv = store.create("Case")
    with pytest.raises(InvestigationError, match=message):
        store.add_evidence(inv["id"], clip(**change))
    assert store.get(inv["id"])["evidence"] == []


def test_duplicate_clip_rejected_but_allowed_after_removal(store):
    inv = store.create("Case")
    ev = store.add_evidence(inv["id"], clip())
    with pytest.raises(InvestigationError, match="already"):
        store.add_evidence(inv["id"], clip())
    store.remove_evidence(inv["id"], ev["id"], "duplicate of camera B")
    store.add_evidence(inv["id"], clip())
    data = store.get(inv["id"])
    assert len(data["evidence"]) == 1 and len(data["removed_evidence"]) == 1
    assert data["removed_evidence"][0]["removal_reason"] == "duplicate of camera B"


def test_reviews_are_never_silently_overwritten(store):
    inv = store.create("Case")
    ev = store.add_evidence(inv["id"], clip())
    store.review_evidence(inv["id"], ev["id"], decision="correct", note="Person enters at 0:18")
    store.review_evidence(inv["id"], ev["id"], decision="wrong")
    store.review_evidence(inv["id"], ev["id"], note="Shadow, not a person")
    history = [a for a in store.audit(inv["id"]) if a["action"] in ("decision_recorded", "decision_changed", "note_changed")]
    assert [(a["action"], a["detail"]["from"], a["detail"]["to"]) for a in history] == [
        ("decision_recorded", None, "correct"), ("note_changed", "", "Person enters at 0:18"),
        ("decision_changed", "correct", "wrong"), ("note_changed", "Person enters at 0:18", "Shadow, not a person")]
    final = store.get(inv["id"])["evidence"][0]
    assert final["decision"] == "wrong" and final["reviewed_at"]


@pytest.mark.parametrize("decision, note", [("confirmed", None), (None, None), (None, "x" * 2001), (None, 5)])
def test_invalid_reviews_rejected(store, decision, note):
    inv = store.create("Case")
    ev = store.add_evidence(inv["id"], clip())
    with pytest.raises(InvestigationError):
        store.review_evidence(inv["id"], ev["id"], decision=decision, note=note)


def test_unknown_ids_are_not_found(store):
    inv = store.create("Case")
    for call in (lambda: store.get(999), lambda: store.remove_evidence(inv["id"], 999),
                 lambda: store.review_evidence(inv["id"], 999, decision="wrong"),
                 lambda: store.remove_query(inv["id"], 999), lambda: store.get("1")):
        with pytest.raises(NotFound):
            call()


def test_recording_start_validation_and_audit(store):
    inv = store.create("Case")
    with pytest.raises(InvestigationError, match="local time"):
        store.set_recording_start(inv["id"], SHA_A, "2026-10-19T14:00:00+08:00")
    with pytest.raises(InvestigationError):
        store.set_recording_start(inv["id"], SHA_A, "yesterday")
    store.set_recording_start(inv["id"], SHA_A, "2026-10-19T14:00:00")
    store.set_recording_start(inv["id"], SHA_A, "")
    assert store.get(inv["id"])["recording_clocks"] == {}
    sets = [a["detail"] for a in store.audit(inv["id"]) if a["action"] == "recording_start_set"]
    assert [(d["from"], d["to"]) for d in sets] == [(None, "2026-10-19T14:00:00"), ("2026-10-19T14:00:00", None)]


def test_corrupt_store_fails_safely_and_is_left_unchanged(tmp_path):
    path = tmp_path / "investigations.db"
    path.write_bytes(b"not sqlite at all" * 64)
    before = path.read_bytes()
    with pytest.raises(StoreUnavailable, match="left unchanged"):
        Store(path).list()
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- timeline and sources


def test_timeline_orders_by_camera_time_across_recordings():
    items = [dict(id=1, video_sha256=SHA_A, video_filename="cam1.mp4", start_sec=50.0, end_sec=55.0),
             dict(id=2, video_sha256=SHA_B, video_filename="cam2.mp4", start_sec=10.0, end_sec=20.0),
             dict(id=3, video_sha256=SHA_A, video_filename="cam1.mp4", start_sec=5.0, end_sec=9.0)]
    ordered, basis = timeline(items, {SHA_A: "2026-10-19T14:00:00", SHA_B: "2026-10-19T14:00:30"})
    assert basis == "absolute" and [e["id"] for e in ordered] == [3, 2, 1]      # 14:00:05, 14:00:40, 14:00:50
    assert ordered[1]["absolute_start"] == "2026-10-19T14:00:40.000"
    ordered, basis = timeline(items, {})
    assert basis == "within_recording" and [e["id"] for e in ordered] == [3, 1, 2]
    ordered, basis = timeline(items, {SHA_B: "2026-10-19T09:00:00"})
    assert basis == "mixed" and [e["id"] for e in ordered] == [2, 3, 1]
    assert timeline([], {}) == ([], "empty")


def test_sources_available_renamed_or_missing(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "now_named.mp4").write_bytes(b"x")
    (videos / "lobby.mp4").write_bytes(b"x")
    library = {SHA_A: dict(id=7, rel_path="lobby.mp4", filename="lobby.mp4"),
               SHA_B: dict(id=8, rel_path="now_named.mp4", filename="now_named.mp4"),
               "c" * 64: dict(id=9, rel_path="deleted.mp4", filename="deleted.mp4")}
    ev = [dict(id=1, video_sha256=SHA_A, video_rel_path="lobby.mp4"),
          dict(id=2, video_sha256=SHA_B, video_rel_path="old_name.mp4"),
          dict(id=3, video_sha256="c" * 64, video_rel_path="deleted.mp4"),
          dict(id=4, video_sha256="d" * 64, video_rel_path="gone.mp4")]
    status = [(e["source_status"], e["current_video_id"]) for e in resolve_sources(ev, library, videos)]
    assert status == [("available", 7), ("renamed", 8), ("missing", None), ("missing", None)]
    assert ev[1]["video_rel_path"] == "old_name.mp4"                     # stored reference untouched


# --------------------------------------------------------------------------- web API


@pytest.fixture
def api(workspace, monkeypatch):
    make_video(workspace.video_dir / "lobby.mp4", seconds=20, seed=1)
    make_video(workspace.video_dir / "carpark.mp4", seconds=12, seed=2)
    workspace.run()
    app = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "bridge.py"))
    client = app.test_client()
    client.get("/")
    with client.session_transaction() as s:
        headers = {"X-CSRF-Token": s["csrf"]}
    videos = {v["filename"]: v for v in workspace.videos()}
    lobby_frame = workspace.frames(videos["lobby.mp4"]["id"])[5]["image_path"]
    hits = [SearchHit(videos["lobby.mp4"]["id"], "lobby.mp4", "lobby.mp4", 4.0, 14.0, .41, .09,
                      [Chunk(1, 4.0, 14.0, .41, .09)], thumbnail=lobby_frame),
            SearchHit(videos["carpark.mp4"]["id"], "carpark.mp4", "carpark.mp4", 0.0, 10.0, .30, .01,
                      [Chunk(2, 0.0, 10.0, .30, .01)])]
    monkeypatch.setattr("tanya.web.search_videos", lambda q, *a: SearchResponse(q, list(hits)))

    def post(url, payload=None, expect=200):
        response = client.post(url, headers=headers, json=payload or {})
        assert response.status_code == expect, response.json
        return response.json
    return client, post, workspace, videos


def add_hit(post, inv_id, hit, **extra):
    return post(f"/api/investigations/{inv_id}/evidence", dict(
        video_id=hit["video_id"], start_sec=hit["start_sec"], end_sec=hit["end_sec"], query="a person walking",
        search_mode="ranked", rank=1, best_score=hit["best_score"],
        score_above_median=hit["best_score_above_median"], thumbnail=hit["thumbnail"], **extra), expect=201)


def test_investigation_workflow_through_the_api(api):
    client, post, ws, videos = api
    inv = post("/api/investigations", {"title": "Lobby, Monday"}, expect=201)
    iid = inv["id"]

    result = post("/api/search", {"query": "a person walking", "investigation_id": iid})
    assert result["saved_query"]["query"] == "a person walking"
    assert result["saved_query"]["settings"]["chunks_requested"] == 10 and result["saved_query"]["last_result_count"] == 2
    hit = result["hits"][0]

    view = add_hit(post, iid, hit, video_sha256="f" * 64)        # a client-sent hash is ignored
    ev = view["evidence"][0]
    assert ev["video_sha256"] == ws.rows("SELECT sha256 FROM videos WHERE filename='lobby.mp4'")[0][0]
    assert ev["source_status"] == "available" and client.get(ev["video_url"]).status_code == 200
    assert client.get(ev["thumbnail_url"]).mimetype == "image/jpeg"

    view = post(f"/api/investigations/{iid}/evidence/{ev['id']}/review", {"decision": "correct", "note": "Enters at 0:06"})
    assert view["evidence"][0]["decision"] == "correct" and view["evidence"][0]["note"] == "Enters at 0:06"
    again = post("/api/search", {"query": "a person walking"})["hits"][0]
    assert again["human_review"]["assessment"] == "correct" and again["status"] == "uncertain"   # mirrored, display only

    second = add_hit(post, iid, result["hits"][1])["evidence"]
    car = next(e for e in second if e["video_filename"] == "carpark.mp4")
    lobby_sha = ev["video_sha256"]
    view = post(f"/api/investigations/{iid}/clock", {"video_sha256": car["video_sha256"], "recorded_start": "2026-10-19T09:00:00"})
    view = post(f"/api/investigations/{iid}/clock", {"video_sha256": lobby_sha, "recorded_start": "2026-10-19T08:59:58"})
    assert view["timeline_basis"] == "absolute"
    assert [e["video_filename"] for e in view["evidence"]] == ["carpark.mp4", "lobby.mp4"]   # 09:00:00 before 09:00:02
    assert {r["filename"] for r in view["recordings"]} == {"lobby.mp4", "carpark.mp4"}

    view = post(f"/api/investigations/{iid}/evidence/{car['id']}/remove", {"reason": "empty car park"})
    assert [e["video_filename"] for e in view["evidence"]] == ["lobby.mp4"] and len(view["removed_evidence"]) == 1

    actions = [a["action"] for a in client.get(f"/api/investigations/{iid}/audit").json["audit"]]
    assert actions == ["created", "query_saved", "evidence_added", "decision_recorded", "note_changed",
                       "evidence_added", "recording_start_set", "recording_start_set", "evidence_removed"]


def test_untrusted_thumbnail_and_bad_video_are_rejected(api):
    _, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    car_frame = ws.frames(videos["carpark.mp4"]["id"])[0]["image_path"]
    view = post(f"/api/investigations/{iid}/evidence", dict(
        video_id=videos["lobby.mp4"]["id"], start_sec=0, end_sec=5, query="q", search_mode="ranked",
        thumbnail=car_frame), expect=201)                          # a frame of another video
    assert view["evidence"][0]["thumbnail"] is None
    post(f"/api/investigations/{iid}/evidence", dict(video_id=999, start_sec=0, end_sec=5, query="q",
                                                     search_mode="ranked"), expect=404)
    post(f"/api/investigations/{iid}/evidence", dict(video_id=videos["lobby.mp4"]["id"], start_sec=0,
                                                     end_sec=999, query="q", search_mode="ranked"), expect=400)


def test_every_change_needs_the_csrf_token(api):
    client, post, _, _ = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    for url in ("/api/investigations", f"/api/investigations/{iid}", f"/api/investigations/{iid}/status",
                f"/api/investigations/{iid}/evidence", f"/api/investigations/{iid}/clock",
                f"/api/investigations/{iid}/report", f"/api/investigations/{iid}/evidence/1/review"):
        assert client.post(url, json={"title": "x", "format": "html"}).status_code == 403, url
    for method in (client.put, client.patch, client.delete):
        assert method(f"/api/investigations/{iid}").status_code == 403
    assert client.get(f"/api/investigations/{iid}/report").status_code == 405


def test_missing_and_renamed_sources_are_flagged_not_dropped(api):
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    for name in ("lobby.mp4", "carpark.mp4"):
        post(f"/api/investigations/{iid}/evidence", dict(video_id=videos[name]["id"], start_sec=0, end_sec=5,
                                                         query="q", search_mode="ranked"), expect=201)
    (ws.video_dir / "lobby.mp4").rename(ws.video_dir / "lobby_renamed.mp4")
    (ws.video_dir / "carpark.mp4").unlink()
    ws.run()                                                    # library now: renamed lobby, no car park
    view = client.get(f"/api/investigations/{iid}").json
    status = {e["video_filename"]: (e["source_status"], e["video_url"] is not None) for e in view["evidence"]}
    assert status == {"lobby.mp4": ("renamed", True), "carpark.mp4": ("missing", False)}
    report = post(f"/api/investigations/{iid}/report", {"format": "json"})
    assert report["summary"]["missing_sources"] == 1
    missing = next(e for e in report["evidence"] if e["source"]["status"] == "missing")
    assert missing["source"]["filename_when_added"] == "carpark.mp4" and len(missing["source"]["video_sha256"]) == 64


def _token(client):
    with client.session_transaction() as s:
        return s["csrf"]


def test_reports_separate_human_decisions_and_escape_content(api):
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "<script>alert(1)</script> case"}, expect=201)["id"]
    lobby = videos["lobby.mp4"]["id"]
    frame = ws.frames(lobby)[3]["image_path"]
    ids = []
    for start in (0, 5, 10, 15):
        view = post(f"/api/investigations/{iid}/evidence", dict(video_id=lobby, start_sec=start, end_sec=start + 4,
                                                                query="<b>q</b>", search_mode="ranked",
                                                                best_score=.4, thumbnail=frame), expect=201)
        ids = [e["id"] for e in view["evidence"]]
    for ev_id, decision in zip(ids, ("correct", "wrong", "unsure")):
        post(f"/api/investigations/{iid}/evidence/{ev_id}/review", {"decision": decision, "note": "<img src=x>"})

    headers = {"X-CSRF-Token": _token(client)}
    raw = client.post(f"/api/investigations/{iid}/report", headers=headers, json={"format": "json"})
    assert raw.status_code == 200 and "attachment" in raw.headers["Content-Disposition"]
    report = json.loads(raw.data)
    assert (report["summary"]["human_confirmed"], report["summary"]["rejected_by_reviewer"],
            report["summary"]["unsure"], report["summary"]["unreviewed_candidate"]) == (1, 1, 1, 1)
    assert [e["category"] for e in report["evidence"]] == ["human_confirmed", "rejected_by_reviewer", "unsure",
                                                           "unreviewed_candidate"]
    assert all(e["source"]["video_sha256"] and e["window"]["end_sec"] for e in report["evidence"])
    assert any("not calibrated probabilities" in line for line in report["limitations"])

    html = client.post(f"/api/investigations/{iid}/report", headers=headers, json={"format": "html"}).data.decode()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<img src=x>" not in html and "<b>q</b>" not in html
    assert "data:image/jpeg;base64," in html and "Human-confirmed" in html and "not a probability" in html
    exports = [a for a in client.get(f"/api/investigations/{iid}/audit").json["audit"] if a["action"] == "report_exported"]
    assert [a["detail"]["format"] for a in exports] == ["json", "html"]


def test_search_still_works_when_investigation_is_closed(api):
    _, post, _, _ = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    post(f"/api/investigations/{iid}/status", {"status": "closed"})
    result = post("/api/search", {"query": "a person walking", "investigation_id": iid})
    assert result["hits"] and "not saved to the investigation" in result["warnings"][0]
    post(f"/api/investigations/{iid}", {"title": "Renamed"}, expect=400)


def test_corrupt_investigations_file_returns_503_and_rest_of_app_works(api):
    client, post, ws, _ = api
    path = ws.db_path.with_name("investigations.db")
    path.write_bytes(b"garbage" * 100)
    before = path.read_bytes()
    response = client.get("/api/investigations")
    assert response.status_code == 503 and "left unchanged" in response.json["error"]
    assert client.get("/api/videos").status_code == 200
    assert path.read_bytes() == before
    result = post("/api/search", {"query": "a person walking", "investigation_id": 1})
    assert result["hits"] and "not saved" in result["warnings"][0]


# --------------------------------------------------------------------------- Phase 8: integrity


def test_database_refuses_to_rewrite_history(store):
    import sqlite3
    inv = store.create("Case")
    ev = store.add_evidence(inv["id"], clip())
    store.review_evidence(inv["id"], ev["id"], decision="correct")       # allowed: decision/note/removal fields
    conn = sqlite3.connect(store.path)
    try:
        for sql in ("UPDATE audit_log SET action='edited'", "DELETE FROM audit_log",
                    "DELETE FROM evidence", "UPDATE evidence SET video_sha256='" + "e" * 64 + "'",
                    "UPDATE evidence SET start_sec=0", "UPDATE evidence SET query='other'"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)
    finally:
        conn.close()
    assert actions(store, inv["id"]) == ["created", "evidence_added", "decision_recorded"]
    assert store.get(inv["id"])["evidence"][0]["video_sha256"] == SHA_A


def test_export_verifies_source_content_and_flags_changed_files(api):
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    for name in ("lobby.mp4", "carpark.mp4"):
        post(f"/api/investigations/{iid}/evidence", dict(video_id=videos[name]["id"], start_sec=0, end_sec=4,
                                                         query="q", search_mode="ranked"), expect=201)
    report = post(f"/api/investigations/{iid}/report", {"format": "json"})
    assert {e["source"]["content_verified_at_export"] for e in report["evidence"]} == {True}
    assert report["summary"]["changed_sources"] == 0

    tampered = ws.video_dir / "carpark.mp4"                      # modified after it was referenced, not re-indexed
    tampered.write_bytes(tampered.read_bytes() + b"\x00edited")
    report = post(f"/api/investigations/{iid}/report", {"format": "json"})
    status = {e["source"]["filename_when_added"]: (e["source"]["status"], e["source"]["content_verified_at_export"])
              for e in report["evidence"]}
    assert status == {"lobby.mp4": ("available", True), "carpark.mp4": ("changed", False)}
    assert report["summary"]["changed_sources"] == 1
    client_html = client.post(f"/api/investigations/{iid}/report", headers={"X-CSRF-Token": _token(client)},
                              json={"format": "html"}).data.decode()
    assert "CHANGED: the file" in client_html and "content verified against the hash at export" in client_html


def test_each_source_file_is_hashed_once(tmp_path):
    from tanya.investigations import verify_sources
    (tmp_path / "a.mp4").write_bytes(b"x")
    calls = []
    items = [dict(id=i, video_sha256=SHA_A, source_status="available", current_rel_path="a.mp4") for i in range(3)]
    out = verify_sources(items, tmp_path, lambda p: calls.append(p) or SHA_A)
    assert len(calls) == 1 and all(e["content_verified"] for e in out)
    gone = verify_sources([dict(id=9, video_sha256=SHA_A, source_status="missing", current_rel_path=None)],
                          tmp_path, lambda p: pytest.fail("missing sources are not hashed"))
    assert gone[0]["source_status"] == "missing" and gone[0]["content_verified"] is False


def test_review_still_saved_when_search_review_file_is_corrupt(api):
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    ev = post(f"/api/investigations/{iid}/evidence", dict(video_id=videos["lobby.mp4"]["id"], start_sec=0, end_sec=4,
                                                         query="q", search_mode="ranked"), expect=201)["evidence"][0]
    feedback_file = ws.db_path.with_name("search_feedback.db")
    feedback_file.write_bytes(b"corrupt" * 100)
    before = feedback_file.read_bytes()
    view = post(f"/api/investigations/{iid}/evidence/{ev['id']}/review", {"decision": "correct"})
    assert view["evidence"][0]["decision"] == "correct" and "could not be updated" in view["warning"]
    assert feedback_file.read_bytes() == before


def test_missing_thumbnail_file_does_not_break_the_report(api):
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    lobby = videos["lobby.mp4"]["id"]
    frame = ws.frames(lobby)[1]["image_path"]
    post(f"/api/investigations/{iid}/evidence", dict(video_id=lobby, start_sec=0, end_sec=4, query="q",
                                                     search_mode="ranked", thumbnail=frame), expect=201)
    (ws.frames_dir / frame).unlink()
    html = client.post(f"/api/investigations/{iid}/report", headers={"X-CSRF-Token": _token(client)},
                       json={"format": "html"})
    assert html.status_code == 200 and "frame image unavailable" in html.data.decode()


@pytest.mark.parametrize("thumbnail", [["x"], {"a": 1}, 5, True, ""])
def test_non_string_thumbnail_is_dropped_not_a_server_error(api, thumbnail):
    """Regression: a list/object thumbnail reached SQLite and caused a 500."""
    _, post, _, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    view = post(f"/api/investigations/{iid}/evidence", dict(video_id=videos["lobby.mp4"]["id"], start_sec=0, end_sec=4,
                                                            query="q", search_mode="ranked", thumbnail=thumbnail), expect=201)
    assert view["evidence"][0]["thumbnail"] is None


def test_manual_moment_from_player_is_labelled_and_not_mirrored(api):
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    view = post(f"/api/investigations/{iid}/evidence", dict(video_id=videos["lobby.mp4"]["id"], start_sec=5, end_sec=15,
                                                            query="Moment chosen in the video player",
                                                            search_mode="manual"), expect=201)
    ev = view["evidence"][0]
    assert ev["search_mode"] == "manual" and ev["rank"] is None and ev["best_score"] is None
    post(f"/api/investigations/{iid}/evidence/{ev['id']}/review", {"decision": "correct"})
    assert not ws.db_path.with_name("search_feedback.db").exists()          # not mirrored into search reviews
    report = post(f"/api/investigations/{iid}/report", {"format": "json"})
    assert report["evidence"][0]["found_by"]["search_mode"] == "manual"
    html = client.post(f"/api/investigations/{iid}/report", headers={"X-CSRF-Token": _token(client)},
                       json={"format": "html"}).data.decode()
    assert "chosen manually in the video player (not a search result)" in html
    post(f"/api/investigations/{iid}/evidence", dict(video_id=videos["lobby.mp4"]["id"], start_sec=0, end_sec=2,
                                                     query="q", search_mode="automatic"), expect=400)


def test_footage_scan_clip_keeps_its_own_provenance(api):
    """A direct footage-scan window is not a similarity ranking: no rank/score, labelled as a scan."""
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    lobby = videos["lobby.mp4"]["id"]
    post(f"/api/investigations/{iid}/evidence", dict(video_id=lobby, start_sec=0, end_sec=4, query="a person walking",
                                                     search_mode="scan", rank=1), expect=400)
    view = post(f"/api/investigations/{iid}/evidence", dict(video_id=lobby, start_sec=0, end_sec=4,
                                                            query="a person walking", search_mode="scan",
                                                            visual_verdict="supported",
                                                            visual_reason="mock reason"), expect=201)
    ev = view["evidence"][0]
    assert ev["search_mode"] == "scan" and ev["rank"] is None and ev["best_score"] is None
    post(f"/api/investigations/{iid}/evidence/{ev['id']}/review", {"decision": "correct"})
    assert not ws.db_path.with_name("search_feedback.db").exists()          # not mirrored into ranked reviews
    report = post(f"/api/investigations/{iid}/report", {"format": "json"})
    found = report["evidence"][0]["found_by"]
    assert found["search_mode"] == "scan" and found["rank"] is None
    html = client.post(f"/api/investigations/{iid}/report", headers={"X-CSRF-Token": _token(client)},
                       json={"format": "html"}).data.decode()
    assert "direct footage scan for" in html and "not a similarity ranking" in html and "rank 1" not in html


def test_changed_or_missing_source_is_flagged_in_the_app_not_only_at_export(api):
    """Before: an altered recording showed "Source available" and played without warning until export."""
    client, post, ws, videos = api
    iid = post("/api/investigations", {"title": "Case"}, expect=201)["id"]
    for name in ("lobby.mp4", "carpark.mp4"):
        post(f"/api/investigations/{iid}/evidence", dict(video_id=videos[name]["id"], start_sec=0, end_sec=4,
                                                         query="q", search_mode="ranked"), expect=201)
    with open(ws.video_dir / "lobby.mp4", "ab") as f:                     # altered after indexing
        f.write(b"tampered")
    (ws.video_dir / "carpark.mp4").unlink()                                  # removed after indexing
    status = {e["video_filename"]: e["source_status"] for e in client.get(f"/api/investigations/{iid}").json["evidence"]}
    assert status == {"lobby.mp4": "changed", "carpark.mp4": "missing"}
    lobby = videos["lobby.mp4"]["id"]
    info = client.get(f"/api/videos/{lobby}/playback").json
    assert info["changed"] is True and "changed since it was indexed" in info["changed_message"]
    listed = {v["filename"]: v["playback"] for v in client.get("/api/videos").json["videos"]}
    assert listed["lobby.mp4"]["changed"] is True and listed["carpark.mp4"]["status"] == "missing"
    report = post(f"/api/investigations/{iid}/report", {"format": "json"})       # export still re-hashes
    assert report["summary"]["changed_sources"] == 1 and report["summary"]["missing_sources"] == 1


def test_unchanged_source_is_not_flagged(api):
    client, post, ws, videos = api
    info = client.get(f"/api/videos/{videos['lobby.mp4']['id']}/playback").json
    assert info["changed"] is False and info["changed_message"] is None
