"""Visual filtering must not turn rankings, missing frames, or malformed output into matches."""
from copy import deepcopy
from pathlib import Path

import pytest

from tanya.config import SearchSettings
from tanya.sentry_client import SearchError
from tanya.visual_review import frame_samples, review_results
from tests.conftest import junction_or_skip, make_video, symlink_or_skip


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
        symlink_or_skip(image, outside)
    assert frame_samples(ws.settings(), original["hits"][0]) == []


# --------------------------------------------------------------------------- outside paths (Windows-runnable)
# Without symlink privileges the test above is skipped on Windows. These cover the same check in
# frame_samples (resolve() + is_relative_to) via database paths and Windows junctions, and confirm
# that nothing is handed to the reviewer (the step that would send frames to Google).


def _frames_point_to(ws, image_path):
    import sqlite3
    conn = sqlite3.connect(ws.db_path)
    with conn:
        conn.execute("UPDATE frames SET image_path = ?", (image_path,))
    conn.close()


def _reviewer_calls(sample):
    calls = []
    result = run(sample, lambda payload, settings: calls.append(payload) or decision(payload))
    return calls, result


def test_db_frame_paths_outside_root_are_not_transmitted(sample, tmp_path):
    ws, original = sample
    assert frame_samples(ws.settings(), original["hits"][0])           # control: real frames are sampled
    private = tmp_path / "private.jpg"                                  # readable JPEG outside frames/
    private.write_bytes(next(ws.frames_dir.rglob("*.jpg")).read_bytes())
    for image_path in ("../private.jpg", str(private), str(private).replace("\\", "/")):
        _frames_point_to(ws, image_path)
        assert frame_samples(ws.settings(), original["hits"][0]) == [], image_path
        calls, result = _reviewer_calls(sample)
        assert calls == [], image_path                                  # nothing sent for review
        assert result["hits"] == [] and result["unclear_hits"][0]["visual_review"]["verdict"] == "unclear"


def test_frames_behind_a_junction_are_not_transmitted(sample, tmp_path):
    ws, original = sample
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "private.jpg").write_bytes(next(ws.frames_dir.rglob("*.jpg")).read_bytes())
    junction_or_skip(ws.frames_dir / "linked", outside_dir)
    assert (ws.frames_dir / "linked" / "private.jpg").is_file()         # readable through the junction
    _frames_point_to(ws, "linked/private.jpg")
    assert frame_samples(ws.settings(), original["hits"][0]) == []
    calls, _ = _reviewer_calls(sample)
    assert calls == []


def test_recorded_targeted_visual_checks_keep_temporal_ambiguity_explicit():
    """Protect the observed three-query sample results without making new API requests."""
    import json
    from tanya.config import PROJECT_ROOT
    data = json.loads((PROJECT_ROOT / 'evaluation/recordings/2026-10-19-targeted-visual.json').read_text())
    assert data['attempted_images'] == data['image_limit'] == 66
    assert len(data['results']) == 3
    expected = {'a person standing still for a long time': ('cam3_entrance.mp4', 5),
                'a parked car': ('cam4_driveway.mp4', 2),
                'a person falling down': ('cam5_corridor.mp4', 1)}
    for result in data['results']:
        assert 'error' not in result
        supported = [c for c in result['candidates'] if c['visual_review']['verdict'] == 'supported']
        assert len(supported) == 1
        assert (supported[0]['filename'], supported[0]['retrieval_rank']) == expected[result['query']]
        for candidate in result['candidates']:
            review = candidate['visual_review']
            assert set(review['evidence_timestamps']) <= set(review['sampled_timestamps'])
    fall = next(r for r in data['results'] if r['query'] == 'a person falling down')
    lobby = next(c for c in fall['candidates'] if c['filename'] == 'cam1_lobby.mp4')
    assert lobby['visual_review']['verdict'] == 'unclear'
    assert lobby['visual_review']['evidence_timestamps'] == []
