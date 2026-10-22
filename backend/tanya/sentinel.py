"""Early-warning detector: warning signs before an incident, from one camera's rules. Runs on this computer.

Rules are set by a person per camera (stored with the camera details):
  zones  - areas to watch, e.g. a driveway: movement inside is a notice (only during active hours, if set);
           someone staying longer than `loiter_sec` is a warning, and so is someone not moving for
           `still_sec` (for example after a fall).
  items  - objects to protect, e.g. a motorbike or a bag:
           mode "theft":      someone at the item is a warning; the item moving or disappearing is an alarm.
           mode "unattended": nobody near the item for `unattended_sec` is a warning.
Movement is found by background subtraction (CCTV cameras are fixed). It is not person recognition: a
shadow or headlights can also move. Every event says what was seen, never what anyone intends.
"""
import math
from collections import deque
from datetime import datetime, timedelta

import cv2
import numpy as np

FPS = 5                  # frames analysed per second of video
WIDTH = 320              # frames are shrunk to this width
WARMUP_SEC = 1.0         # background model settling time at the start of a recording
# After the warm-up the background learns slowly (time constant 1/(LEARN*FPS) = 40 s), so a person who stops
# moving stays visible as "not background" for a while. OpenCV's default learns fast early in a video.
LEARN = 0.005
MIN_AREA = 0.0005        # moving shapes smaller than this share of the frame are ignored (a person seen from above can be 0.06%)
GAP_SEC = 1.5            # presence survives short gaps (someone briefly hidden)
COOLDOWN_SEC = 20.0      # the same event is not repeated within this time
# Mean grey-level difference meaning an item looks different from its first frame. Measured on the parking clip:
# 2-7 while the motorbike stands there, 14-17 after it is taken.
CHANGE_LEVEL = 10.0
STILL_MAX = 0.06         # "not moving" is about people: shapes bigger than this share of the frame (vehicles) are skipped
STILL_MOVE = 0.04        # "not moving": the centre of what moves stays within this share of the frame width
MODES = ("theft", "unattended")
LEVELS = ("notice", "warning", "alarm")


class RuleError(ValueError):
    pass


def _box(value, label):
    if (not isinstance(value, list) or len(value) != 4 or any(type(c) not in (int, float) or not math.isfinite(c)
                                                              or not 0 <= c <= 1000 for c in value)
            or value[2] - value[0] < 10 or value[3] - value[1] < 10):
        raise RuleError(f"{label} needs an area of at least 1% of the picture, as [top, left, bottom, right] 0-1000.")
    return [round(float(c)) for c in value]


def _name(value, label):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
        raise RuleError(f"{label} needs a name of 1-40 characters.")
    return " ".join(value.split())


def _clock(value):
    if not isinstance(value, str) or len(value) != 5:
        raise RuleError("Active hours use HH:MM, e.g. 22:00.")
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        raise RuleError("Active hours use HH:MM, e.g. 22:00.") from None
    return value


def clean_rules(rules):
    """Validated rules, or None to clear them."""
    if rules is None:
        return None
    if not isinstance(rules, dict):
        raise RuleError("Rules must be an object.")
    zones = rules.get("zones") or []
    items = rules.get("items") or []
    if not isinstance(zones, list) or not isinstance(items, list) or len(zones) > 6 or len(items) > 6:
        raise RuleError("Use at most 6 zones and 6 items per camera.")
    out = {"zones": [{"name": _name(z.get("name"), "A zone"), "box_2d": _box(z.get("box_2d"), "A zone")}
                     for z in zones if isinstance(z, dict)],
           "items": [], "loiter_sec": 10, "unattended_sec": 5, "still_sec": 4, "hours": None}
    for item in items:
        if not isinstance(item, dict) or item.get("mode") not in MODES:
            raise RuleError("Each item needs a mode: theft or unattended.")
        out["items"].append({"name": _name(item.get("name"), "An item"), "box_2d": _box(item.get("box_2d"), "An item"),
                             "mode": item["mode"]})
    for key, low, high in (("loiter_sec", 3, 300), ("unattended_sec", 2, 600), ("still_sec", 3, 120)):
        if key in rules:
            value = rules[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise RuleError(f"{key} must be between {low} and {high} seconds.")
            out[key] = value
    hours = rules.get("hours")
    if hours:
        if not isinstance(hours, dict):
            raise RuleError("Active hours need a start and an end.")
        out["hours"] = {"from": _clock(hours.get("from")), "to": _clock(hours.get("to"))}
    if not out["zones"] and not out["items"]:
        return None
    return out


def _px(box, w, h):
    y0, x0, y1, x1 = box
    return int(x0 * w / 1000), int(y0 * h / 1000), int(x1 * w / 1000), int(y1 * h / 1000)


def _to_1000(rect, w, h):
    x, y, bw, bh = rect
    return [round(y * 1000 / h), round(x * 1000 / w), round((y + bh) * 1000 / h), round((x + bw) * 1000 / w)]


def _active(hours, started_at, t):
    """True if moment t of the recording falls inside the active hours (always, without hours or a clock)."""
    if not hours or not started_at:
        return True
    try:
        at = datetime.fromisoformat(started_at) + timedelta(seconds=t)
    except ValueError:
        return True
    now = at.strftime("%H:%M")
    start, end = hours["from"], hours["to"]
    return start <= now < end if start < end else (now >= start or now < end)


def analyse(path, duration_sec, rules, started_at=None):
    """Events in time order: [{t, level, kind, target, message, box_2d}]. Each one is what a person would want
    to be told while watching this camera live."""
    rules = clean_rules(rules)
    if rules is None:
        raise RuleError("Set at least one zone or item for this camera first.")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuleError("This recording could not be opened.")
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    skip = max(1, round(fps / FPS))
    subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=30, detectShadows=True)
    # Only slightly darker pixels count as shadow (default: up to 50% darker), so people in dark clothes count.
    subtractor.setShadowThreshold(0.8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    events, last_said = [], {}
    zone_state = {z["name"]: {"since": None, "seen": None, "loitered": False, "track": deque(), "still": False}
                  for z in rules["zones"]}
    item_state = {i["name"]: {"ref": None, "near_since": None, "alone_since": None, "changed_since": None, "gone": False}
                  for i in rules["items"]}

    def say(t, level, kind, target, message, box):
        key = (kind, target)
        if t - last_said.get(key, -1e9) < COOLDOWN_SEC:
            return
        last_said[key] = t
        events.append({"t": round(t, 2), "level": level, "kind": kind, "target": target, "message": message, "box_2d": box})

    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            index += 1
            if (index - 1) % skip:
                continue
            t = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            h0, w0 = frame.shape[:2]
            frame = cv2.resize(frame, (WIDTH, round(h0 * WIDTH / w0)))
            h, w = frame.shape[:2]
            grey = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            mask = subtractor.apply(frame, learningRate=-1 if t < WARMUP_SEC else LEARN)
            mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)[1]   # drop shadows (value 127)
            mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel, iterations=3)
            for item in rules["items"]:
                state = item_state[item["name"]]
                if state["ref"] is None:
                    x0, y0, x1, y1 = _px(item["box_2d"], w, h)
                    state["ref"] = grey[y0:y1, x0:x1].astype(np.float32)
            if t < WARMUP_SEC:
                continue
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            shapes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > MIN_AREA * w * h]
            active = _active(rules["hours"], started_at, t)

            for zone in rules["zones"]:
                state = zone_state[zone["name"]]
                zx0, zy0, zx1, zy1 = _px(zone["box_2d"], w, h)
                inside = [s for s in shapes if zx0 <= s[0] + s[2] / 2 <= zx1 and zy0 <= s[1] + s[3] <= zy1]   # feet in zone
                if inside:
                    if state["since"] is None or t - state["seen"] > GAP_SEC:
                        state["since"], state["loitered"] = t, False
                        if active:
                            say(t, "notice", "movement", zone["name"], f"Movement in {zone['name']}"
                                + (f" during watch hours ({rules['hours']['from']}-{rules['hours']['to']})" if rules["hours"] else ""),
                                _to_1000(max(inside, key=lambda s: s[2] * s[3]), w, h))
                    state["seen"] = t
                    if active and not state["loitered"] and t - state["since"] >= rules["loiter_sec"]:
                        state["loitered"] = True
                        say(t, "warning", "loitering", zone["name"], f"Someone has stayed in {zone['name']} for {round(t - state['since'])} s",
                            _to_1000(max(inside, key=lambda s: s[2] * s[3]), w, h))
                    # One person often shows as several pieces: follow the outline around the biggest piece and
                    # the pieces right next to it (not everything else that changes in the zone).
                    people = [s for s in inside if s[2] * s[3] <= STILL_MAX * w * h]
                    if not people:
                        state["track"].clear(); state["still"] = False
                        continue
                    core = max(people, key=lambda s: s[2] * s[3])
                    pad = max(core[2], core[3])
                    group = [s for s in people if s[0] < core[0] + core[2] + pad and s[0] + s[2] > core[0] - pad
                             and s[1] < core[1] + core[3] + pad and s[1] + s[3] > core[1] - pad]
                    ux0, uy0 = min(s[0] for s in group), min(s[1] for s in group)
                    ux1, uy1 = max(s[0] + s[2] for s in group), max(s[1] + s[3] for s in group)
                    biggest = (ux0, uy0, ux1 - ux0, uy1 - uy0)
                    track = state["track"]
                    track.append((t, ux0 + (ux1 - ux0) / 2, uy0 + (uy1 - uy0) / 2))
                    while track and t - track[0][0] > rules["still_sec"]:
                        track.popleft()
                    spread = max(max(p[1] for p in track) - min(p[1] for p in track), max(p[2] for p in track) - min(p[2] for p in track))
                    if t - state["since"] >= rules["still_sec"] and track[0][0] <= t - rules["still_sec"] + 0.5 and spread < STILL_MOVE * w:
                        if active and not state["still"]:
                            state["still"] = True
                            say(t, "warning", "still", zone["name"],
                                f"Someone has not moved in {zone['name']} for {round(rules['still_sec'])} s: they may need help",
                                _to_1000(biggest, w, h))
                    else:
                        state["still"] = False
                elif state["since"] is not None and t - state["seen"] > GAP_SEC:
                    state["since"], state["still"] = None, False
                    state["track"].clear()

            for item in rules["items"]:
                state = item_state[item["name"]]
                x0, y0, x1, y1 = _px(item["box_2d"], w, h)
                mx, my = int((x1 - x0) * 0.35) + 4, int((y1 - y0) * 0.35) + 4   # "near" = within about a third of its size
                near = [s for s in shapes if s[0] < x1 + mx and s[0] + s[2] > x0 - mx and s[1] < y1 + my and s[1] + s[3] > y0 - my]
                if item["mode"] == "theft":
                    if near:
                        if state["near_since"] is None:
                            state["near_since"] = t
                        if t - state["near_since"] >= 1.0:
                            say(t, "warning", "approach", item["name"], f"Someone is at the {item['name']}", item["box_2d"])
                    else:
                        state["near_since"] = None
                    region = grey[y0:y1, x0:x1].astype(np.float32)
                    changed = region.shape == state["ref"].shape and float(np.mean(np.abs(region - state["ref"]))) > CHANGE_LEVEL
                    if changed:
                        state["changed_since"] = state["changed_since"] if state["changed_since"] is not None else t
                        if not state["gone"] and t - state["changed_since"] >= 2.0:
                            state["gone"] = True
                            say(t, "alarm", "item_moved", item["name"], f"The {item['name']} has moved or is gone", item["box_2d"])
                    else:
                        state["changed_since"] = None
                else:
                    if near:
                        state["alone_since"] = None
                    else:
                        state["alone_since"] = state["alone_since"] if state["alone_since"] is not None else t
                        if t - state["alone_since"] >= rules["unattended_sec"]:
                            say(t, "warning", "unattended", item["name"],
                                f"The {item['name']} has been left unattended for {round(t - state['alone_since'])} s", item["box_2d"])
    finally:
        capture.release()
    return events
