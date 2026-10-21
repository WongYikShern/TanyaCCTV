"""Preset offline event index: search annotated events by plain words, without AI or network.

The index is a JSON file built by backend/scripts/run_offline_demo.py from labels that already exist:
  - CAVIAR publisher annotations (evaluation/datasets/caviar-events.json), or the single-reviewer provisional
    version of them when it is present locally (evaluation/provisional/, git-ignored);
  - the scripted events of the generated synthetic footage (backend/scripts/make_demo_footage.py);
  - optional cached YOLO person detections (tanya.person_detection), as unreviewed person-presence candidates.
Every entry is bound to the SHA-256 of the video it describes; an entry whose footage is not in the library
with that exact hash is never returned. Queries are matched by explicit synonym rules (no model), with
optional camera-view and time filters. Nothing here is a detection of an incident: each result says where
its label came from. This index is for the demo only and is never read by the benchmark tools.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import person_detection

FORMAT = "tanyacctv-event-index/1"
CONTEXT_SEC = 2.0   # surrounding footage played before and after an event

# Concept -> words/phrases that express it. Order matters only for display.
CONCEPTS = {
    "fall": ["fall", "falls", "falling", "fallen", "fell", "collapse", "collapses", "collapsed", "collapsing",
             "lying", "lies", "lie down", "lying down", "on the floor", "on the ground", "slip", "slipped", "trip",
             "tripped", "drop down"],
    "walk": ["walk", "walks", "walking", "walked", "passing", "passes", "passing by", "strolling", "moving",
             "crossing", "pedestrian walking"],
    "stand": ["standing", "stands", "standing still", "stand still", "loitering", "loiter", "waiting", "idle",
              "not moving", "stationary"],
    "browse": ["browse", "browsing", "window shopping", "looking at the shop", "looking in the window",
               "looking at a shop", "looking into the shop"],
    "enter": ["enter", "enters", "entering", "entered", "going in", "goes in", "go into", "goes into", "going into",
              "walks into", "walking into", "comes in", "coming in", "arrive", "arrives", "arriving"],
    "exit": ["exit", "exits", "exiting", "leave", "leaves", "leaving", "left the", "going out", "goes out",
             "comes out", "coming out", "drives away", "driving away", "departing"],
    "meet": ["meet", "meets", "meeting", "talking", "chatting", "interacting", "together", "group", "conversation"],
    "park": ["park", "parks", "parked", "parking"],
    "person": ["person", "people", "someone", "somebody", "anyone", "anybody", "human", "humans", "man", "woman",
               "men", "women", "pedestrian", "individual", "visitor", "customer"],
    "vehicle": ["car", "cars", "vehicle", "vehicles", "van", "truck", "taxi"],
}
# Things the index has no labels for, and TanyaCCTV cannot recognise: answer honestly instead of guessing.
UNSUPPORTED = {"fight": ["fight", "fighting", "punch", "punching", "assault", "attack", "hitting", "brawl"],
               "fire or smoke": ["fire", "smoke", "flames", "burning"],
               "weapon": ["weapon", "gun", "knife"],
               "theft": ["theft", "steal", "stealing", "stolen", "shoplifting", "robbery", "rob"],
               "running": ["run", "runs", "running", "chasing", "sprinting"]}
COLOURS = ["red", "blue", "green", "white", "black", "yellow", "silver", "grey", "gray"]
VIEWS = {"corridor": ["corridor", "hallway"], "front": ["front view", "front camera", "shop front", "front"],
         "overhead": ["overhead", "from above", "top view"], "lobby": ["lobby"],
         "car park": ["car park", "carpark", "parking lot"], "entrance": ["entrance", "doorway", "door"],
         "driveway": ["driveway"]}
# CAVIAR category -> concepts (all CAVIAR categories describe people).
CAVIAR_CONCEPTS = {"walking": {"person", "walk"}, "standing_still": {"person", "stand"},
                   "meeting": {"person", "meet"}, "person_present": {"person"}, "browsing": {"person", "browse"},
                   "fallen": {"person", "fall"}, "shop_enter": {"person", "enter"}, "shop_exit": {"person", "exit"}}
CAVIAR_LABELS = {"walking": "a person walking", "standing_still": "a person standing still (at least 2 s)",
                 "meeting": "people interacting (a group)", "person_present": "a person in view",
                 "browsing": "a person browsing", "fallen": "a person falling, then on the floor",
                 "shop_enter": "a person entering a shop", "shop_exit": "a person leaving a shop"}
SOURCES = {
    "provisional_review": ("Annotated · reviewed by one person",
                           "CAVIAR publisher annotation, kept by one human reviewer. Provisional: not "
                           "independently verified."),
    "publisher_annotation": ("Annotated (publisher)",
                             "CAVIAR publisher annotation; not reviewed by a person here."),
    "synthetic_script": ("Scripted demo event",
                         "Generated synthetic footage: this event was drawn at these times, so it is known by "
                         "construction. Cartoon scene, not real CCTV."),
    "yolo_person": ("Person detected (YOLO) · needs review",
                    person_detection.CAUTION),
}
SOURCE_ORDER = ["provisional_review", "publisher_annotation", "synthetic_script", "yolo_person"]
STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "into", "with", "and", "or", "is", "are", "was", "who",
        "that", "some", "any", "show", "me", "find", "clip", "clips", "video", "footage", "camera", "view",
        "someone", "person", "people", "there"}


def _has(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text) is not None


def concepts_of(text: str) -> set[str]:
    t = text.lower()
    return {c for c, words in CONCEPTS.items() if any(_has(t, w) for w in words)}


def unsupported_of(text: str) -> list[str]:
    t = text.lower()
    return [c for c, words in UNSUPPORTED.items() if any(_has(t, w) for w in words)]


def colours_of(text: str) -> set[str]:
    t = text.lower().replace("gray", "grey")
    return {c for c in COLOURS if _has(t, c)} - {"gray"}


def views_of(text: str) -> set[str]:
    t = text.lower()
    return {v for v, words in VIEWS.items() if any(_has(t, w) for w in words)}


def time_filter(text: str) -> tuple[float | None, float | None]:
    """'after 20 s', 'before 0:30', 'between 10 and 20 seconds' -> (lo, hi) in seconds."""
    t = text.lower()
    num = r"(\d+(?::\d{1,2})?(?:\.\d+)?)"

    def sec(v: str) -> float:
        if ":" in v:
            m, s = v.split(":")
            return int(m) * 60 + float(s)
        return float(v)
    if m := re.search(rf"between {num}\s*(?:s|sec|secs|seconds)?\s*and {num}", t):
        a, b = sorted((sec(m.group(1)), sec(m.group(2))))
        return a, b
    lo = sec(m.group(1)) if (m := re.search(rf"after {num}", t)) else None
    hi = sec(m.group(1)) if (m := re.search(rf"before {num}", t)) else None
    return lo, hi


@dataclass
class Query:
    text: str
    concepts: set[str]
    colours: set[str]
    views: set[str]
    unsupported: list[str]
    after: float | None
    before: float | None
    words: set[str] = field(default_factory=set)

    @classmethod
    def parse(cls, text: str) -> "Query":
        lo, hi = time_filter(text)
        views = views_of(text)
        # Camera-view phrases are filters, not actions: "in the car park" must not mean "a car parking".
        rest = text.lower()
        for v in views:
            for w in sorted(VIEWS[v], key=len, reverse=True):
                rest = re.sub(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", " ", rest)
        words = {w for w in re.findall(r"[a-z]+", rest) if w not in STOP and len(w) > 2}
        return cls(text, concepts_of(rest), colours_of(rest), views, unsupported_of(rest), lo, hi, words)

    @property
    def actions(self) -> set[str]:
        return self.concepts - {"person", "vehicle"}


def entry_matches(q: Query, e: dict) -> bool:
    ec = set(e["concepts"])
    if q.views and not q.views & set(e.get("views", [])):
        return False
    if q.after is not None and e["end_sec"] <= q.after:
        return False
    if q.before is not None and e["start_sec"] >= q.before:
        return False
    if q.colours and not q.colours & set(e.get("colours", [])):
        return False
    if q.actions:
        return q.actions <= ec and (not ({"person", "vehicle"} & q.concepts) or bool({"person", "vehicle"} & q.concepts & ec))
    if q.concepts == {"person"}:
        # Presence intervals, detector candidates, and scripted clips' person events (they have no separate
        # presence label). CAVIAR action labels are left out: its presence intervals already cover them.
        return (e["category"] == "person_present" or e["source"] == "yolo_person"
                or (e["source"] == "synthetic_script" and "person" in e["concepts"]))
    if "vehicle" in q.concepts:
        return "vehicle" in ec
    return False


def relevance(q: Query, e: dict) -> int:
    """Extra query words that also appear in the label or view (e.g. 'shop', 'door'): a tie-breaker only."""
    text = (e["label"] + " " + " ".join(e.get("views", []))).lower()
    return sum(1 for w in q.words if _has(text, w))


# --------------------------------------------------------------------------- building


def caviar_entries(events_path: Path, library: dict[str, str]) -> tuple[list[dict], list[str], dict]:
    """CAVIAR events for clips present in the library with the exact labelled video hash."""
    data = json.loads(events_path.read_text(encoding="utf-8"))
    status = data.get("verification")
    source = "provisional_review" if status == "provisional_single_reviewer" else "publisher_annotation"
    clips = {c["video"]: c for c in data["clips"]}
    notes, out = [], []
    for name, clip in clips.items():
        if library.get(name) is None:
            notes.append(f"{name}: not in the demo library; its labels are not indexed.")
        elif library[name] != clip["video_sha256"]:
            notes.append(f"{name}: the library copy's hash differs from the labelled video; its labels are not indexed.")
    views = {c["video"]: _caviar_views(c) for c in data["clips"]}
    for category, events in data["events"].items():
        for ev in events:
            name = ev["video"]
            if name not in clips or library.get(name) != clips[name]["video_sha256"]:
                continue
            out.append(dict(video=name, video_sha256=library[name], dataset="CAVIAR", category=category,
                            label=CAVIAR_LABELS.get(category, category.replace("_", " ")),
                            concepts=sorted(CAVIAR_CONCEPTS.get(category, set())), colours=[], views=views[name],
                            start_sec=float(ev["start_sec"]), end_sec=float(ev["end_sec"]), source=source,
                            verification=ev.get("verification", status)))
    contested = [dict(video=e["video"], category=e.get("category"), start_sec=e["start_sec"], end_sec=e["end_sec"])
                 for e in data.get("rejected_events", []) if library.get(e["video"]) == clips.get(e["video"], {}).get("video_sha256")]
    meta = {"file": events_path.name, "verification": status, "attribution": data.get("attribution"),
            "licence": data.get("licence"), "source_page": data.get("source_page"), "contested": contested}
    return out, notes, meta


def _caviar_views(clip: dict) -> list[str]:
    purpose = (clip.get("purpose") or "").lower()
    if "corridor" in purpose:
        return ["corridor"]
    if "front" in purpose:
        return ["front"]
    return ["overhead"]   # the three lobby-site clips are filmed from above (see docs/live-caviar-pilot-2026-10-21.md)


def synthetic_entries(scenes: dict, library: dict[str, str]) -> list[dict]:
    """Scripted events of generated synthetic clips: (name -> (duration, [(label, start, end), ...]))."""
    out = []
    for name, (_duration, events) in scenes.items():
        if library.get(name) is None:
            continue
        view = re.sub(r"^cam\d+_|\.mp4$", "", name).replace("carpark", "car park")
        for label, start, end in events:
            concepts = concepts_of(label)
            if "vehicle" not in concepts and ({"walk", "fall", "stand", "enter", "exit"} & concepts):
                concepts.add("person")
            out.append(dict(video=name, video_sha256=library[name], dataset="synthetic", category=label,
                            label=label, concepts=sorted(concepts), colours=sorted(colours_of(label)),
                            views=[view], start_sec=float(start), end_sec=float(end), source="synthetic_script",
                            verification="scripted"))
    return out


def build(path: Path, *, library: dict[str, str], scenes: dict, caviar_events: Path | None) -> dict:
    """Write the index JSON. `library` maps file name -> SHA-256 of the indexed copy."""
    entries = synthetic_entries(scenes, library)
    notes, caviar_meta = [], None
    if caviar_events and caviar_events.is_file():
        found, notes, caviar_meta = caviar_entries(caviar_events, library)
        entries += found
    index = {"format": FORMAT, "entries": entries, "notes": notes, "caviar": caviar_meta,
             "caution": "Labels describe what an annotation says happened. They are not detections or confirmed "
                        "incidents. Watch the footage before relying on any result."}
    path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index


# --------------------------------------------------------------------------- searching


class _Response:
    def __init__(self, data: dict):
        self.data = data

    def to_dict(self) -> dict:
        return self.data


class EventIndexSearch:
    """Callable used as the web app's offline search. Reads the index and the YOLO cache; never calls out."""
    mode = "event_index"

    def __init__(self, index_path: Path, yolo_config: person_detection.YoloConfig | None = None):
        self.index_path = Path(index_path)
        self.yolo_config = yolo_config

    def __call__(self, query: str, settings, search_settings=None):
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        if index.get("format") != FORMAT:
            raise ValueError("The event index file has an unexpected format.")
        q = Query.parse(query)
        conn = sqlite3.connect(f"{Path(settings.db_path).resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            videos = {r["sha256"]: dict(r) for r in conn.execute(
                "SELECT id, sha256, rel_path, filename, duration_sec FROM videos WHERE status='done'")}
            entries = [e for e in index["entries"] if e["video_sha256"] in videos]
            if "person" in q.concepts and not q.actions:
                views = {}
                for e in entries:   # a clip's camera view, from its labels, so view filters apply to detections too
                    views.setdefault(e["video_sha256"], set()).update(e.get("views", []))
                entries += self._yolo_entries(settings, videos, views)
            # "two people fighting" must not quietly become "two people": the unsupported part is the question.
            matched = [] if q.unsupported and not q.actions else [e for e in entries if entry_matches(q, e)]
            matched.sort(key=lambda e: (SOURCE_ORDER.index(e["source"]), -relevance(q, e), e["video"], e["start_sec"]))
            hits = [self._hit(e, videos[e["video_sha256"]], conn) for e in matched]
        finally:
            conn.close()
        warnings = ["OFFLINE DEMO: results come from a preset event index (annotations and cached detections), "
                    "not a live AI search."]
        if q.unsupported:
            warnings.append("This index has no labels for " + ", ".join(q.unsupported)
                            + ", and TanyaCCTV cannot recognise it. No result does not mean it did not happen.")
        if q.actions and "fall" in q.actions:
            warnings.append("YOLO person detections are never used as fall results: only annotated events are shown.")
        contested = (index.get("caviar") or {}).get("contested") or []
        if contested and matched and any(c["category"] in {e["category"] for e in matched} for c in contested):
            warnings.append(f"{len(contested)} annotated interval(s) were rejected by the reviewer and are not shown "
                            "(contested, unresolved).")
        if not hits:
            known = sorted({c for e in index["entries"] for c in e["concepts"]})
            warnings.append("No event in the preset index matches this description. The index only covers: "
                            + ", ".join(known) + ". This does not prove that nothing happened.")
        return _Response({"query": query, "hits": hits, "warnings": warnings, "mode": "event_index",
                          "matched_concepts": sorted(q.concepts), "filters": {
                              "views": sorted(q.views), "colours": sorted(q.colours), "after_sec": q.after,
                              "before_sec": q.before},
                          "note": "Preset event index for the offline demo: labels from the source shown on each "
                                  "result, matched by keywords. Not a detection, not a confirmed incident, and a "
                                  "missing result does not prove absence. Watch the footage before deciding."})

    def _yolo_entries(self, settings, videos: dict, views: dict | None = None) -> list[dict]:
        out = []
        for sha, video in videos.items():
            cached = person_detection.load_cached(settings, sha, self.yolo_config)
            if not cached or cached["stale"]:
                continue
            for iv in cached["intervals"]:
                out.append(dict(video=video["filename"], video_sha256=sha, dataset="library", category="person_detection",
                                label="a person detected in view", concepts=["person"], colours=[],
                                views=sorted((views or {}).get(sha, ())),
                                start_sec=iv["start_sec"], end_sec=iv["end_sec"], source="yolo_person",
                                verification="unreviewed_candidate",
                                detector={"max_conf": iv["max_conf"], "mean_conf": iv["mean_conf"], "frames": iv["frames"],
                                          "threshold": cached["presence_conf"], "model": cached["model"],
                                          "provenance": cached.get("provenance")}))
        return out

    @staticmethod
    def _hit(e: dict, video: dict, conn) -> dict:
        duration = video["duration_sec"] or e["end_sec"]
        start, end = max(0.0, e["start_sec"]), min(duration, e["end_sec"])
        frame = conn.execute("SELECT image_path, timestamp_sec FROM frames WHERE video_id=? "
                             "ORDER BY ABS(timestamp_sec - ?) LIMIT 1", (video["id"], start)).fetchone()
        badge, provenance = SOURCES[e["source"]]
        return {"video_id": video["id"], "rel_path": video["rel_path"], "filename": video["filename"],
                "start_sec": round(start, 2), "end_sec": round(end, 2), "best_score": None,
                "best_score_above_median": None, "chunks": [], "review_focus": None,
                "thumbnail": frame["image_path"] if frame else None,
                "thumbnail_timestamp_sec": frame["timestamp_sec"] if frame else None, "status": "uncertain",
                "event": {"label": e["label"], "category": e["category"], "dataset": e["dataset"],
                          "source": e["source"], "source_label": badge, "provenance": provenance,
                          "verification": e["verification"], "views": e.get("views", []),
                          "needs_human_review": e["source"] == "yolo_person",
                          "context_start_sec": round(max(0.0, start - CONTEXT_SEC), 2),
                          "context_end_sec": round(min(duration, end + CONTEXT_SEC), 2),
                          "detector": e.get("detector")}}
