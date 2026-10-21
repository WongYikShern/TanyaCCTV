"""Preset offline event index and optional YOLO person candidates: offline, honest, bound to footage hashes."""
import json

import pytest

from tanya import event_index, person_detection
from tanya.config import SearchSettings
from tanya.event_index import EventIndexSearch, Query
from tanya.web import create_app
from tests.conftest import make_video

SCENES = {"cam5_corridor.mp4": (6, [("a person walking", 0, 2), ("a person falling down", 2, 3),
                                    ("a person lying on the floor", 3, 6)]),
          "cam2_carpark.mp4": (4, [("a red car", 1, 3)])}


def caviar_labels(path, sha, verification="provisional_single_reviewer"):
    path.write_text(json.dumps({
        "verification": verification, "attribution": "EC Funded CAVIAR project/IST 2001 37540",
        "clips": [{"video": "Rest_FallOnFloor.mp4", "video_sha256": sha, "purpose": "staged fall"},
                  {"video": "Other.mp4", "video_sha256": "0" * 64, "purpose": "entry/exit, corridor view"}],
        "events": {"fallen": [{"video": "Rest_FallOnFloor.mp4", "start_sec": 2.2, "end_sec": 3.8,
                               "verification": verification}],
                   "person_present": [{"video": "Rest_FallOnFloor.mp4", "start_sec": 0.0, "end_sec": 5.0}],
                   "shop_enter": [{"video": "Other.mp4", "start_sec": 1.0, "end_sec": 1.5}]},
        "rejected_events": [{"video": "Rest_FallOnFloor.mp4", "category": "fallen", "start_sec": 4.0, "end_sec": 4.5}]}),
        encoding="utf-8")
    return path


@pytest.fixture
def demo(workspace, tmp_path, monkeypatch):
    # Never pick up a real local YOLO set-up: a different real weights file would (correctly) mark results stale.
    monkeypatch.setenv("TANYA_YOLO_HOME", str(tmp_path / "no-yolo"))
    monkeypatch.setenv("TANYA_YOLO_PYTHON", str(tmp_path / "missing-python"))
    monkeypatch.setenv("TANYA_YOLO_WEIGHTS", str(tmp_path / "missing.pt"))
    for name, (seconds, _) in SCENES.items():
        make_video(workspace.video_dir / name, seconds=seconds)
    make_video(workspace.video_dir / "Rest_FallOnFloor.mp4", seconds=5, seed=3)
    workspace.run()
    library = {v["filename"]: v["sha256"] for v in workspace.videos()}
    labels = caviar_labels(tmp_path / "labels.json", library["Rest_FallOnFloor.mp4"])
    index_path = tmp_path / "event-index.json"
    index = event_index.build(index_path, library=library, scenes=SCENES, caviar_events=labels)
    search = EventIndexSearch(index_path, person_detection.load_config())
    app = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "bridge.py"), offline_search=search)
    client = app.test_client()
    page = client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    return client, headers, workspace, index, page, library


def ask(client, headers, query):
    r = client.post("/api/search", headers=headers, json={"query": query})
    assert r.status_code == 200, r.json
    return r.json


def test_query_parsing_uses_explicit_synonyms_and_filters():
    q = Query.parse("Someone collapsed on the floor in the corridor after 0:20")
    assert q.concepts == {"person", "fall"} and q.views == {"corridor"} and q.after == 20
    assert Query.parse("a blue car between 10 and 20 seconds").colours == {"blue"}
    assert Query.parse("between 10 and 20 seconds").after == 10
    assert Query.parse("two people fighting").unsupported == ["fight"]
    assert Query.parse("a person walking").actions == {"walk"}


def test_index_only_binds_labels_to_footage_with_the_labelled_hash(demo):
    _client, _headers, _ws, index, _page, _library = demo
    videos = {e["video"] for e in index["entries"]}
    assert videos == {"cam5_corridor.mp4", "cam2_carpark.mp4", "Rest_FallOnFloor.mp4"}
    assert any("Other.mp4: not in the demo library" in n for n in index["notes"])
    assert index["caviar"]["verification"] == "provisional_single_reviewer"


def test_fall_query_returns_annotated_events_with_sources_and_exact_times(demo):
    client, headers, _ws, _index, page, _library = demo
    assert b"OFFLINE DEMO" in page.data and b"preset event index" in page.data
    data = ask(client, headers, "a person falling")
    sources = [h["event"]["source"] for h in data["hits"]]
    assert sources == ["provisional_review", "synthetic_script", "synthetic_script"]     # reviewed labels first
    first = data["hits"][0]
    assert (first["filename"], first["start_sec"], first["end_sec"]) == ("Rest_FallOnFloor.mp4", 2.2, 3.8)
    assert first["event"]["context_start_sec"] == 0.2 and first["event"]["context_end_sec"] == 5.0   # clipped to video
    assert "not independently verified" in first["event"]["provenance"]
    assert first["best_score"] is None and first["video_url"] and not first["event"]["needs_human_review"]
    assert any("rejected by the reviewer" in w for w in data["warnings"])
    assert any("never used as fall results" in w for w in data["warnings"])


def test_colour_view_time_and_no_match_are_handled_honestly(demo):
    client, headers, _ws, _index, _page, _library = demo
    assert [h["filename"] for h in ask(client, headers, "a red car")["hits"]] == ["cam2_carpark.mp4"]
    assert ask(client, headers, "a blue car")["hits"] == []
    corridor = ask(client, headers, "a person walking in the corridor")["hits"]
    assert [(h["filename"], h["event"]["label"]) for h in corridor] == [("cam5_corridor.mp4", "a person walking")]
    late = ask(client, headers, "a person lying on the floor after 4 s")["hits"]      # the CAVIAR fall ends at 3.8 s
    assert [(h["filename"], h["event"]["label"]) for h in late] == [("cam5_corridor.mp4", "a person lying on the floor")]
    fight = ask(client, headers, "two people fighting")
    assert fight["hits"] == [] and any("no labels for fight" in w for w in fight["warnings"])
    assert any("does not prove" in w for w in fight["warnings"])
    assert not any("not prepared for current AI search" in w for w in fight["warnings"])


def test_yolo_candidates_are_person_presence_only_and_bound_to_the_video(demo, tmp_path):
    client, headers, ws, _index, _page, library = demo
    sha = library["cam2_carpark.mp4"]
    frames = [{"frame": i, "t": i / 25, "boxes": [[1, 2, 3, 4, 0.8]] if 25 <= i < 75 else []} for i in range(100)]
    good = {"format": person_detection.FORMAT, "kind": "person_detection", "video": {"name": "cam2_carpark.mp4",
            "sha256": sha, "frames": 100, "fps": 25.0}, "model": {"weights": "w.pt", "weights_sha256": "a" * 64,
            "imgsz": 384, "min_conf": 0.1}, "runner": {"device": "cpu"}, "detections": frames}
    person_detection.store(ws.settings(), good, sha)
    with pytest.raises(person_detection.PersonDetectionError, match="different footage"):
        person_detection.store(ws.settings(), dict(good, video=dict(good["video"], sha256="f" * 64)), sha)
    hits = ask(client, headers, "a person")["hits"]
    yolo = [h for h in hits if h["event"]["source"] == "yolo_person"]
    assert [(h["filename"], h["start_sec"], h["end_sec"]) for h in yolo] == [("cam2_carpark.mp4", 1.0, 3.0)]
    assert yolo[0]["event"]["needs_human_review"] and yolo[0]["event"]["detector"]["max_conf"] == 0.8
    assert any(h["event"]["source"] == "provisional_review" for h in hits)            # annotated presence too
    assert ("cam5_corridor.mp4", 0.0, 2.0) in [(h["filename"], h["start_sec"], h["end_sec"]) for h in hits]   # scripted person
    assert [h["event"]["source"] for h in ask(client, headers, "a person in the car park")["hits"]] == ["yolo_person"]
    assert all(h["event"]["source"] != "yolo_person" for h in ask(client, headers, "a person falling")["hits"])
    vid = next(v["id"] for v in client.get("/api/videos").json["videos"] if v["filename"] == "cam2_carpark.mp4")
    people = client.get(f"/api/videos/{vid}/people").json
    assert people["available"] is False and people["result"]["intervals"][0]["frames"] == 50
    assert client.post(f"/api/videos/{vid}/people", headers=headers).status_code == 503   # not set up: never runs


def test_presence_intervals_merge_short_gaps_and_drop_blips():
    frames = [{"frame": i, "t": i / 25, "boxes": [[0, 0, 1, 1, 0.9 if i not in (10, 11) else 0.2]]} for i in range(30)]
    frames += [{"frame": 30 + i, "t": (30 + i) / 25, "boxes": []} for i in range(30)]
    frames += [{"frame": 60, "t": 2.4, "boxes": [[0, 0, 1, 1, 0.95]]}]
    out = person_detection.presence_intervals(frames)
    assert [(i["start_sec"], i["end_sec"], i["frames"]) for i in out] == [(0.0, 1.2, 28)]   # gap merged, 1-frame blip dropped


def test_saved_experiment_runs_are_reused_only_when_bound_by_the_media_manifest(workspace, tmp_path):
    run = tmp_path / "results-384"
    run.mkdir()
    (run / "results.json").write_text(json.dumps({"environment": {"weights": "yolo26n.pt", "imgsz": 384,
        "conf_recorded": 0.1, "inference_device": "cuda:0"}, "totals": {"network_attempts_blocked": 0},
        "clips": [{"video": "Walk1.mp4", "frames": 3}]}), encoding="utf-8")
    (run / "Walk1_detections.json").write_text(json.dumps(
        [{"frame": i, "t": i / 25, "boxes": []} for i in range(3)]), encoding="utf-8")
    settings = workspace.settings()
    assert person_detection.import_saved_run(settings, run, "Walk1.mp4", "a" * 64, "b" * 64) is None   # other bytes
    assert person_detection.import_saved_run(settings, run, "Walk1.mp4", "a" * 64, None) is None
    saved = person_detection.import_saved_run(settings, run, "Walk1.mp4", "a" * 64, "a" * 64)
    cached = person_detection.load_cached(settings, "a" * 64)
    assert saved.is_file() and cached["model"]["weights_sha256"] is None and "cannot be verified" in cached["provenance"]
