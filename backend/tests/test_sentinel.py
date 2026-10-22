"""Early-warning detector: rule validation, the warning signs on synthetic scenes, and the API."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from tanya import sentinel
from tanya.config import SearchSettings
from tanya.web import create_app


def scene(path, seconds, draw, fps=25, size=(320, 240)):
    """A static noisy background; draw(frame, t) adds what happens at time t."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    background = np.random.default_rng(2).integers(40, 90, (size[1], size[0], 3), dtype=np.uint8)
    for i in range(int(seconds * fps)):
        frame = background.copy(); draw(frame, i / fps); writer.write(frame)
    writer.release()
    return path


def person(frame, x, y):
    cv2.rectangle(frame, (int(x), int(y)), (int(x) + 16, int(y) + 40), (230, 230, 230), -1)


def bike(frame):
    cv2.rectangle(frame, (200, 150), (260, 190), (30, 200, 240), -1)


def theft(frame, t):
    """Bike stands still; a person walks up from the left (2-6 s), waits (6-9 s), then leaves with the bike (9 s+)."""
    if t < 9:
        bike(frame)
    if 2 <= t < 6:
        person(frame, 20 + (t - 2) * 40, 150)
    elif 6 <= t < 9:
        person(frame, 180, 150)
    elif t >= 9:
        x = 180 - (t - 9) * 50
        if x > -20:
            person(frame, x, 150); cv2.rectangle(frame, (int(x) + 16, 150), (int(x) + 76, 190), (30, 200, 240), -1)


RULES = {"zones": [{"name": "Yard", "box_2d": [300, 0, 1000, 1000]}],
         "items": [{"name": "motorbike", "box_2d": [600, 600, 820, 840], "mode": "theft"}], "loiter_sec": 4}


def test_theft_scene_warns_before_the_alarm(tmp_path):
    events = sentinel.analyse(scene(tmp_path / "theft.mp4", 14, theft), 14, RULES)
    kinds = [(e["level"], e["kind"]) for e in events]
    assert ("notice", "movement") in kinds and ("warning", "approach") in kinds and ("alarm", "item_moved") in kinds
    first_warning = min(e["t"] for e in events if e["level"] == "warning")
    alarm = next(e["t"] for e in events if e["level"] == "alarm")
    assert first_warning < 9 <= alarm < 12          # warned before the bike moved; alarm soon after


def test_unattended_item_and_quiet_scene(tmp_path):
    bag = {"items": [{"name": "bag", "box_2d": [600, 600, 820, 840], "mode": "unattended"}], "unattended_sec": 3}
    events = sentinel.analyse(scene(tmp_path / "bag.mp4", 6, lambda f, t: bike(f)), 6, bag)
    assert [e["kind"] for e in events] == ["unattended"] and 3 <= events[0]["t"] < 5
    quiet = sentinel.analyse(scene(tmp_path / "quiet.mp4", 6, lambda f, t: bike(f)), 6, RULES)
    assert quiet == []


def test_someone_who_stops_moving_is_flagged(tmp_path):
    def fall(frame, t):
        person(frame, 40 + min(t, 2) * 50, 120) if t < 2 else cv2.rectangle(frame, (140, 150), (180, 166), (230, 230, 230), -1)
    events = sentinel.analyse(scene(tmp_path / "fall.mp4", 9, fall), 9, {"zones": [{"name": "Hall", "box_2d": [0, 0, 1000, 1000]}]})
    assert any(e["kind"] == "still" for e in events)


def test_watch_hours_silence_daytime_movement(tmp_path):
    video = scene(tmp_path / "walk.mp4", 6, lambda f, t: person(f, 20 + t * 40, 150) if t > 2 else None)
    rules = {"zones": RULES["zones"], "hours": {"from": "22:00", "to": "06:00"}}
    assert sentinel.analyse(video, 6, rules, "2024-01-01T23:30:00")[0]["kind"] == "movement"
    assert sentinel.analyse(video, 6, rules, "2024-01-01T14:00:00") == []


@pytest.mark.parametrize("rules", [{"zones": [{"name": "", "box_2d": [0, 0, 500, 500]}]}, {"zones": [{"name": "A", "box_2d": [0, 0, 5, 5]}]},
                                   {"items": [{"name": "b", "box_2d": [0, 0, 500, 500], "mode": "eat"}]}, {"zones": "x"},
                                   {"zones": [{"name": "A", "box_2d": [0, 0, 500, 500]}], "hours": {"from": "25:00", "to": "06:00"}},
                                   {"zones": [{"name": "A", "box_2d": [0, 0, 500, 500]}], "loiter_sec": 1}])
def test_bad_rules_are_rejected(rules):
    with pytest.raises(sentinel.RuleError):
        sentinel.clean_rules(rules)


def test_api_saves_rules_and_returns_events(workspace):
    scene(workspace.video_dir / "yard.mp4", 14, theft)
    workspace.run()
    app = create_app(workspace.settings(), SearchSettings(None, Path("unused")))
    app.config["TESTING"] = True
    client = app.test_client(); client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    video = client.get("/api/videos").json["videos"][0]
    assert client.post(f"/api/videos/{video['id']}/sentinel", headers=headers).status_code == 400   # no rules yet
    assert client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"rules": {"zones": "x"}}).status_code == 400
    assert client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"rules": RULES}).status_code == 200
    events = client.post(f"/api/videos/{video['id']}/sentinel", headers=headers).json["events"]
    assert any(e["level"] == "alarm" for e in events)
    assert client.post(f"/api/videos/{video['id']}/sentinel").status_code == 403
    client.post(f"/api/videos/{video['id']}/camera", headers=headers, json={"rules": None})
    assert "rules" not in client.get("/api/videos").json["videos"][0]["camera"]
