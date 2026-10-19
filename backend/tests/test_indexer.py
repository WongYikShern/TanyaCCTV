"""Tests for repeatable video indexing. All videos are synthetic; no real footage needed."""

from __future__ import annotations

import pytest

from tanya import db, indexer as indexer_mod
from tanya.frames import VideoError
from tanya.indexer import FAILED, INDEXED, SKIPPED, UNSUPPORTED, sha256_file
from tests.conftest import make_video


def statuses(summary):
    return {o.rel_path: o.status for o in summary.outcomes}


# --------------------------------------------------------------- happy path


def test_indexes_new_video(workspace):
    make_video(workspace.video_dir / "cam1.avi", seconds=5, fps=10)

    summary = workspace.run(interval=1.0)

    assert statuses(summary) == {"cam1.avi": INDEXED}
    [video] = workspace.videos()
    assert video["status"] == db.STATUS_DONE
    assert video["filename"] == "cam1.avi"
    assert video["sha256"] == sha256_file(workspace.video_dir / "cam1.avi")
    assert (video["width"], video["height"]) == (64, 48)
    assert video["fps"] == pytest.approx(10.0)
    assert video["duration_sec"] == pytest.approx(5.0)
    assert video["frame_count"] == 5

    frames = workspace.frames(video["id"])
    assert [f["timestamp_sec"] for f in frames] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert [f["frame_number"] for f in frames] == [0, 10, 20, 30, 40]
    for f in frames:
        assert (workspace.frames_dir / f["image_path"]).is_file()
    # Only the published folder remains; no temp leftovers.
    assert workspace.frame_dirs() == [video["sha256"]]


def test_interval_two_seconds_and_mp4(workspace):
    make_video(workspace.video_dir / "sub" / "cam2.mp4", seconds=5, fps=10)

    workspace.run(interval=2.0)

    [video] = workspace.videos()
    assert video["rel_path"] == "sub/cam2.mp4"
    assert [f["timestamp_sec"] for f in workspace.frames(video["id"])] == [0.0, 2.0, 4.0]


# ----------------------------------------------------------- repeatability


def test_rerun_skips_and_does_not_duplicate(workspace):
    make_video(workspace.video_dir / "cam1.avi", seed=1)
    make_video(workspace.video_dir / "cam2.avi", seed=2)
    workspace.run()
    before_frames = workspace.rows("SELECT id, image_path FROM frames ORDER BY id")

    summary = workspace.run()

    assert set(statuses(summary).values()) == {SKIPPED}
    assert len(workspace.videos()) == 2
    assert workspace.rows("SELECT id, image_path FROM frames ORDER BY id") == before_frames


def test_renamed_video_is_detected_not_reindexed(workspace):
    make_video(workspace.video_dir / "old_name.avi")
    workspace.run()
    [before] = workspace.videos()

    (workspace.video_dir / "old_name.avi").rename(workspace.video_dir / "new_name.avi")
    summary = workspace.run()

    [outcome] = summary.outcomes
    assert outcome.status == SKIPPED and "renamed from old_name.avi" in outcome.message
    assert summary.removed == []
    [after] = workspace.videos()
    assert after["id"] == before["id"]
    assert after["rel_path"] == "new_name.avi"
    assert len(workspace.frames(after["id"])) == before["frame_count"]


def test_modified_content_is_reindexed_and_old_data_removed(workspace):
    path = make_video(workspace.video_dir / "cam1.avi", seconds=3, seed=1)
    workspace.run()
    [old] = workspace.videos()

    make_video(path, seconds=4, seed=2)  # same file name, different content
    summary = workspace.run()

    assert statuses(summary) == {"cam1.avi": INDEXED}
    assert summary.removed == ["cam1.avi"]
    [new] = workspace.videos()
    assert new["sha256"] != old["sha256"]
    assert new["frame_count"] == 4
    assert workspace.rows("SELECT COUNT(*) FROM frames")[0][0] == 4
    assert workspace.frame_dirs() == [new["sha256"]]  # old frames folder is gone


def test_deleted_video_index_data_removed(workspace):
    make_video(workspace.video_dir / "keep.avi", seed=1)
    gone = make_video(workspace.video_dir / "gone.avi", seed=2)
    workspace.run()
    gone_sha = sha256_file(gone)

    gone.unlink()  # the user deletes the video
    summary = workspace.run()

    assert summary.removed == ["gone.avi"]
    assert [v["rel_path"] for v in workspace.videos()] == ["keep.avi"]
    assert gone_sha not in workspace.frame_dirs()
    assert (workspace.video_dir / "keep.avi").exists()


def test_changed_interval_triggers_reindex(workspace):
    make_video(workspace.video_dir / "cam1.avi", seconds=6)
    workspace.run(interval=1.0)

    summary = workspace.run(interval=2.0)

    assert statuses(summary) == {"cam1.avi": INDEXED}
    [video] = workspace.videos()
    assert video["frame_interval_sec"] == 2.0
    assert [f["timestamp_sec"] for f in workspace.frames(video["id"])] == [0.0, 2.0, 4.0]
    assert len(list((workspace.frames_dir / video["sha256"]).glob("*.jpg"))) == 3


def test_missing_frame_files_trigger_reindex(workspace):
    make_video(workspace.video_dir / "cam1.avi")
    workspace.run()
    [video] = workspace.videos()
    next((workspace.frames_dir / video["sha256"]).glob("*.jpg")).unlink()

    summary = workspace.run()

    assert statuses(summary) == {"cam1.avi": INDEXED}
    assert len(list((workspace.frames_dir / video["sha256"]).glob("*.jpg"))) == 5


def test_force_reindexes_without_duplicates_and_keeps_originals(workspace):
    path = make_video(workspace.video_dir / "cam1.avi")
    original_hash = sha256_file(path)
    workspace.run()

    summary = workspace.run(force=True)

    assert statuses(summary) == {"cam1.avi": INDEXED}
    [video] = workspace.videos()
    assert len(workspace.frames(video["id"])) == 5
    assert workspace.rows("SELECT COUNT(*) FROM frames")[0][0] == 5
    assert len(list((workspace.frames_dir / video["sha256"]).glob("*.jpg"))) == 5
    assert workspace.frame_dirs() == [video["sha256"]]
    assert sha256_file(path) == original_hash  # source video untouched


def test_duplicate_content_under_two_names(workspace):
    make_video(workspace.video_dir / "a.avi")
    (workspace.video_dir / "b.avi").write_bytes((workspace.video_dir / "a.avi").read_bytes())

    summary = workspace.run()

    assert statuses(summary) == {"a.avi": INDEXED, "b.avi": SKIPPED}
    assert len(workspace.videos()) == 1


# ------------------------------------------------------------ bad input


def test_corrupt_video_fails_without_stopping_the_run(workspace):
    make_video(workspace.video_dir / "good.avi")
    (workspace.video_dir / "corrupt.mp4").write_bytes(b"this is not a video" * 500)

    summary = workspace.run()

    assert statuses(summary) == {"good.avi": INDEXED, "corrupt.mp4": FAILED}
    assert summary.has_failures
    bad = workspace.rows("SELECT * FROM videos WHERE filename = 'corrupt.mp4'")[0]
    assert bad["status"] == db.STATUS_FAILED and bad["error"]
    assert workspace.frames(bad["id"]) == []
    assert bad["sha256"] not in workspace.frame_dirs()


def test_failed_video_is_retried_and_fixed_file_indexes(workspace):
    corrupt = workspace.video_dir / "cam1.avi"
    corrupt.write_bytes(b"garbage" * 1000)
    workspace.run()
    assert workspace.run().outcomes[0].status == FAILED  # retried, still bad, no crash

    make_video(corrupt)  # user replaces it with a working file
    summary = workspace.run()

    assert statuses(summary) == {"cam1.avi": INDEXED}
    [video] = workspace.videos()  # the stale failed record was removed
    assert video["status"] == db.STATUS_DONE


def test_empty_and_unsupported_files(workspace):
    (workspace.video_dir / "empty.mp4").write_bytes(b"")
    (workspace.video_dir / "notes.txt").write_text("hello", encoding="utf-8")
    (workspace.video_dir / ".hidden.mp4").write_bytes(b"x")

    summary = workspace.run()

    assert statuses(summary) == {"empty.mp4": FAILED, "notes.txt": UNSUPPORTED}
    assert workspace.videos() == []


def test_missing_video_dir_is_config_error(workspace, tmp_path):
    from tanya.config import ConfigError, Settings
    from tanya.indexer import Indexer

    settings = Settings(tmp_path / "nope", workspace.frames_dir, workspace.db_path)
    with pytest.raises(ConfigError):
        Indexer(settings, log=lambda _m: None).run()


def test_frames_dir_inside_video_dir_rejected(workspace):
    from tanya.config import ConfigError, Settings
    from tanya.indexer import Indexer

    settings = Settings(workspace.video_dir, workspace.video_dir / "frames", workspace.db_path)
    with pytest.raises(ConfigError):
        Indexer(settings, log=lambda _m: None).run()


def test_symlink_outside_video_dir_not_processed(workspace, tmp_path):
    outside = make_video(tmp_path / "outside" / "secret.avi")
    link = workspace.video_dir / "link.avi"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks is not permitted on this machine")

    summary = workspace.run()

    assert statuses(summary) == {"link.avi": FAILED}
    assert workspace.videos() == []


# ----------------------------------------------- failures during processing


def test_error_mid_extraction_leaves_no_partial_frames(workspace, monkeypatch):
    make_video(workspace.video_dir / "cam1.avi")

    def broken_extract(video_path, out_dir, interval_sec, jpeg_quality=90):
        (out_dir / "frame_000000_000000000ms.jpg").write_bytes(b"partial")
        raise VideoError("decoder crashed")

    monkeypatch.setattr(indexer_mod, "extract_frames", broken_extract)
    summary = workspace.run()

    assert statuses(summary) == {"cam1.avi": FAILED}
    [video] = workspace.videos()
    assert video["status"] == db.STATUS_FAILED and "decoder crashed" in video["error"]
    assert workspace.rows("SELECT COUNT(*) FROM frames")[0][0] == 0
    assert workspace.frame_dirs() == []  # temp folder cleaned up, nothing published

    monkeypatch.undo()
    assert statuses(workspace.run()) == {"cam1.avi": INDEXED}


def test_interrupted_run_is_resumed_safely(workspace, monkeypatch):
    make_video(workspace.video_dir / "cam1.avi")

    def interrupted_extract(video_path, out_dir, interval_sec, jpeg_quality=90):
        (out_dir / "frame_000000_000000000ms.jpg").write_bytes(b"partial")
        raise KeyboardInterrupt  # user pressed Ctrl+C

    monkeypatch.setattr(indexer_mod, "extract_frames", interrupted_extract)
    with pytest.raises(KeyboardInterrupt):
        workspace.run()

    [video] = workspace.videos()
    assert video["status"] == db.STATUS_PROCESSING
    assert workspace.frame_dirs() == []

    monkeypatch.undo()
    summary = workspace.run()
    assert statuses(summary) == {"cam1.avi": INDEXED}
    [video] = workspace.videos()
    assert video["status"] == db.STATUS_DONE
    assert len(workspace.frames(video["id"])) == 5


def test_interrupt_after_publish_before_commit(workspace, monkeypatch):
    """Simulate a crash after new frames were moved into place but before the DB commit."""
    make_video(workspace.video_dir / "cam1.avi", seconds=6)
    workspace.run(interval=1.0)
    [video] = workspace.videos()

    class CrashingConnection:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __enter__(self):
            return self._conn.__enter__()

        def __exit__(self, *exc):
            return self._conn.__exit__(*exc)

        def executemany(self, *args):
            raise KeyboardInterrupt

    real_connect = db.connect
    monkeypatch.setattr(db, "connect", lambda path: CrashingConnection(real_connect(path)))
    with pytest.raises(KeyboardInterrupt):
        workspace.run(interval=2.0)
    monkeypatch.undo()

    # Old frame rows survived (transaction rolled back) and status says "redo me".
    [video] = workspace.videos()
    assert video["status"] == db.STATUS_PROCESSING

    summary = workspace.run(interval=2.0)
    assert statuses(summary) == {"cam1.avi": INDEXED}
    [video] = workspace.videos()
    assert [f["timestamp_sec"] for f in workspace.frames(video["id"])] == [0.0, 2.0, 4.0]
    assert len(list((workspace.frames_dir / video["sha256"]).glob("*.jpg"))) == 3
    assert workspace.frame_dirs() == [video["sha256"]]
