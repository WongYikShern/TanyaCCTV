"""Follow a person or object through a recording, starting from one box at one moment.

Runs on this computer (OpenCV's MIL tracker, corrected by motion: CCTV cameras are fixed, so a moving
shape next to the box is almost always the target); nothing is sent anywhere. The starting box comes from a
person drawing it, or from the AI image check's own box on a frame it cited. The track is a visual aid:
it can drift or lose the target (occlusion, darkness, low resolution), and says so instead of guessing.
"""
import math

import cv2

TRACK_FPS = 10          # positions per second of video
MAX_BACK_SEC = 4.0      # also follow a little backwards, so the box is there just before the moment
MAX_AHEAD_SEC = 20.0
MAX_WIDTH = 640         # frames are shrunk for speed; boxes are returned on the 0-1000 scale
LOST_AFTER = 5          # consecutive failed updates before the target counts as lost
# Colour similarity (HSV histogram correlation) between the box now and the box as drawn. Below this the
# target is marked "not visible" (hidden or out of view) while the tracker keeps its last place. Measured on
# the night garage clip: 0.55-0.76 with the person in the box, 0.11-0.39 without.
MIN_SIMILARITY = 0.45


class TrackingError(ValueError):
    pass


def check_box(box):
    if (not isinstance(box, list) or len(box) != 4 or any(type(c) not in (int, float) or not math.isfinite(c)
                                                          or not 0 <= c <= 1000 for c in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise TrackingError("The box must be [top, left, bottom, right] on a 0-1000 scale.")
    if (box[2] - box[0]) < 8 or (box[3] - box[1]) < 8:
        raise TrackingError("Draw a slightly bigger box around the person or object.")
    return [float(c) for c in box]


def _frames(capture, start_sec, end_sec, step):
    """(time, frame) pairs from start to end, about every `step` seconds, shrunk to MAX_WIDTH."""
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_sec) * 1000)
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    skip = max(1, round(fps * step))
    out, i = [], 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        t = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t > end_sec + 1e-6:
            break
        if i % skip == 0:
            h, w = frame.shape[:2]
            if w > MAX_WIDTH:
                frame = cv2.resize(frame, (MAX_WIDTH, round(h * MAX_WIDTH / w)))
            out.append((round(t, 3), frame))
        i += 1
    return out


def _appearance(frame, rect):
    x, y, w, h = (int(v) for v in rect)
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(fw, x + w), min(fh, y + h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 8, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def _moving_shapes(frames):
    """Boxes (x, y, w, h) of moving regions in each frame, by background subtraction in time order."""
    subtractor = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=25, detectShadows=False)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    shapes = []
    for _, frame in frames:
        mask = subtractor.apply(frame)
        mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area = frame.shape[0] * frame.shape[1] * 0.004
        shapes.append([cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > min_area])
    return shapes


def _towards_motion(frame, shapes, x, y, w, h):
    """Pull the box towards the largest moving shape near it, keeping its size; None if nothing moves nearby."""
    cx, cy = x + w / 2, y + h / 2
    near = [b for b in shapes if abs(b[0] + b[2] / 2 - cx) < max(w, 20) and abs(b[1] + b[3] / 2 - cy) < max(h, 20)]
    if not near:
        return None
    bx, by, bw, bh = max(near, key=lambda b: b[2] * b[3])
    cx, cy = cx + 0.6 * (bx + bw / 2 - cx), cy + 0.6 * (by + bh / 2 - cy)
    fh, fw = frame.shape[:2]
    w, h = min(int(w), fw - 2), min(int(h), fh - 2)
    return int(min(max(0, cx - w / 2), fw - w - 1)), int(min(max(0, cy - h / 2), fh - h - 1)), w, h


def _follow(frames, box, shapes=None):
    """Track through frames (already in the direction of travel), with the moving shapes of each frame.
    Returns points and the time the tracker failed (None if it never did)."""
    if not frames:
        return [], None
    h, w = frames[0][1].shape[:2]
    y0, x0, y1, x1 = box
    rect = (int(x0 * w / 1000), int(y0 * h / 1000), max(2, int((x1 - x0) * w / 1000)), max(2, int((y1 - y0) * h / 1000)))
    tracker = cv2.TrackerMIL_create()
    tracker.init(frames[0][1], rect)
    reference = _appearance(frames[0][1], rect)
    points, misses = [{"t": frames[0][0], "box_2d": [round(c) for c in box], "seen": True}], 0
    last = rect
    for i, (t, frame) in enumerate(frames[1:], start=1):
        ok, (x, y, bw, bh) = tracker.update(frame)
        if not ok:
            x, y, bw, bh = last
        pulled = _towards_motion(frame, shapes[i], x, y, bw, bh) if shapes else None
        if pulled:
            ok = True
            if abs(pulled[0] - x) > bw * 0.1 or abs(pulled[1] - y) > bh * 0.1:
                try:   # restart the tracker on the corrected place, so it doesn't drift back
                    tracker = cv2.TrackerMIL_create(); tracker.init(frame, pulled)
                except cv2.error:
                    pass
            x, y, bw, bh = pulled
        last = (x, y, bw, bh)
        inside = ok and bw > 1 and bh > 1 and x + bw > 0 and y + bh > 0 and x < w and y < h
        misses = 0 if inside else misses + 1
        if misses >= LOST_AFTER:
            return points, t
        if inside:
            now = _appearance(frame, (x, y, bw, bh))
            seen = reference is not None and now is not None and cv2.compareHist(reference, now, cv2.HISTCMP_CORREL) >= MIN_SIMILARITY
            points.append({"t": t, "box_2d": [round(max(0, y) * 1000 / h), round(max(0, x) * 1000 / w),
                                              round(min(h, y + bh) * 1000 / h), round(min(w, x + bw) * 1000 / w)], "seen": bool(seen)})
    return points, None


def track(path, timestamp, box, duration_sec):
    """Positions of the boxed target around `timestamp`, as [{t, box_2d}], plus where it was lost (if it was)."""
    box = check_box(box)
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not 0 <= timestamp <= (duration_sec or 0):
        raise TrackingError("Choose a moment inside the recording.")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise TrackingError("This recording could not be opened for tracking.")
    try:
        # One sequential read: seeking twice can land on different frames and shift the times.
        frames = _frames(capture, max(0.0, timestamp - MAX_BACK_SEC), min(duration_sec, timestamp + MAX_AHEAD_SEC), 1.0 / TRACK_FPS)
    finally:
        capture.release()
    if not frames:
        raise TrackingError("No frames could be read at that moment.")
    seed = min(range(len(frames)), key=lambda i: abs(frames[i][0] - timestamp))   # the frame the box was drawn on
    shapes = _moving_shapes(frames)
    forward, lost_ahead = _follow(frames[seed:], box, shapes[seed:])
    backward, lost_back = _follow(list(reversed(frames[:seed + 1])), box, list(reversed(shapes[:seed + 1])))
    points = sorted(backward[1:] + forward, key=lambda p: p["t"])
    return {"points": points, "lost_after": lost_ahead, "lost_before": lost_back,
            "from": points[0]["t"], "to": points[-1]["t"], "fps": TRACK_FPS}
