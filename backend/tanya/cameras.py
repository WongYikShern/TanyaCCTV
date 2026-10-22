"""Camera names and map locations for recordings, kept in a small JSON file beside the library.

Keyed by content hash, so a name follows the footage even if the file is renamed or re-indexed.
Locations are entered by a person (clicking on the map); nothing is inferred from the footage.
"""
import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

MAX_NAME = 60
MAX_PLACE = 80
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CameraError(ValueError):
    pass


def store_path(settings):
    return settings.db_path.with_name("cameras.json")


def load(settings):
    """All saved camera details as {sha256: {...}}; an unreadable file counts as empty."""
    try:
        data = json.loads(store_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if SHA256.match(k) and isinstance(v, dict)} if isinstance(data, dict) else {}


def _clean_text(value, limit, label):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CameraError(f"{label} must be text.")
    value = " ".join(value.split())
    if len(value) > limit:
        raise CameraError(f"{label} can be at most {limit} characters.")
    return value


def _clean_coord(value, low, high, label):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise CameraError(f"{label} must be a number between {low} and {high}.")
    return round(float(value), 6)


def update(settings, sha256, data):
    """Validate and save one camera's name, place, location and/or hidden flag. Missing keys keep their value.

    A hidden camera stays in the library but is left off the camera wall, the map and "All recordings" scans."""
    if not isinstance(sha256, str) or not SHA256.match(sha256):
        raise CameraError("Unknown recording.")
    if not isinstance(data, dict):
        raise CameraError("Send the camera details as an object.")
    cameras = load(settings)
    entry = dict(cameras.get(sha256, {}))
    if "name" in data:
        entry["name"] = _clean_text(data["name"], MAX_NAME, "Camera name")
    if "place" in data:
        entry["place"] = _clean_text(data["place"], MAX_PLACE, "Place")
    if "lat" in data or "lng" in data:
        lat = _clean_coord(data.get("lat"), -90, 90, "Latitude")
        lng = _clean_coord(data.get("lng"), -180, 180, "Longitude")
        if (lat is None) != (lng is None):
            raise CameraError("Set both latitude and longitude, or clear both.")
        entry["lat"], entry["lng"] = lat, lng
    if "started_at" in data:
        # The camera's own clock when the recording starts (as burned into the footage), e.g.
        # "2004-01-20T10:35:11.3". Lets routes across cameras use real times. Typed in by a person.
        value = data["started_at"]
        if value in (None, ""):
            entry["started_at"] = None
        else:
            try:
                parsed = datetime.fromisoformat(value) if isinstance(value, str) and len(value) <= 32 else None
            except ValueError:
                parsed = None
            if parsed is None or parsed.tzinfo is not None:
                raise CameraError("Recording start must be a local date and time, e.g. 2004-01-20T10:35:11.")
            entry["started_at"] = parsed.isoformat(timespec="milliseconds")
    if "heading" in data:
        # Direction the camera faces on the map, in degrees clockwise from north (for its view cone).
        value = data["heading"]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise CameraError("Heading must be a number of degrees.")
        entry["heading"] = None if value is None else round(float(value) % 360, 1)
    if "hidden" in data:
        if type(data["hidden"]) is not bool:
            raise CameraError("hidden must be true or false.")
        entry["hidden"] = data["hidden"] or None
    entry = {k: v for k, v in entry.items() if v not in ("", None)}
    if entry:
        cameras[sha256] = entry
    else:
        cameras.pop(sha256, None)
    path = store_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write a temporary file and swap it in, so a crash never leaves half a file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cameras-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cameras, handle, indent=2, sort_keys=True)
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return entry
