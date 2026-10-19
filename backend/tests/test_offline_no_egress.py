"""The offline replay demo must never start a Google-bound process, through any route.

Worst case on purpose: a real-looking search interpreter and an API key are configured, and every
POST route is sent every approval flag. Only local work (indexing, playback copies, investigations,
reports) may run. Outbound work always goes through one of three subprocess launch points:
sentry_client (search/index CLI), search_sync (AI preparation) and visual_review (image checks).
"""
import subprocess

import pytest

from tanya.offline_demo import replay_search
from tanya.web import create_app
from tests.search_fixtures import search_env  # noqa: F401

APPROVE_ALL = {"query": "a red car", "confirmed": True, "visual_check": True, "approve_frame_upload": True,
               "video_ids": None, "scan_id": "x", "batch": 0, "format": "json", "title": "Rehearsal"}
OUTBOUND = ("tanya.sentry_client", "tanya.search_sync", "tanya.visual_review")


@pytest.fixture
def offline(search_env, monkeypatch):
    calls = []

    def forbidden(cmd, *args, **kwargs):
        calls.append(cmd)
        raise AssertionError(f"offline demo started an outbound process: {cmd}")

    for module in OUTBOUND:
        monkeypatch.setattr(f"{module}.subprocess.run", forbidden)
    # Fully configured on purpose: the guards must not depend on missing setup.
    app = create_app(search_env.settings, search_env.search_settings, offline_search=replay_search)
    client = app.test_client()
    client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    return app, client, headers, calls


def test_offline_status_never_offers_live_ai(offline):
    _, client, _, calls = offline
    status = client.get("/api/status").json
    assert status["offline_demo"] is True and status["scan_ready"] is False
    assert calls == []


def test_no_post_route_can_reach_google_in_offline_mode(offline):
    app, client, headers, calls = offline
    routes = sorted({r.rule for r in app.url_map.iter_rules() if "POST" in r.methods and "<" not in r.rule})
    assert {"/api/search", "/api/search/plan", "/api/search/sync", "/api/search/scan/plan",
            "/api/search/scan/batch"} <= set(routes)
    for rule in routes:
        response = client.post(rule, headers=headers, json=APPROVE_ALL)
        assert response.status_code < 500, (rule, response.status_code, response.get_json())
    for rule in ("/api/search/plan", "/api/search/sync", "/api/search/scan/plan", "/api/search/scan/batch"):
        assert client.post(rule, headers=headers, json=APPROVE_ALL).status_code == 403, rule
    visual = client.post("/api/search", headers=headers, json=APPROVE_ALL)
    assert visual.status_code == 403 and "no Google calls" in visual.json["error"]
    ranked = client.post("/api/search", headers=headers, json={"query": "a red car"})
    assert ranked.status_code == 200 and any("OFFLINE REPLAY" in w for w in ranked.json["warnings"])
    assert calls == []


def test_live_mode_still_uses_the_engine(search_env, monkeypatch):
    """Control: the same patch does fire outside offline mode, so the test above is meaningful."""
    calls = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("tanya.sentry_client.subprocess.run", spy)
    search_env.set_indexed([str(p) for p in search_env.settings.video_dir.glob("*.mp4")])
    client = create_app(search_env.settings, search_env.search_settings).test_client()
    client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    client.post("/api/search", headers=headers, json={"query": "a person walking"})
    assert calls, "the engine subprocess was expected in live mode"
