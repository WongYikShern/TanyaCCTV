"""Pre-analysed footage: moments a person described in advance, searchable by plain words without AI.

Notes live in data/footage_notes.json (local, not in Git), each bound to a recording's content hash:
  {"notes": [{"sha256": ..., "start_sec": 27, "end_sec": 42, "description": "...", "tags": [...],
              "box": {"timestamp": 30, "box_2d": [ymin, xmin, ymax, xmax], "label": "..."}}]}
A query matches a note when its words (or their synonyms) appear in the note's description or tags.
Results say they come from pre-analysed notes, not from a live AI check.
"""
import json
import re

STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "or", "with", "is", "are", "was", "who", "that",
        "find", "show", "me", "any", "some", "someone", "somebody", "for", "from", "into", "by", "his", "her", "their"}
# Words that mean the same thing for searching. Every word in a group is expanded to the whole group.
SYNONYMS = [
    {"steal", "stealing", "stole", "stolen", "theft", "thief", "thieves", "rob", "robbing", "robbery", "burglar",
     "burglary", "break", "breaking", "loot", "taking", "takes", "take", "took", "grab", "grabbing", "crime"},
    {"motorbike", "motorcycle", "bike", "scooter", "motor"},
    {"truck", "ute", "pickup", "van", "vehicle", "car"},
    {"man", "person", "people", "guy", "male", "suspect", "individual", "intruder", "men", "human"},
    {"bag", "luggage", "suitcase", "backpack", "item", "belonging", "belongings", "baggage", "parcel"},
    {"left", "leave", "leaving", "abandoned", "unattended", "alone", "forgotten", "lost", "missing", "behind"},
    {"fall", "falls", "fell", "falling", "fallen", "collapse", "collapsed", "lying", "floor", "ground", "slip"},
    {"walk", "walking", "walks", "passing", "moving", "crossing"},
    {"enter", "entering", "enters", "door", "coming", "arrive", "arrives", "garage"},
    {"night", "dark"},
    {"white", "light"},
    {"helmet", "hood", "hoodie", "masked", "mask"},
    {"load", "loading", "loads", "lift", "lifting", "carry", "carrying", "push", "pushing", "wheel", "wheeling"},
]
_GROUP = {}
for group in SYNONYMS:
    for word in group:
        _GROUP.setdefault(word, set()).update(group)


def words(text):
    return [w for w in re.findall(r"[a-z]+", str(text).lower()) if w not in STOP and len(w) > 1]


def expand(word):
    return _GROUP.get(word, {word})


def valid_box(box):
    return (isinstance(box, list) and len(box) == 4 and all(type(c) in (int, float) and 0 <= c <= 1000 for c in box)
            and box[0] < box[2] and box[1] < box[3])


def load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    notes = data.get("notes") if isinstance(data, dict) else None
    return [n for n in notes if isinstance(n, dict) and isinstance(n.get("sha256"), str)] if isinstance(notes, list) else []


def search(notes, query, library):
    """Notes matching the query whose recording is in `library` ({sha256: video row}), best first.

    Every query word must be found (directly or via a synonym) in the note's description or tags,
    so "a man stealing a motorbike" needs both a theft and a motorbike."""
    wanted = words(query)
    if not wanted:
        return []
    hits = []
    for note in notes:
        video = library.get(note["sha256"])
        if video is None:
            continue
        have = set(words(note.get("description", ""))) | set(words(" ".join(note.get("tags", []))))
        found = [w for w in wanted if expand(w) & have]
        if len(found) == len(wanted):
            hits.append((len(found) + 0.1 * len(set(wanted) & have), note, video))
    hits.sort(key=lambda h: (-h[0], h[2]["id"], h[1].get("start_sec", 0)))
    return [(note, video) for _, note, video in hits]
