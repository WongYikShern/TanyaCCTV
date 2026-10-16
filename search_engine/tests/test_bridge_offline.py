"""Offline bridge tests: no API key, no network. Uses real stored chunk embeddings."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import tanya_bridge
from conftest import BRIDGE, EVENTS, overlaps

FAKE_KEY = "FAKE-TEST-KEY-not-real-bridge-0123456789"


def run_main(capsys, argv):
    code = tanya_bridge.main(argv)
    out, err = capsys.readouterr()
    lines = out.strip().splitlines()
    assert len(lines) == 1, f"stdout must be exactly one JSON line, got: {out!r}"
    return code, json.loads(lines[0]), out, err


def walking_query_vector(chunk_embeddings):
    # Stand-in for "a person walking": the chunk that lies entirely inside the walk (24-34 s).
    return chunk_embeddings[("cam1_lobby.mp4", 24.0)]


# ----------------------------------------------------------------- deduplication


def test_dedupe_disabled_keeps_all_event_chunks(capsys, index_copy, chunk_embeddings, fake_embedder):
    fake_embedder(vector=walking_query_vector(chunk_embeddings))

    code, data, _, _ = run_main(capsys, ["search", "a person walking", "--n", "5", "--db", str(index_copy)])

    assert code == 0 and data["ok"] and data["dedupe"] == "disabled"
    assert len(data["results"]) == 5  # nothing silently dropped
    walking = [r for r in data["results"] if overlaps(r, EVENTS["walking"])]
    starts = {r["start_sec"] for r in walking}
    # 16-26, 24-34 and 32-42 all overlap the walk and are >0.9 cosine-similar to each other.
    assert {16.0, 24.0, 32.0} <= starts
    assert data["results"][0]["start_sec"] == 24.0


def test_old_cli_default_dedupe_would_drop_event_chunks(index_copy, chunk_embeddings, fake_embedder):
    """Documents the bug the bridge fixes: dedupe_threshold=0.9 discards real walking chunks."""
    from sentrysearch.search import search_footage
    from sentrysearch.store import SentryStore

    fake_embedder(vector=walking_query_vector(chunk_embeddings))
    store = SentryStore(db_path=index_copy, backend="gemini")
    deduped = search_footage("q", store, n_results=5, dedupe_threshold=0.9)
    kept = {(r["source_file"].endswith("cam1_lobby.mp4"), r["start_time"]) for r in deduped}
    assert not {(True, 16.0), (True, 32.0)} <= kept  # at least one walking chunk was thrown away


# ----------------------------------------------------------------- JSON contract


def test_search_json_contract(capsys, index_copy, chunk_embeddings, fake_embedder):
    fake_embedder(vector=chunk_embeddings[("cam2_carpark.mp4", 24.0)])

    code, data, _, _ = run_main(capsys, ["search", "a red car", "--n", "3", "--db", str(index_copy)])

    assert code == 0
    assert set(data) == {"ok", "query", "total_chunks", "dedupe", "note", "baseline", "results"}
    assert data["query"] == "a red car" and data["total_chunks"] == 13
    assert set(data["baseline"]) == {"median"}
    results = data["results"]
    assert [r["rank"] for r in results] == [1, 2, 3]
    assert [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True)
    for r in results:
        assert set(r) == {"rank", "source_file", "filename", "start_sec", "end_sec",
                          "score", "score_above_median", "status"}
        assert r["filename"] in r["source_file"] and os.path.isfile(r["source_file"])
        assert 0 <= r["start_sec"] < r["end_sec"] <= 60
        assert r["status"] == "uncertain"
        assert r["score_above_median"] == pytest.approx(r["score"] - data["baseline"]["median"], abs=2e-4)
    assert results[0]["filename"] == "cam2_carpark.mp4" and overlaps(results[0], EVENTS["red_car"])


def test_stats_json(capsys, index_copy):
    code, data, _, _ = run_main(capsys, ["stats", "--db", str(index_copy)])
    assert code == 0 and data["total_chunks"] == 13 and len(data["source_files"]) == 2


# ----------------------------------------------------------------- labelling (no cutoff at all)

# Top-5 scores recorded from the live Gemini run on 2026-10-17 (sentrysearch-trial/live-results.json). The other 8
# chunks of each query are padded at the recorded median so the bridge sees the same median.
RECORDED_LIVE = {
    # flat scores: the old robust z-score labelled these irrelevant chunks "candidate" (z=4.16, 3.32)
    "fire and smoke": (0.3183, [0.3395, 0.3352, 0.3303, 0.3232, 0.3213]),
    # wide spread: the old z-score labelled these correct chunks "uncertain" (z=1.60)
    "a person lying on the floor": (0.3503, [0.4575, 0.4492, 0.4416, 0.3985, 0.3700]),
    "a red car": (0.2442, [0.3644, 0.3588, 0.3567, 0.2958, 0.2847]),
    "a person walking": (0.3443, [0.4013, 0.3963, 0.3921, 0.3469, 0.3450]),
}


def _fake_hits(top5, median):
    scores = top5 + [median] * 8
    return [{"source_file": f"C:/fake/clip{i}.mp4", "start_time": 8.0 * i, "end_time": 8.0 * i + 10,
             "similarity_score": s} for i, s in enumerate(scores)]


@pytest.mark.parametrize("query", sorted(RECORDED_LIVE))
def test_recorded_live_scores_are_all_uncertain(capsys, monkeypatch, index_copy, fake_embedder, query):
    import sentrysearch.search

    median, top5 = RECORDED_LIVE[query]
    fake_embedder(vector=[0.0])  # not used: search_footage is replaced below
    monkeypatch.setattr(sentrysearch.search, "search_footage",
                        lambda q, store, n_results, dedupe_threshold: _fake_hits(top5, median))

    code, data, _, _ = run_main(capsys, ["search", query, "--n", "5", "--db", str(index_copy)])

    assert code == 0
    assert data["baseline"]["median"] == pytest.approx(median, abs=1e-4)
    assert [r["score"] for r in data["results"]] == top5  # ranking order preserved
    assert {r["status"] for r in data["results"]} == {"uncertain"}
    for r, s in zip(data["results"], top5):
        assert r["score_above_median"] == pytest.approx(s - median, abs=1e-4)
    assert "relative_z" not in json.dumps(data)


def test_status_is_only_ever_uncertain(capsys, index_copy, chunk_embeddings, fake_embedder):
    # Even a perfect match (query vector == a stored chunk, score 1.0) is not a confirmed incident.
    for key in list(chunk_embeddings)[:4]:
        fake_embedder(vector=chunk_embeddings[key])
        _, data, _, _ = run_main(capsys, ["search", "q", "--n", "13", "--db", str(index_copy)])
        assert data["results"][0]["score"] == pytest.approx(1.0, abs=1e-3)
        assert {r["status"] for r in data["results"]} == {"uncertain"}


def test_removed_min_z_option_is_rejected(capsys):
    code, data, _, _ = run_main(capsys, ["search", "x", "--min-z", "3"])
    assert code == 1 and data["ok"] is False and "--min-z" in data["error"]


# ----------------------------------------------------------------- error safety


def test_errors_and_library_output_never_reveal_the_key(capsys, monkeypatch, index_copy, fake_embedder):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    fake_embedder(error=RuntimeError(f"401 invalid key {FAKE_KEY} for request"),
                  chatter=f"debug: using key {FAKE_KEY}")

    code, data, out, err = run_main(capsys, ["search", "anything", "--db", str(index_copy)])

    assert code == 1 and data["ok"] is False and data["error_type"] == "RuntimeError"
    assert FAKE_KEY not in out and FAKE_KEY not in err
    assert "***REDACTED***" in data["error"] and "***REDACTED***" in err


@pytest.mark.parametrize("argv, fragment", [
    (["search"], "query"),
    (["search", "   "], "empty"),
    (["search", "x", "--n", "0"], "--n"),
    (["search", "x", "--db", "Z:/no/such/index"], "not found"),
    (["explode"], "invalid choice"),
])
def test_bad_input_returns_json_error(capsys, argv, fragment):
    code, data, _, _ = run_main(capsys, argv)
    assert code == 1 and data["ok"] is False and fragment in data["error"]


def test_empty_index_returns_no_results(capsys, tmp_path, fake_embedder):
    fake_embedder(error=AssertionError("must not embed when the index is empty"))
    (tmp_path / "empty").mkdir()
    code, data, _, _ = run_main(capsys, ["search", "x", "--db", str(tmp_path / "empty")])
    assert code == 0 and data["results"] == [] and data["total_chunks"] == 0


# ----------------------------------------------------------------- real subprocess, pinned tool env


def _env_without_key():
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_subprocess_stats_in_pinned_tool_env(index_copy, bridge_python):
    proc = subprocess.run([str(bridge_python), str(BRIDGE), "stats", "--db", str(index_copy)],
                          capture_output=True, text=True, env=_env_without_key(), timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["total_chunks"] == 13


def test_subprocess_missing_key_is_clean_json_error(index_copy, bridge_python):
    proc = subprocess.run([str(bridge_python), str(BRIDGE), "search", "a red car", "--db", str(index_copy)],
                          capture_output=True, text=True, env=_env_without_key(), timeout=120)
    data = json.loads(proc.stdout)
    assert proc.returncode == 1 and data["ok"] is False
    assert data["error_type"] == "GeminiAPIKeyError"


def test_query_starting_with_dash_after_separator(capsys, index_copy, chunk_embeddings, fake_embedder):
    """The client sends `search --n N [--db X] -- QUERY`; a query like "-fire" must work."""
    fake_embedder(vector=chunk_embeddings[("cam2_carpark.mp4", 24.0)])
    code, data, _, _ = run_main(capsys, ["search", "--n", "3", "--db", str(index_copy), "--", "-fire"])
    assert code == 0 and data["query"] == "-fire" and len(data["results"]) == 3


def test_note_says_scores_are_not_probabilities(capsys, index_copy, chunk_embeddings, fake_embedder):
    fake_embedder(vector=chunk_embeddings[("cam2_carpark.mp4", 24.0)])
    _, data, _, _ = run_main(capsys, ["search", "--n", "1", "--db", str(index_copy), "--", "a red car"])
    assert "not calibrated probabilities" in data["note"]
