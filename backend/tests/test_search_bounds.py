"""Regressions found while validating uploaded clips with non-integer durations."""
from tanya.search import search_videos
from tanya.config import SearchSettings
from tests.conftest import make_video


def test_rounded_engine_end_is_clamped_to_recording(workspace, monkeypatch):
    make_video(workspace.video_dir / "clip.mp4", seconds=2.5)
    workspace.run()
    video = workspace.videos()[0]
    result = dict(rank=1, source_file=str(workspace.video_dir / "clip.mp4"), filename="clip.mp4",
                  start_sec=0, end_sec=video["duration_sec"] + .005, score=.4,
                  score_above_median=.1, status="uncertain")
    monkeypatch.setattr("tanya.search.sentry_client.search", lambda *a: {"results": [result]})
    response = search_videos("clip", workspace.settings(), SearchSettings(None, workspace.video_dir))
    assert response.hits[0].end_sec == video["duration_sec"]
    assert response.hits[0].chunks[0].end_sec == video["duration_sec"]
    assert response.hits[0].thumbnail is not None


def test_engine_window_entirely_after_recording_is_skipped(workspace, monkeypatch):
    make_video(workspace.video_dir / "clip.mp4", seconds=2)
    workspace.run()
    result = dict(rank=1, source_file=str(workspace.video_dir / "clip.mp4"), filename="clip.mp4",
                  start_sec=8, end_sec=18, score=.4, score_above_median=.1, status="uncertain")
    monkeypatch.setattr("tanya.search.sentry_client.search", lambda *a: {"results": [result]})
    response = search_videos("clip", workspace.settings(), SearchSettings(None, workspace.video_dir))
    assert not response.hits
    assert "outside the video duration" in response.warnings[0]
