"""Tests for opt-in search-index sync (fake bridge + fake sentrysearch CLI, no API calls)."""

from __future__ import annotations

import pytest

import sync_search_index as sync_cli
from tanya import search_sync
from tanya.sentry_client import SearchError
from tests.search_fixtures import FAKE_CLI, FAKE_KEY, search_env  # noqa: F401

OUTSIDE = r"C:\Users\someone\sentrysearch-trial\footage\cam1_lobby.mp4"  # shared-index entry from elsewhere


def sha(env, rel):
    return env.ws.rows("SELECT sha256 FROM videos WHERE rel_path = ?", (rel,))[0][0]


def plan_for(env):
    return search_sync.build_plan(env.settings, env.indexed(), search_sync.load_manifest(env.settings))


# --------------------------------------------------------------------------- estimates


def test_chunk_and_frame_estimates_match_sentrysearch_chunking():
    assert search_sync.estimate(60) == (8, 74)   # 0-10, 8-18, ... 48-58, 56-60
    assert search_sync.estimate(40) == (5, 48)   # 0-10 ... 32-40 (trial: 8 + 5 chunks)
    assert search_sync.estimate(6) == (1, 6)


# --------------------------------------------------------------------------- planning (changes nothing)


def test_new_videos_are_planned_with_cost_and_outside_entries_untouched(search_env):
    search_env.set_indexed([OUTSIDE])
    plan = plan_for(search_env)

    assert [v.rel_path for v in plan.to_index] == ["cam1_lobby.mp4", "cam2_carpark.mp4"]
    assert plan.to_remove == [] and plan.untouched_outside == 1
    assert plan.frames == 74 + 48
    assert plan.estimated_cost_usd == pytest.approx(122 * search_sync.USD_PER_FRAME)
    text = search_sync.describe(plan)
    assert "Videos to index: 2" in text and "Estimated frames: 122" in text and "US$0.10" in text
    assert "outside the video folder (never touched): 1" in text


def test_up_to_date_videos_are_left_alone(search_env):
    srcs = [search_env.source(r) for r in ("cam1_lobby.mp4", "cam2_carpark.mp4")]
    search_env.set_indexed(srcs)
    search_sync.save_manifest(search_env.settings, {
        s: {"sha256": sha(search_env, r)} for s, r in zip(srcs, ("cam1_lobby.mp4", "cam2_carpark.mp4"))})
    plan = plan_for(search_env)
    assert plan.is_empty and sorted(plan.up_to_date) == ["cam1_lobby.mp4", "cam2_carpark.mp4"]


def test_deleted_changed_and_unverified_entries_are_planned_for_removal(search_env):
    lobby, car = search_env.source("cam1_lobby.mp4"), search_env.source("cam2_carpark.mp4")
    gone = search_env.source("deleted.mp4")
    search_env.set_indexed([lobby, car, gone, OUTSIDE])
    search_sync.save_manifest(search_env.settings, {
        lobby: {"sha256": "0" * 64},                       # content changed since indexing
        gone: {"sha256": "1" * 64},
    })                                                     # car: indexed manually, unverifiable
    plan = plan_for(search_env)

    reasons = {r.source_file: r.reason for r in plan.to_remove}
    assert set(reasons) == {lobby, car, gone}               # OUTSIDE never planned
    assert "changed" in reasons[lobby] and "cannot be verified" in reasons[car] and "no longer" in reasons[gone]
    assert sorted(v.rel_path for v in plan.to_index) == ["cam1_lobby.mp4", "cam2_carpark.mp4"]


def test_unsearchable_formats_are_reported_not_planned(search_env):
    from tests.conftest import make_video

    make_video(search_env.settings.video_dir / "old.avi", seconds=3)
    search_env.ws.run()
    plan = plan_for(search_env)
    assert plan.not_searchable == ["old.avi"] and "old.avi" not in [v.rel_path for v in plan.to_index]


# --------------------------------------------------------------------------- the script is a dry run by default


@pytest.fixture
def cli_env(search_env, monkeypatch):
    s = search_env.settings
    monkeypatch.setenv("TANYA_VIDEO_DIR", str(s.video_dir))
    monkeypatch.setenv("TANYA_FRAMES_DIR", str(s.frames_dir))
    monkeypatch.setenv("TANYA_DB_PATH", str(s.db_path))
    monkeypatch.setenv("TANYA_SENTRY_PYTHON", str(search_env.search_settings.sentry_python))
    monkeypatch.setenv("TANYA_SENTRY_BRIDGE", str(search_env.search_settings.bridge_path))
    monkeypatch.delenv("TANYA_SENTRY_DB", raising=False)
    return search_env


def test_script_without_yes_changes_nothing(cli_env, capsys):
    cli_env.set_indexed([cli_env.source("deleted.mp4"), OUTSIDE])
    assert sync_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Videos to index: 2" in out and "Index entries to remove: 1" in out and "Dry run" in out
    assert [c[0] for c in cli_env.calls()] == ["stats"]          # no remove, no index
    assert cli_env.indexed() == [cli_env.source("deleted.mp4"), OUTSIDE]
    assert not search_sync.manifest_path(cli_env.settings).exists()


# --------------------------------------------------------------------------- applying (fake CLI)


def test_apply_removes_exact_entries_then_indexes_and_records_manifest(search_env):
    gone = search_env.source("deleted.mp4")
    search_env.set_indexed([gone, OUTSIDE])
    plan = plan_for(search_env)

    assert search_sync.apply_plan(plan, search_env.settings, search_env.search_settings, FAKE_CLI, log=lambda m: None)

    removes = [c for c in search_env.calls() if c[0] == "remove"]
    assert removes == [["remove", "--source-file", gone, "--within", str(search_env.settings.video_dir.resolve())]]
    indexes = [c for c in search_env.calls() if c[0] == "cli"]
    assert [c[2] for c in indexes] == [search_env.source("cam1_lobby.mp4"), search_env.source("cam2_carpark.mp4")]
    assert indexes[0][3:] == ["--chunk-duration", "10", "--overlap", "2"]
    assert OUTSIDE in search_env.indexed()                          # shared entry untouched
    manifest = search_sync.load_manifest(search_env.settings)
    assert manifest[search_env.source("cam1_lobby.mp4")]["sha256"] == sha(search_env, "cam1_lobby.mp4")
    assert plan_for(search_env).is_empty                            # second run: nothing to do


def test_apply_refuses_without_key_and_changes_nothing(search_env, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    search_env.set_indexed([search_env.source("deleted.mp4")])
    with pytest.raises(SearchError, match="GEMINI_API_KEY is not set"):
        search_sync.apply_plan(plan_for(search_env), search_env.settings, search_env.search_settings, FAKE_CLI)
    assert search_env.calls() == [] and search_env.indexed() == [search_env.source("deleted.mp4")]


def test_apply_refuses_custom_index_location(search_env, tmp_path):
    with pytest.raises(SearchError, match="TANYA_SENTRY_DB"):
        search_sync.apply_plan(plan_for(search_env), search_env.settings,
                               search_env.with_search(sentry_db=tmp_path), FAKE_CLI)
    assert search_env.calls() == []


@pytest.mark.parametrize("mode", ["fail", "silent_fail"])
def test_failed_indexing_is_reported_and_not_recorded(search_env, monkeypatch, mode):
    monkeypatch.setenv("FAKE_CLI_MODE", mode)
    logs = []
    ok = search_sync.apply_plan(plan_for(search_env), search_env.settings, search_env.search_settings,
                                FAKE_CLI, log=logs.append)
    assert ok is False
    assert search_sync.load_manifest(search_env.settings) == {}
    assert all("[failed]" in m for m in logs) and not any(FAKE_KEY in m for m in logs)
