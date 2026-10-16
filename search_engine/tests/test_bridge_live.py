"""Live bridge tests: real Gemini query embeddings through the real bridge subprocess.

Skipped unless GEMINI_API_KEY is set in the environment running pytest (use ../run-live-tests.ps1).
Each query costs one text embedding (negligible). If TANYA_LIVE_REPORT is set, results
(scores and labels only, never the key) are saved there for review.

These tests check RANKING only. Labels are always "uncertain": the 2026-10-17 live run showed no
score statistic separates relevant from irrelevant clips on this footage (see tanya_bridge.py).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import BRIDGE, EVENTS, LIVE_REPORT, overlaps

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set (live test)"),
]

_report: dict[str, dict] = {}


@pytest.fixture(scope="module", autouse=True)
def write_report():
    yield
    if _report and LIVE_REPORT:
        Path(LIVE_REPORT).write_text(json.dumps(_report, indent=2), encoding="utf-8")


def bridge_search(query: str, db, python, n: int = 5) -> list[dict]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([str(python), str(BRIDGE), "search", query, "--n", str(n), "--db", str(db)],
                          capture_output=True, text=True, env=env, timeout=180)
    data = json.loads(proc.stdout)
    assert proc.returncode == 0 and data["ok"], data
    _report[query] = data
    results = data["results"]
    assert len(results) == n  # dedupe off: nothing silently dropped
    assert {r["status"] for r in results} == {"uncertain"}  # never treated as a confirmed incident
    return results


def test_walking_chunks_are_not_discarded(index_copy, bridge_python):
    results = bridge_search("a person walking", index_copy, bridge_python)
    assert all(overlaps(r, EVENTS["walking"]) for r in results[:3]), results[:3]


def test_person_lying_ranks_first(index_copy, bridge_python):
    results = bridge_search("a person lying on the floor", index_copy, bridge_python)
    assert all(overlaps(r, EVENTS["lying"]) for r in results[:3]), results[:3]


def test_red_car_ranks_first(index_copy, bridge_python):
    results = bridge_search("a red car", index_copy, bridge_python)
    assert all(overlaps(r, EVENTS["red_car"]) for r in results[:3]), results[:3]
    lobby_scores = [r["score"] for r in results if r["filename"] == "cam1_lobby.mp4"]
    assert all(results[0]["score"] > s for s in lobby_scores)


def test_fire_and_smoke_is_all_uncertain(index_copy, bridge_python):
    results = bridge_search("fire and smoke", index_copy, bridge_python)
    assert results, "search should still return ranked clips"
    # status is checked in bridge_search: every result is "uncertain"
