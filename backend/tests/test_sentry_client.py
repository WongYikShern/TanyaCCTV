"""Tests for the subprocess client that talks to the bridge (fake bridge, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tanya import sentry_client
from tanya.config import SearchSettings
from tanya.sentry_client import SearchError, SearchNotConfiguredError
from tests.search_fixtures import FAKE_BRIDGE, FAKE_KEY, search_env  # noqa: F401


def test_search_returns_recorded_results(search_env):
    data = sentry_client.search(search_env.search_settings, "a red car", n=3)
    assert [r["filename"] for r in data["results"]] == ["cam2_carpark.mp4"] * 3
    assert {r["status"] for r in data["results"]} == {"uncertain"}


def test_key_is_passed_through_environment_only(search_env, monkeypatch):
    monkeypatch.setenv("FAKE_BRIDGE_MODE", "key_check")
    assert sentry_client.run_bridge(search_env.search_settings, ["search", "x", "--n", "1"])["key_present"]
    assert not any(FAKE_KEY in " ".join(c) for c in search_env.calls())  # never on the command line


@pytest.mark.parametrize("settings, fragment", [
    (SearchSettings(sentry_python=None, bridge_path=FAKE_BRIDGE), "not configured"),
    (SearchSettings(sentry_python=Path("Z:/nope/python.exe"), bridge_path=FAKE_BRIDGE), "does not exist"),
    (SearchSettings(sentry_python=Path(sys.executable), bridge_path=Path("Z:/nope/bridge.py")), "not found"),
])
def test_not_configured(settings, fragment):
    with pytest.raises(SearchNotConfiguredError, match=fragment):
        sentry_client.search(settings, "x")


@pytest.mark.parametrize("mode, fragment", [
    ("error", "ClientError"),
    ("garbage", "no valid JSON"),
    ("crash", "no valid JSON"),
    ("bad_status", "unexpected result status"),
    ("exit_nonzero", "exited with code 2"),
])
def test_engine_failures_raise_search_error_without_the_key(search_env, monkeypatch, mode, fragment):
    monkeypatch.setenv("FAKE_BRIDGE_MODE", mode)
    with pytest.raises(SearchError, match=fragment) as exc:
        sentry_client.search(search_env.search_settings, "a red car")
    assert FAKE_KEY not in str(exc.value)


def test_redaction_marker_is_used(search_env, monkeypatch):
    monkeypatch.setenv("FAKE_BRIDGE_MODE", "error")
    with pytest.raises(SearchError) as exc:
        sentry_client.search(search_env.search_settings, "x")
    assert "***REDACTED***" in str(exc.value)


def test_timeout(search_env, monkeypatch):
    monkeypatch.setenv("FAKE_BRIDGE_MODE", "sleep")
    with pytest.raises(SearchError, match="timed out"):
        sentry_client.search(search_env.with_search(timeout_sec=1), "x")


@pytest.mark.parametrize("query, n", [("", 5), ("   ", 5), ("x", 0), ("x", 101)])
def test_invalid_input_never_starts_the_engine(search_env, query, n):
    with pytest.raises(SearchError):
        sentry_client.search(search_env.search_settings, query, n)
    assert search_env.calls() == []


def test_db_override_is_passed_to_bridge(search_env, tmp_path):
    sentry_client.stats(search_env.with_search(sentry_db=tmp_path / "idx"))
    assert search_env.calls()[-1] == ["stats", "--db", str(tmp_path / "idx")]
