"""Camera names and map locations: validation, persistence by content hash, and CSRF protection."""
import pytest

from tanya.config import SearchSettings
from tanya.web import create_app
from tests.conftest import make_video


@pytest.fixture
def web(workspace):
    make_video(workspace.video_dir / "gate.mp4", seconds=2)
    workspace.run()
    app = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "bridge.py"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        token = session["csrf"]
    video = client.get("/api/videos").json["videos"][0]
    return client, {"X-CSRF-Token": token}, video, workspace


def test_name_place_and_location_are_saved_and_listed(web):
    client, headers, video, _ = web
    assert video["camera"] == {}
    saved = client.post(f"/api/videos/{video['id']}/camera", headers=headers,
                        json={"name": "  Front   gate ", "place": "Block A", "lat": 3.1478, "lng": 101.7139})
    assert saved.status_code == 200
    assert saved.json["camera"] == {"name": "Front gate", "place": "Block A", "lat": 3.1478, "lng": 101.7139}
    listed = client.get("/api/videos").json["videos"][0]["camera"]
    assert listed == saved.json["camera"]
    # Updating only the name keeps the location.
    client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"name": "Main gate"})
    assert client.get("/api/videos").json["videos"][0]["camera"]["lat"] == 3.1478


def test_hidden_flag_is_saved_and_cleared(web):
    client, headers, video, _ = web
    assert client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"hidden": True}).json["camera"] == {"hidden": True}
    assert client.get("/api/videos").json["videos"][0]["camera"] == {"hidden": True}
    client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"hidden": False})
    assert client.get("/api/videos").json["videos"][0]["camera"] == {}
    assert client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"hidden": "yes"}).status_code == 400


def test_clearing_every_field_removes_the_entry(web):
    client, headers, video, ws = web
    client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"name": "Lobby", "lat": 1, "lng": 2})
    client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"name": "", "lat": None, "lng": None})
    assert client.get("/api/videos").json["videos"][0]["camera"] == {}


@pytest.mark.parametrize("payload", [
    {"lat": 91, "lng": 0}, {"lat": 0, "lng": 181}, {"lat": 1}, {"lat": "3", "lng": 1},
    {"lat": float("nan"), "lng": 1}, {"name": "x" * 61}, {"name": 5}, [1, 2]])
def test_invalid_details_are_rejected_without_saving(web, payload):
    client, headers, video, _ = web
    response = client.post(f"/api/videos/{video['id']}/camera", headers=headers, json=payload)
    assert response.status_code == 400
    assert client.get("/api/videos").json["videos"][0]["camera"] == {}


def test_requires_csrf_token_and_existing_video(web):
    client, headers, video, _ = web
    assert client.post(f"/api/videos/{video['id']}/camera", json={"name": "x"}).status_code == 403
    assert client.post("/api/videos/999/camera", headers=headers, json={"name": "x"}).status_code == 404


def test_corrupt_store_is_treated_as_empty(web):
    client, headers, video, ws = web
    (ws.settings().db_path.with_name("cameras.json")).write_text("{not json", encoding="utf-8")
    assert client.get("/api/videos").json["videos"][0]["camera"] == {}
    assert client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"name": "Lobby"}).status_code == 200


def test_map_tiles_are_the_only_external_images_allowed(web):
    client, _, _, _ = web
    policy = client.get("/").headers["Content-Security-Policy"]
    assert "script-src 'self';" in policy and "connect-src 'self';" in policy
    assert "img-src 'self' data: https://server.arcgisonline.com;" in policy
