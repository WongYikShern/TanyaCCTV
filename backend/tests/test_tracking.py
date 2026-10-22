"""Local tracking: follows a moving target from one box, both ways in time; validates input; API wiring."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from tanya import tracking
from tanya.config import SearchSettings
from tanya.web import create_app


def moving_square(path, seconds=5, fps=25, size=(320, 240)):
    """A white 40x60 square (with a red dot) moving right at 50 px/s over a fixed noisy background."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    background = np.random.default_rng(0).integers(0, 60, (size[1], size[0], 3), dtype=np.uint8)
    for i in range(seconds * fps):
        frame = background.copy(); x = 20 + 2 * i
        cv2.rectangle(frame, (x, 90), (x + 40, 150), (255, 255, 255), -1); cv2.circle(frame, (x + 20, 120), 8, (0, 0, 255), -1)
        writer.write(frame)
    writer.release()
    return path


def centre_px(box, width=320):
    return (box[1] + box[3]) / 2 / 1000 * width


def test_follows_the_target_forwards_and_backwards(tmp_path):
    video = moving_square(tmp_path / "square.mp4")
    # At t=2 s the square spans x 120-160 (of 320) and y 90-150 (of 240).
    result = tracking.track(video, 2.0, [375, 375, 625, 500], 5.0)
    assert result["lost_after"] is None and result["from"] < 1.0 and result["to"] > 4.5
    for point in result["points"]:
        expected = 20 + 50 * point["t"] + 20
        assert abs(centre_px(point["box_2d"]) - expected) < 12, point
        assert point["seen"], point


def test_target_that_leaves_the_box_is_marked_not_visible(tmp_path):
    """The square disappears after 3 s: later points are kept but marked not seen."""
    path = tmp_path / "vanish.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (320, 240))
    background = np.random.default_rng(1).integers(0, 60, (240, 320, 3), dtype=np.uint8)
    for i in range(125):
        frame = background.copy()
        if i < 75:
            cv2.rectangle(frame, (140, 90), (180, 150), (40, 200, 255), -1)
        writer.write(frame)
    writer.release()
    result = tracking.track(path, 1.0, [375, 437, 625, 563], 5.0)
    assert all(p["seen"] for p in result["points"] if p["t"] < 2.8)
    late = [p for p in result["points"] if p["t"] > 3.3]
    assert late and not any(p["seen"] for p in late)


@pytest.mark.parametrize("box", [[0, 0, 1001, 10], [500, 500, 400, 600], [1, 2, 3], [0, 0, 5, 5], "x"])
def test_bad_boxes_are_rejected(tmp_path, box):
    with pytest.raises(tracking.TrackingError):
        tracking.track(moving_square(tmp_path / "s.mp4"), 1.0, box, 5.0)


def test_time_must_be_inside_the_recording(tmp_path):
    with pytest.raises(tracking.TrackingError):
        tracking.track(moving_square(tmp_path / "s.mp4"), 9.0, [375, 375, 625, 500], 5.0)


def test_api_tracks_a_library_video_and_requires_csrf(workspace):
    moving_square(workspace.video_dir / "square.mp4")
    workspace.run()
    app = create_app(workspace.settings(), SearchSettings(None, Path("unused")))
    app.config["TESTING"] = True
    client = app.test_client(); client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    video = client.get("/api/videos").json["videos"][0]
    body = {"timestamp": 2.0, "box_2d": [375, 375, 625, 500]}
    assert client.post(f"/api/videos/{video['id']}/track", json=body).status_code == 403
    response = client.post(f"/api/videos/{video['id']}/track", headers=headers, json=body)
    assert response.status_code == 200 and len(response.json["points"]) > 20
    assert client.post(f"/api/videos/{video['id']}/track", headers=headers, json={"timestamp": 2.0, "box_2d": [1, 2]}).status_code == 400
    assert client.post("/api/videos/999/track", headers=headers, json=body).status_code == 404
