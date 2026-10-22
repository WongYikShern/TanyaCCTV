"""AI incident summary: approval, offline refusal, and exactly which text facts would be sent. No network."""
from pathlib import Path

import pytest

from tanya import incident_summary
from tanya.config import SearchSettings
from tanya.web import create_app
from tests.conftest import make_video


@pytest.fixture
def case(workspace, monkeypatch):
    make_video(workspace.video_dir / "lobby.mp4", seconds=12)
    workspace.run()
    sent = []
    monkeypatch.setattr(incident_summary, "run_summary", lambda payload, settings: sent.append(payload) or "Draft summary.")
    app = create_app(workspace.settings(), SearchSettings(None, Path("unused")))
    app.config["TESTING"] = True
    client = app.test_client(); client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    video = client.get("/api/videos").json["videos"][0]
    client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"name": "Lobby", "place": "Ground floor"})
    inv = client.post("/api/investigations", headers=headers, json={"title": "Missing bag"}).json
    return client, headers, video, inv, sent


def add(client, headers, inv, video, start, decision=None, note=None):
    view = client.post(f"/api/investigations/{inv['id']}/evidence", headers=headers, json=dict(
        video_id=video["id"], start_sec=start, end_sec=start + 4, query="person with a bag", search_mode="manual",
        rank=None, best_score=None)).json
    ev = max(view["evidence"], key=lambda e: e["id"])   # the timeline is sorted by time, not by id
    if decision or note:
        client.post(f"/api/investigations/{inv['id']}/evidence/{ev['id']}/review", headers=headers,
                    json={k: v for k, v in (("decision", decision), ("note", note)) if v})
    return ev


def test_requires_approval_and_at_least_one_clip(case):
    client, headers, video, inv, sent = case
    url = f"/api/investigations/{inv['id']}/summary"
    assert client.post(url, headers=headers, json={}).status_code == 400
    assert client.post(url, headers=headers, json={"approve_text_upload": True}).status_code == 400
    assert client.post(url, json={"approve_text_upload": True}).status_code == 403
    assert sent == []


def test_sends_only_text_facts_and_returns_a_draft_without_saving(case):
    client, headers, video, inv, sent = case
    add(client, headers, inv, video, 6, decision="wrong")
    add(client, headers, inv, video, 1, decision="correct", note="enters from the left")
    response = client.post(f"/api/investigations/{inv['id']}/summary", headers=headers, json={"approve_text_upload": True})
    assert response.status_code == 200 and response.json == {"summary": "Draft summary.", "facts": 2}
    facts = sent[0]["facts"]
    assert sent[0]["title"] == "Missing bag"
    assert [f["time_in_recording"] for f in facts] == ["0:01-0:05", "0:06-0:10"]
    assert facts[0] == {"camera": "Lobby", "place": "Ground floor", "time_in_recording": "0:01-0:05",
                        "human_decision": "relevant", "found_by": "chosen manually", "investigator_note": "enters from the left"}
    assert facts[1]["human_decision"] == "not relevant"
    assert "jpeg" not in str(sent) and "image_path" not in str(sent)
    # Drafting never changes the case.
    assert client.get(f"/api/investigations/{inv['id']}").json["description"] == ""


def test_offline_demo_refuses(workspace, monkeypatch):
    monkeypatch.setattr(incident_summary, "run_summary", lambda *a: pytest.fail("must not send"))
    class Offline:
        mode = "replay"
    app = create_app(workspace.settings(), SearchSettings(None, Path("unused")), offline_search=Offline())
    app.config["TESTING"] = True
    client = app.test_client(); client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    assert client.post("/api/investigations/1/summary", headers=headers, json={"approve_text_upload": True}).status_code == 403
