"""Settings for running the website on a host such as Render (docs/deploy-render.md).

Locally none of these variables are set, so the site stays localhost-only, open and able to add footage.
"""
import base64

import pytest

from tanya.config import SearchSettings
from tanya.web import create_app

HOSTED = "tanyacctv.onrender.com"


def make_client(workspace, monkeypatch, **env):
    for name in ("TANYA_ALLOWED_HOSTS", "RENDER_EXTERNAL_HOSTNAME", "TANYA_SITE_PASSWORD", "TANYA_DISABLE_UPLOADS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    app = create_app(workspace.settings(), SearchSettings(None, workspace.video_dir / "bridge.py"))
    app.config["TESTING"] = True
    return app.test_client()


def basic(password, user="judge"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_defaults_stay_local_and_open(workspace, monkeypatch):
    client = make_client(workspace, monkeypatch)
    assert client.get("/").status_code == 200
    assert client.get("/", headers={"Host": HOSTED}).status_code == 403
    assert client.get("/api/status").json["uploads_enabled"] is True


def test_render_hostname_and_extra_hosts_are_accepted(workspace, monkeypatch):
    client = make_client(workspace, monkeypatch, RENDER_EXTERNAL_HOSTNAME=HOSTED, TANYA_ALLOWED_HOSTS="cctv.example.org, demo.example")
    for host in (HOSTED, "cctv.example.org", "demo.example", "localhost"):
        assert client.get("/", headers={"Host": host}).status_code == 200, host
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_health_check_answers_any_host_without_password(workspace, monkeypatch):
    client = make_client(workspace, monkeypatch, TANYA_SITE_PASSWORD="secret")
    response = client.get("/healthz", headers={"Host": "10.0.0.5:10000"})
    assert response.status_code == 200 and response.data == b"ok"


@pytest.mark.parametrize("headers, expected", [({}, 401), (basic("wrong"), 401), (basic("secret"), 200), (basic("secret", user=""), 200)])
def test_site_password(workspace, monkeypatch, headers, expected):
    client = make_client(workspace, monkeypatch, TANYA_SITE_PASSWORD="secret")
    response = client.get("/", headers=headers)
    assert response.status_code == expected
    if expected == 401:
        assert "Basic" in response.headers["WWW-Authenticate"]
        assert client.get("/api/videos", headers=headers).status_code == 401


def test_uploads_can_be_turned_off(workspace, monkeypatch):
    client = make_client(workspace, monkeypatch, TANYA_DISABLE_UPLOADS="1")
    client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    assert client.get("/api/status").json["uploads_enabled"] is False
    for path in ("/api/upload", "/api/index"):
        response = client.post(path, headers=headers)
        assert response.status_code == 403 and "turned off" in response.json["error"]
    assert not list(workspace.video_dir.iterdir())
