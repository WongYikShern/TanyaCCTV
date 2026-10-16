"""Safety tests for `tanya_bridge.py remove`. Self-contained: builds its own temporary index.

The shared ~/.sentrysearch/db can hold footage from other folders, so remove must only ever
delete the chunks of one exactly-matching file inside the allowed folder.
"""

from __future__ import annotations

import json

import pytest

import tanya_bridge


@pytest.fixture
def store_dir(tmp_path):
    """Index with: two videos inside videos/, a name-prefix twin, and one file in another folder."""
    from sentrysearch.store import SentryStore

    videos = tmp_path / "videos"
    other = tmp_path / "elsewhere"
    files = {
        "cam1": str(videos / "cam1.mp4"),
        "cam10": str(videos / "cam10.mp4"),      # cam1.mp4 is NOT a substring, but "cam1" is a prefix
        "cam1_copy": str(videos / "sub" / "cam1.mp4"),
        "outside": str(other / "cam1.mp4"),      # same file name, different folder
    }
    db = tmp_path / "db"
    store = SentryStore(db_path=db, backend="gemini")
    chunks = []
    for i, f in enumerate(files.values()):
        for start in (0.0, 8.0):
            vec = [0.0] * 8
            vec[i] = 1.0
            chunks.append({"source_file": f, "start_time": start, "end_time": start + 10, "embedding": vec})
    store.add_chunks(chunks)
    return db, videos, files


def run(capsys, argv):
    code = tanya_bridge.main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    return code, json.loads(out[0])


def indexed(db):
    from sentrysearch.store import SentryStore

    return set(SentryStore(db_path=db, backend="gemini").get_stats()["source_files"])


def test_removes_only_the_exact_file(capsys, store_dir):
    db, videos, files = store_dir
    code, data = run(capsys, ["remove", "--source-file", files["cam1"], "--within", str(videos), "--db", str(db)])

    assert code == 0 and data["ok"] and data["removed_chunks"] == 2
    assert indexed(db) == {files["cam10"], files["cam1_copy"], files["outside"]}


def test_refuses_file_outside_within_folder(capsys, store_dir):
    db, videos, files = store_dir
    before = indexed(db)
    code, data = run(capsys, ["remove", "--source-file", files["outside"], "--within", str(videos), "--db", str(db)])

    assert code == 1 and not data["ok"] and "not inside --within" in data["error"]
    assert indexed(db) == before


@pytest.mark.parametrize("make_path", [
    lambda f, v: str(v / "cam"),                       # substring of several indexed paths
    lambda f, v: str(v / "cam1"),                      # prefix of cam1.mp4 and cam10.mp4
    lambda f, v: f["cam1"].upper(),                    # same file on Windows, but not an exact match
    lambda f, v: str(v / "missing.mp4"),               # not indexed at all
])
def test_refuses_anything_but_an_exact_indexed_path(capsys, store_dir, make_path):
    db, videos, files = store_dir
    before = indexed(db)
    code, data = run(capsys, ["remove", "--source-file", make_path(files, videos),
                              "--within", str(videos), "--db", str(db)])

    assert code == 1 and not data["ok"] and "refusing" in data["error"]
    assert indexed(db) == before


def test_refuses_relative_paths_and_the_folder_itself(capsys, store_dir):
    db, videos, files = store_dir
    before = indexed(db)
    for argv in (
        ["remove", "--source-file", "cam1.mp4", "--within", str(videos)],
        ["remove", "--source-file", files["cam1"], "--within", "videos"],
        ["remove", "--source-file", str(videos), "--within", str(videos)],
    ):
        code, data = run(capsys, argv + ["--db", str(db)])
        assert code == 1 and not data["ok"]
    assert indexed(db) == before


def test_missing_arguments_are_json_errors(capsys):
    code, data = run(capsys, ["remove", "--within", "C:/x"])
    assert code == 1 and "--source-file" in data["error"]
