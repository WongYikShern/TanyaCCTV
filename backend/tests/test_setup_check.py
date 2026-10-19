"""Tests for the read-only setup checks, search-interpreter discovery and website startup."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

import check_setup
import run_web
from tanya import config, setup_check
from tanya.config import SearchSettings, Settings
from tanya.setup_check import FAIL, PASS, WARN

FAKE_KEY = "FAKE-TEST-KEY-not-real-setup-0123456789"
TRIAL_PY = Path(os.environ.get("TANYA_SENTRY_PYTHON", "") or "Z:/none")


def settings_in(tmp_path) -> Settings:
    return Settings(tmp_path / "videos", tmp_path / "frames", tmp_path / "tanya.db")


def test_python_and_packages_pass_in_project_env():
    assert setup_check.check_python().status == PASS
    packages = setup_check.check_packages()
    assert packages.status == PASS and "Flask" in packages.detail and "opencv" in packages.detail


def test_missing_package_is_a_failure_with_fix(monkeypatch):
    real = setup_check.importlib.import_module
    monkeypatch.setattr(setup_check.importlib, "import_module",
                        lambda name: (_ for _ in ()).throw(ImportError()) if name == "flask" else real(name))
    check = setup_check.check_packages()
    assert check.status == FAIL and "Flask" in check.detail and "requirements.txt" in check.fix


def test_data_checks_fresh_install_passes(tmp_path):
    checks = {c.name: c for c in setup_check.check_data(settings_in(tmp_path))}
    assert checks["Video folder"].status == PASS and "created when first used" in checks["Video folder"].detail
    assert checks["Database"].status == PASS


def test_folder_that_is_a_file_fails(tmp_path):
    (tmp_path / "videos").write_text("not a folder", encoding="utf-8")
    checks = {c.name: c for c in setup_check.check_data(settings_in(tmp_path))}
    assert checks["Video folder"].status == FAIL


def test_corrupt_database_fails_without_modifying_it(tmp_path):
    db = tmp_path / "tanya.db"
    db.write_bytes(b"this is not sqlite" * 100)
    before = db.read_bytes()
    checks = {c.name: c for c in setup_check.check_data(settings_in(tmp_path))}
    assert checks["Database"].status == FAIL
    assert db.read_bytes() == before                                     # read-only check


def test_healthy_database_reports_video_count(workspace):
    from tests.conftest import make_video

    make_video(workspace.video_dir / "a.mp4", seconds=2)
    workspace.run()
    checks = {c.name: c for c in setup_check.check_data(workspace.settings())}
    assert checks["Database"].status == PASS and "1 video(s), integrity ok" in checks["Database"].detail


def test_onedrive_paths_warn(tmp_path):
    s = Settings(tmp_path / "OneDrive" / "videos", tmp_path / "f", tmp_path / "t.db")
    assert any(c.name == "OneDrive" and c.status == WARN for c in setup_check.check_data(s))


def test_port_in_use_warns_and_free_port_passes():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]
    try:
        assert setup_check.check_port(port).status == WARN
    finally:
        holder.close()
    assert setup_check.check_port(port).status == PASS


def test_search_not_configured_or_missing_warns(tmp_path):
    bridge = tmp_path / "bridge.py"
    assert setup_check.check_search(SearchSettings(None, bridge))[0].status == WARN
    missing = setup_check.check_search(SearchSettings(tmp_path / "nope.exe", bridge))[0]
    assert missing.status == WARN and "does not exist" in missing.detail


def test_python_without_sentrysearch_warns(tmp_path):
    check = setup_check.check_search(SearchSettings(Path(sys.executable), tmp_path / "bridge.py"))[0]
    assert check.status == WARN and "does not have SentrySearch installed" in check.detail


@pytest.mark.skipif(not TRIAL_PY.is_file(), reason="needs TANYA_SENTRY_PYTHON (the pinned SentrySearch env)")
def test_pinned_search_engine_passes():
    checks = setup_check.check_search(SearchSettings(TRIAL_PY, config.PROJECT_ROOT / "search_engine/tanya_bridge.py"))
    assert [c.status for c in checks] == [PASS, PASS] and "d3efd6a" in checks[0].detail


def test_key_presence_only_never_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    check = setup_check.check_key()
    assert check.status == PASS and FAKE_KEY not in check.detail
    assert FAKE_KEY not in setup_check.as_json(setup_check.run_all())
    assert FAKE_KEY not in "\n".join(setup_check.summary_lines(setup_check.run_all()))
    monkeypatch.delenv("GEMINI_API_KEY")
    assert setup_check.check_key().status == WARN


def test_check_setup_cli_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(check_setup, "run_all", lambda: [setup_check.Check("x", WARN, "optional")])
    assert check_setup.main([]) == 0 and "warning" in capsys.readouterr().out
    monkeypatch.setattr(check_setup, "run_all", lambda: [setup_check.Check("x", FAIL, "required", "do this")])
    assert check_setup.main([]) == 1 and "fix: do this" in capsys.readouterr().out


# --------------------------------------------------------------------------- interpreter discovery


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("TANYA_SENTRY_PYTHON", raising=False)
    return tmp_path


def test_local_sentry_env_is_discovered(fake_root):
    assert config.load_search_settings().sentry_python is None
    local = config.local_sentry_python()
    local.parent.mkdir(parents=True)
    local.write_text("", encoding="utf-8")
    assert config.load_search_settings().sentry_python == local


def test_explicit_interpreter_takes_precedence(fake_root, monkeypatch):
    local = config.local_sentry_python()
    local.parent.mkdir(parents=True)
    local.write_text("", encoding="utf-8")
    monkeypatch.setenv("TANYA_SENTRY_PYTHON", str(fake_root / "explicit.exe"))
    assert config.load_search_settings().sentry_python == fake_root / "explicit.exe"


# --------------------------------------------------------------------------- website startup


def test_busy_port_stops_startup_with_a_clear_message(monkeypatch, capsys):
    monkeypatch.setattr(run_web, "check_port",
                        lambda: setup_check.Check("Website port", WARN, "127.0.0.1:5001 is already in use", "stop it"))
    monkeypatch.setattr(run_web, "create_app", lambda *a: pytest.fail("app must not be created"))
    assert run_web.main() == 1
    assert "already in use" in capsys.readouterr().err


def test_startup_summary_shows_key_presence_only(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    lines = "\n".join(run_web.startup_lines(settings_in(tmp_path), SearchSettings(None, tmp_path / "b.py")))
    assert "Gemini key:    set" in lines and FAKE_KEY not in lines and "localhost:5001" in lines


def test_investigation_and_review_files_are_checked_read_only(tmp_path):
    checks = {c.name: c for c in setup_check.check_data(settings_in(tmp_path))}
    assert checks["Investigations file"].status == PASS and "created when first used" in checks["Investigations file"].detail
    bad = tmp_path / "investigations.db"
    bad.write_bytes(b"garbage" * 100)
    before = bad.read_bytes()
    checks = {c.name: c for c in setup_check.check_data(settings_in(tmp_path))}
    assert checks["Investigations file"].status == WARN and "move it aside" in checks["Investigations file"].fix
    assert bad.read_bytes() == before
    import sqlite3
    good = tmp_path / "search_feedback.db"                     # any valid SQLite file passes
    conn = sqlite3.connect(good)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    assert {c.name: c for c in setup_check.check_data(settings_in(tmp_path))}["Search reviews file"].status == PASS
