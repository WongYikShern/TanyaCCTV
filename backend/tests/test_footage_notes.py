"""Pre-analysed footage notes: word and synonym matching, binding to recordings by hash, and the API."""
import json
from pathlib import Path

import pytest

from tanya import footage_notes
from tanya.config import SearchSettings
from tanya.web import create_app
from tests.conftest import make_video

NOTES = [
    {"sha256": "a" * 64, "start_sec": 27, "end_sec": 42, "description": "Theft: a man loads a motorbike onto a ute.",
     "tags": ["steal", "night"], "box": {"timestamp": 30, "box_2d": [330, 560, 880, 760], "label": "man loading motorbike"}},
    {"sha256": "a" * 64, "start_sec": 9, "end_sec": 12, "description": "A man walks into the garage.", "tags": ["enter"]},
    {"sha256": "b" * 64, "start_sec": 0, "end_sec": 8, "description": "A red bag is left alone on the floor.", "tags": ["unattended"]},
]
LIBRARY = {"a" * 64: {"id": 1}, "b" * 64: {"id": 2}}


@pytest.mark.parametrize("query,expected", [
    ("a man stealing a motorbike", ["Theft"]), ("someone robbing a motorcycle", ["Theft"]),
    ("luggage left behind", ["A red bag"]), ("missing item", ["A red bag"]), ("a red car", []), ("", [])])
def test_every_word_must_match_directly_or_by_synonym(query, expected):
    found = [n["description"] for n, _ in footage_notes.search(NOTES, query, LIBRARY)]
    assert [d for d in found if any(d.startswith(e) for e in expected)] == found and len(found) == len(expected)


def test_notes_for_recordings_not_in_the_library_are_ignored():
    assert footage_notes.search(NOTES, "bag", {"a" * 64: {"id": 1}}) == []


def test_api_returns_preanalysed_hits_with_box_and_frame(workspace):
    make_video(workspace.video_dir / "garage.mp4", seconds=12)
    workspace.run()
    sha = workspace.videos()[0]["sha256"]
    notes = [dict(NOTES[0], sha256=sha, start_sec=2, end_sec=6, box=dict(NOTES[0]["box"], timestamp=4))]
    workspace.settings().db_path.with_name("footage_notes.json").write_text(json.dumps({"notes": notes}), encoding="utf-8")
    app = create_app(workspace.settings(), SearchSettings(None, Path("unused")))
    app.config["TESTING"] = True
    client = app.test_client(); client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    assert client.post("/api/search/notes", json={"query": "theft"}).status_code == 403
    hit = client.post("/api/search/notes", headers=headers, json={"query": "a man stealing a motorbike"}).json["hits"][0]
    assert hit["preanalysed"] and (hit["start_sec"], hit["end_sec"]) == (2, 6)
    box = hit["visual_review"]["evidence_boxes"][0]
    assert box["box_2d"] == [330, 560, 880, 760] and box["frame_url"].startswith("/media/frames/")
    assert client.post("/api/search/notes", headers=headers, json={"query": "a red car"}).json["hits"] == []
    assert client.post("/api/search/notes", headers=headers, json={"query": ""}).status_code == 400
