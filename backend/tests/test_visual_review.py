"""Visual filtering must not turn rankings, missing frames, or malformed output into matches."""
from copy import deepcopy
from pathlib import Path

import pytest

from tanya.config import SearchSettings
from tanya.sentry_client import SearchError
from tanya.visual_review import frame_samples, review_results
from tests.conftest import make_video


@pytest.fixture
def sample(workspace):
    make_video(workspace.video_dir / "clip.mp4", seconds=8)
    workspace.run()
    video = workspace.videos()[0]
    hit = dict(video_id=video["id"], filename="clip.mp4", rel_path="clip.mp4", start_sec=0,
               end_sec=8, best_score=.4, status="uncertain")
    return workspace, dict(query="people wearing black shirt", hits=[hit], warnings=[])


def run(sample, reviewer, result=None):
    ws, original = sample
    return review_results(deepcopy(original if result is None else result), ws.settings(),
                          SearchSettings(None, Path("unused")), reviewer=reviewer)


def decision(payload, verdict="supported"):
    return [dict(id=c["id"], verdict=verdict, reason="Visible clothing evidence.",
                 evidence_timestamps=[c["frames"][0]["timestamp_sec"]] if verdict == "supported" else [])
            for c in payload["candidates"]]


def test_samples_are_bounded_spread_and_never_contain_disk_paths(sample):
    ws, result = sample
    frames = frame_samples(ws.settings(), result["hits"][0])
    assert 1 <= len(frames) <= 6
    assert frames[0]["timestamp_sec"] == 0 and frames[-1]["timestamp_sec"] == 7
    assert all(set(f) == {"timestamp_sec", "jpeg"} and f["jpeg"] for f in frames)


@pytest.mark.parametrize("verdict,group", [("supported", "hits"), ("not_supported", "rejected_hits"),
                                           ("unclear", "unclear_hits")])
def test_decisions_are_separated_without_changing_uncertain_status(sample, verdict, group):
    result = run(sample, lambda payload, settings: decision(payload, verdict))
    assert len(result[group]) == 1
    assert result[group][0]["status"] == "uncertain"
    if verdict != "supported":
        assert result["hits"] == []


@pytest.mark.parametrize("invalid", [
    [], [{"id": "unexpected", "verdict": "supported"}],
    [{"id": [], "verdict": "supported"}],
    [{"id": "0", "verdict": "unclear", "reason": "unclear", "evidence_timestamps": []},
     {"id": "0", "verdict": "supported", "reason": "yes", "evidence_timestamps": [0]}],
    [{"id": "0", "verdict": "supported", "reason": "yes", "evidence_timestamps": []}],
    [{"id": "0", "verdict": "supported", "reason": "yes", "evidence_timestamps": [999]}],
    [{"id": "0", "verdict": "confirmed", "reason": "yes", "evidence_timestamps": [0]}],
    [{"id": "0", "verdict": "unclear", "reason": "", "evidence_timestamps": []}],
    {"not": "a list"},
])
def test_malformed_model_output_fails_closed(sample, invalid):
    with pytest.raises(SearchError):
        run(sample, lambda *args: invalid)


def test_missing_frames_does_not_call_model_or_accept_candidate(sample):
    ws, original = sample
    for frame in ws.frames_dir.rglob("*.jpg"):
        frame.unlink()
    def forbidden(*args):
        pytest.fail("Missing images must not trigger an API call")
    result = run(sample, forbidden)
    assert not result["hits"] and len(result["unclear_hits"]) == 1
    assert result["visual_review"]["checked_candidates"] == 0


def test_only_five_windows_sent_and_rest_remain_unclear(sample):
    ws, original = sample
    original["hits"] = [deepcopy(original["hits"][0]) for _ in range(7)]
    def review(payload, settings):
        assert len(payload["candidates"]) == 5
        assert sum(len(c["frames"]) for c in payload["candidates"]) <= 30
        return decision(payload)
    result = run(sample, review)
    assert len(result["hits"]) == 5 and len(result["unclear_hits"]) == 2


def test_symlinked_frame_outside_root_is_not_transmitted(sample, tmp_path):
    ws, original = sample
    outside = tmp_path / "private.jpg"
    first = next(ws.frames_dir.rglob("*.jpg"))
    outside.write_bytes(first.read_bytes())
    for image in ws.frames_dir.rglob("*.jpg"):
        image.unlink()
        image.symlink_to(outside)
    assert frame_samples(ws.settings(), original["hits"][0]) == []
