"""Event timeline, YOLO presence lane, evidence provenance and review history, reports and search filters."""
import json
import os

import pytest

from tanya import event_index, person_detection
from tanya.config import SearchSettings
from tanya.web import create_app
from tests.conftest import make_video
from tests.test_event_index import ask, demo  # noqa: F401  (shared offline event-index fixture)


def yolo_result(sha, name="cam2_carpark.mp4", weights_sha="a" * 64, frames=100):
    dets = [{"frame": i, "t": i / 25, "boxes": ([[10, 20, 30, 60, 0.8], [40, 20, 60, 60, 0.5]] if i == 50 else
                                                [[10, 20, 30, 60, 0.6]]) if 25 <= i < 75 else []} for i in range(frames)]
    return {"format": person_detection.FORMAT, "kind": "person_detection",
            "video": {"name": name, "sha256": sha, "frames": frames, "fps": 25.0},
            "model": {"weights": "yolo26n.pt", "weights_sha256": weights_sha, "imgsz": 384, "min_conf": 0.1},
            "runner": {"device": "cpu"}, "detections": dets}


def vid(client, name):
    return next(v["id"] for v in client.get("/api/videos").json["videos"] if v["filename"] == name)


# ---------------------------------------------------------------- feature 1: event timeline


def test_timeline_lists_exact_labels_and_times_per_video(demo):
    client, _headers, _ws, _index, _page, _library = demo
    events = client.get(f"/api/videos/{vid(client, 'cam5_corridor.mp4')}/events").json
    assert events["index_available"] is True
    assert [(e["label"], e["start_sec"], e["end_sec"], e["source"]) for e in events["events"]] == [
        ("a person walking", 0.0, 2.0, "synthetic_script"), ("a person falling down", 2.0, 3.0, "synthetic_script"),
        ("a person lying on the floor", 3.0, 6.0, "synthetic_script")]
    fall = client.get(f"/api/videos/{vid(client, 'Rest_FallOnFloor.mp4')}/events").json["events"]
    assert {(e["category"], e["verification"]) for e in fall} == {("fallen", "provisional_single_reviewer"),
                                                                 ("person_present", "provisional_single_reviewer")}
    assert all("not independently verified" in e["status_label"] for e in fall)
    assert client.get("/api/videos/999/events").status_code == 404


def test_timeline_has_no_labels_outside_the_event_index(workspace):
    make_video(workspace.video_dir / "a.mp4", seconds=2)
    workspace.run()
    client = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "b.py")).test_client()
    data = client.get("/api/videos/1/events").json
    assert data == {"index_available": False, "events": [], "duration_sec": data["duration_sec"]}
    assert client.get("/api/search/filters").json == {"available": False}


def test_player_page_has_timeline_markup_and_seek_wiring(demo):
    client, *_ = demo
    page = client.get("/").data.decode()
    assert 'id="event-timeline-card"' in page and 'id="evt-playhead"' in page and "timeline.js" in page
    js = client.get("/static/timeline.js").data.decode()
    assert "bar.onclick = event => { event.stopPropagation(); timelineJump(item.start_sec, bar); }" in js
    assert "function timelineJump(t, button) {\n  seek(t);" in js.replace("\r\n", "\n")
    assert "jump.onclick = () => timelineJump(item.start_sec, jump);" in js and "Not an action or incident." in js


# ---------------------------------------------------------------- feature 2: YOLO lane and cache status


def test_presence_intervals_keep_the_peak_box_and_person_count():
    out = person_detection.presence_intervals(yolo_result("s" * 64)["detections"])
    assert len(out) == 1 and (out[0]["start_sec"], out[0]["end_sec"], out[0]["frames"]) == (1.0, 3.0, 50)
    assert out[0]["peak"] == {"frame": 50, "t": 2.0, "box": [10, 20, 30, 60], "conf": 0.8} and out[0]["max_people"] == 2


def test_cache_is_reused_when_hashes_match_and_marked_stale_otherwise(demo, tmp_path, monkeypatch):
    client, _headers, ws, _index, _page, library = demo
    sha = library["cam2_carpark.mp4"]
    weights = tmp_path / "w.pt"
    weights.write_bytes(b"model")
    real = person_detection.file_sha256(weights)
    person_detection.store(ws.settings(), yolo_result(sha, weights_sha=real), sha)
    config = person_detection.YoloConfig(None, weights, None)
    first = person_detection.load_cached(ws.settings(), sha, config)
    assert first["status"] == "cached" and first["weights_verified"] and not first["stale"]
    assert person_detection.load_cached(ws.settings(), sha, config) is first          # memoised, not re-parsed
    weights.write_bytes(b"another model")
    stale = person_detection.load_cached(ws.settings(), sha, config)
    assert stale["status"] == "stale" and stale["stale"]
    assert person_detection.load_cached(ws.settings(), sha)["status"] == "cached_unverified"   # nothing to compare


def test_yolo_lane_is_person_presence_only(demo):
    client, headers, ws, _index, _page, library = demo
    sha = library["cam2_carpark.mp4"]
    person_detection.store(ws.settings(), yolo_result(sha), sha)
    people = client.get(f"/api/videos/{vid(client, 'cam2_carpark.mp4')}/people").json["result"]
    assert people["intervals"][0]["peak"]["box"] == [10, 20, 30, 60] and "not a fall" in people["caution"]
    events = client.get(f"/api/videos/{vid(client, 'cam2_carpark.mp4')}/events").json["events"]
    assert all(e["source"] != "yolo_person" for e in events)          # labels and detections stay separate
    fall = ask(client, headers, "a person collapsed")
    assert all(h["event"]["source"] != "yolo_person" for h in fall["hits"])


# ---------------------------------------------------------------- feature 3: evidence provenance and review


def case(client, headers, title="Case"):
    return client.post("/api/investigations", headers=headers, json={"title": title}).json["id"]


def add_hit(client, headers, iid, hit, **extra):
    return client.post(f"/api/investigations/{iid}/evidence", headers=headers, json=dict(
        video_id=hit["video_id"], start_sec=hit["start_sec"], end_sec=hit["end_sec"], query="a person falling",
        search_mode="index", event_source=hit["event"]["source"], thumbnail=hit["thumbnail"], **extra))


def test_index_evidence_records_server_side_provenance_and_review_history(demo):
    client, headers, ws, _index, _page, _library = demo
    iid = case(client, headers)
    hit = ask(client, headers, "a person falling")["hits"][0]
    added = add_hit(client, headers, iid, hit, event={"label": "forged", "source": "provisional_review"})
    assert added.status_code == 201
    ev = added.json["evidence"][0]
    assert ev["search_mode"] == "index" and ev["event"]["label"] == "a person falling, then on the floor"
    assert ev["event"]["verification"] == "provisional_single_reviewer" and ev["best_score"] is None
    # A clip that matches no indexed event, or a client-chosen source, cannot claim provenance.
    bad = client.post(f"/api/investigations/{iid}/evidence", headers=headers, json=dict(
        video_id=hit["video_id"], start_sec=1, end_sec=2, query="x", search_mode="index", event_source="provisional_review"))
    assert bad.status_code == 400 and "provenance" in bad.json["error"]
    url = f"/api/investigations/{iid}/evidence/{ev['id']}/review"
    for decision in ("correct", "unsure"):
        assert client.post(url, headers=headers, json={"decision": decision}).status_code == 200
    assert client.post(url, headers=headers, json={"note": "Fall visible at 0:03."}).status_code == 200
    assert client.post(url, json={"decision": "wrong"}).status_code == 403                     # CSRF still required
    item = client.get(f"/api/investigations/{iid}").json["evidence"][0]
    assert (item["id"], item["decision"], item["note"]) == (ev["id"], "unsure", "Fall visible at 0:03.")
    assert [(h["action"], h["from"], h["to"]) for h in item["history"]] == [
        ("decision_recorded", None, "correct"), ("decision_changed", "correct", "unsure"),
        ("note_changed", "", "Fall visible at 0:03.")]
    assert item["event"]["label"] == "a person falling, then on the floor"


def test_yolo_evidence_is_a_model_candidate_with_detector_details(demo):
    client, headers, ws, _index, _page, library = demo
    sha = library["cam2_carpark.mp4"]
    person_detection.store(ws.settings(), yolo_result(sha), sha)
    iid = case(client, headers)
    hit = next(h for h in ask(client, headers, "a person")["hits"] if h["event"]["source"] == "yolo_person")
    ev = add_hit(client, headers, iid, hit).json["evidence"][0]
    assert ev["event"]["verification"] == "unreviewed_candidate"
    assert ev["event"]["detector"]["peak"]["box"] == [10, 20, 30, 60] and ev["event"]["detector"]["max_conf"] == 0.8


# ---------------------------------------------------------------- feature 4: reports


def report(client, headers, iid, fmt, **extra):
    r = client.post(f"/api/investigations/{iid}/report", headers=headers, json={"format": fmt, **extra})
    assert r.status_code == 200
    return r.json if fmt == "json" else r.data.decode()


def test_reports_carry_provenance_review_status_and_caveats(demo):
    client, headers, ws, _index, _page, library = demo
    sha = library["cam2_carpark.mp4"]
    person_detection.store(ws.settings(), yolo_result(sha), sha)
    iid = case(client, headers, "Lobby fall")
    fall = ask(client, headers, "a person falling")["hits"][0]
    yolo = next(h for h in ask(client, headers, "a person")["hits"] if h["event"]["source"] == "yolo_person")
    e1 = add_hit(client, headers, iid, fall).json["evidence"][0]["id"]
    add_hit(client, headers, iid, yolo)
    client.post(f"/api/investigations/{iid}/evidence/{e1}/review", headers=headers, json={"decision": "correct", "note": "Seen."})
    data = report(client, headers, iid, "json")
    assert data["report_version"] == 2 and data["report_options"] == {"frame_images_included": False}
    s = data["summary"]
    assert (s["human_confirmed"], s["unreviewed_candidate"], s["unresolved"]) == (1, 1, 1)
    assert s["by_source"] == {"provisional_review": 1, "yolo_person": 1}
    assert any("second independent review is pending" in c for c in data["label_caveats"])
    assert any("not a recognised action" in c for c in data["label_caveats"])
    by_label = {e["event"]["label"]: e for e in data["evidence"]}
    assert by_label["a person falling, then on the floor"]["review"]["history"][0]["to"] == "correct"
    assert by_label["a person detected in view"]["category"] == "unreviewed_candidate"
    html = report(client, headers, iid, "html")
    assert "Lobby fall" in html and "TanyaCCTV" in html and "data:image/png;base64," in html     # brand mark only
    assert "data:image/jpeg" not in html and "Frame images are not included" in html
    assert "reviewed by one person (provisional)" in html and "YOLO person detection (unreviewed candidate)" in html
    assert "A detector score, not the probability of an event." in html and "Decision history" in html
    assert "Human-confirmed (marked Correct)" in html and "@media print" in html


def test_reports_warn_about_missing_and_changed_index_sources(demo):
    client, headers, ws, _index, _page, _library = demo
    iid = case(client, headers)
    hits = ask(client, headers, "a person falling")["hits"]
    for h in hits[:2]:
        add_hit(client, headers, iid, h)
    corridor = ws.video_dir / "cam5_corridor.mp4"
    (ws.video_dir / "Rest_FallOnFloor.mp4").write_bytes(b"changed footage")    # same name, different bytes
    corridor.unlink()                                                          # gone from the library
    data = report(client, headers, iid, "json")
    assert (data["summary"]["missing_sources"], data["summary"]["changed_sources"]) == (1, 1)
    html = report(client, headers, iid, "html")
    assert "MISSING from the library" in html and "CHANGED: the file" in html


# ---------------------------------------------------------------- feature 5: filters


def search(client, headers, query, filters):
    return client.post("/api/search", headers=headers, json={"query": query, "filters": filters})


def test_filters_combine_with_the_query_and_never_add_false_matches(demo):
    client, headers, ws, _index, _page, library = demo
    person_detection.store(ws.settings(), yolo_result(library["cam2_carpark.mp4"]), library["cam2_carpark.mp4"])
    fall_id, corridor_id = vid(client, "Rest_FallOnFloor.mp4"), vid(client, "cam5_corridor.mp4")
    only_review = search(client, headers, "a person falling", {"sources": ["provisional_review"]}).json["hits"]
    assert [h["filename"] for h in only_review] == ["Rest_FallOnFloor.mp4"]
    one_video = search(client, headers, "a person falling", {"video_ids": [corridor_id]}).json["hits"]
    assert {h["filename"] for h in one_video} == {"cam5_corridor.mp4"}
    late = search(client, headers, "a person falling", {"start_sec": 3.9}).json["hits"]
    assert [(h["filename"], h["event"]["label"]) for h in late] == [("cam5_corridor.mp4", "a person lying on the floor")]
    status = search(client, headers, "all", {"statuses": ["scripted"], "event_types": ["vehicle"]}).json["hits"]
    assert [h["event"]["label"] for h in status] == ["a red car"]
    browse = search(client, headers, "", {"event_types": ["presence"]})
    assert browse.status_code == 400                                       # the API still needs a query
    presence = search(client, headers, "all", {"event_types": ["presence"]}).json["hits"]
    assert {h["event"]["source"] for h in presence} == {"provisional_review", "yolo_person"}
    strict = search(client, headers, "a person", {"sources": ["yolo_person"], "min_yolo_conf": 0.9}).json
    assert strict["hits"] == [] and any("not evidence of any action" in w for w in strict["warnings"])
    assert any("selected filters" in w for w in strict["warnings"])
    none = search(client, headers, "a person falling", {"video_ids": [vid(client, "cam2_carpark.mp4")]}).json
    assert none["hits"] == [] and none["applied_filters"]["video_ids"] == [vid(client, "cam2_carpark.mp4")]
    fight = search(client, headers, "two people fighting", {"event_types": ["presence"]}).json
    assert fight["hits"] == [] and any("no labels for fight" in w for w in fight["warnings"])
    assert fall_id != corridor_id


@pytest.mark.parametrize("bad", [{"sources": ["gemini"]}, {"event_types": "fall"}, {"video_ids": [0]},
                                 {"start_sec": 5, "end_sec": 2}, {"min_yolo_conf": 2}, {"colour": ["red"]},
                                 {"start_sec": float("nan")}, ["fall"]])
def test_invalid_filters_are_refused(demo, bad):
    client, headers, *_ = demo
    assert search(client, headers, "a person falling", bad).status_code == 400


def test_filter_options_only_list_values_present_in_the_library(demo):
    client, *_ = demo
    options = client.get("/api/search/filters").json
    assert options["available"] is True and options["yolo_available"] is False
    assert {o["value"] for o in options["sources"]} == {"provisional_review", "synthetic_script"}
    assert "fight" not in {o["value"] for o in options["event_types"]}
    assert {r["filename"] for r in options["recordings"]} == {"cam5_corridor.mp4", "cam2_carpark.mp4", "Rest_FallOnFloor.mp4"}


def test_saved_searches_keep_their_filters_and_work_without_gemini(demo, monkeypatch):
    client, headers, *_ = demo
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    iid = case(client, headers)
    r = client.post("/api/search", headers=headers, json={"query": "a person falling", "investigation_id": iid,
                                                          "filters": {"sources": ["synthetic_script"]}})
    assert r.status_code == 200 and len(r.json["hits"]) == 2      # the two scripted falls
    saved = client.get(f"/api/investigations/{iid}").json["queries"][0]
    assert saved["settings"]["filters"]["sources"] == ["synthetic_script"] and saved["settings"]["engine"].startswith("Preset")
    assert client.post("/api/search", json={"query": "a person falling", "filters": {}}).status_code == 403   # CSRF


def test_filters_are_refused_outside_the_event_index(workspace):
    make_video(workspace.video_dir / "a.mp4", seconds=2)
    workspace.run()
    app = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "b.py"))
    client = app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    r = client.post("/api/search", headers=headers, json={"query": "x", "filters": {"sources": ["yolo_person"]}})
    assert r.status_code == 400 and "event index only" in r.json["error"]
