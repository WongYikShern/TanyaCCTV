"""Real-camera evaluation dataset built from publisher ground truth (CAVIAR), never from model output.

CAVIAR ships per-frame XML labels for every tracked person (movement, role, context, situation) and
for groups. This module turns those labels into event intervals with a fixed, documented rule per
category, pairs them with a fixed natural-language query set, and writes:

- a dataset manifest (one row per query x clip x event; JSON Lines),
- ground truth in the existing evaluation format ({"cases": [...]}, read by tanya.evaluation),
- a human review sheet (CSV) for independent verification.

Every derived interval is labelled ``publisher_label_unverified`` until a person confirms it with
the review sheet. Nothing here calls a model or a network service.
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

FPS = 25.0                      # review copies are normalised to frame_index / 25
MERGE_GAP_SEC = 0.5             # join label runs separated by a short tracking gap
DATASET = "CAVIAR"
LICENCE = "Publisher states Creative Commons BY-SA (version not specified)"
ATTRIBUTION = "EC Funded CAVIAR project/IST 2001 37540"
SOURCE_PAGE = "https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/"
UNVERIFIED = "publisher_label_unverified"
VERIFIED = "human_verified"
PROVISIONAL = "provisional_single_reviewer"   # one reviewer only: never "verified", never mixed with it
REVIEW_VERDICTS = ("confirm", "adjust", "reject")
REVIEW_COLUMNS = ["event_id", "event_key", "video", "category", "derived_start_sec", "derived_end_sec", "rule",
                  "reviewer_verdict (confirm/adjust/reject)", "verified_start_sec", "verified_end_sec",
                  "reviewer_initials", "notes"]


@dataclass(frozen=True)
class Rule:
    """Which publisher labels make a frame part of an event category.

    CAVIAR's ``context`` is a whole-track scenario label (a person who will later fall is labelled
    "drop down" from the moment they walk in), while ``movement`` and ``situation`` describe the
    person at that frame. Rules therefore use the instantaneous fields; ``context`` only selects
    which track (e.g. the faller) a rule applies to, combined with an instantaneous condition.
    All listed fields must match (AND); each field accepts any of its values (OR).
    """
    category: str
    description: str
    object_fields: dict | None = None     # field -> accepted values, all fields must match
    group_fields: dict | None = None      # field -> accepted values, all fields must match
    object_exclude: dict | None = None    # field -> values that disqualify the person
    any_person: bool = False
    min_duration_sec: float = 1.0


RULES = (
    Rule("walking", "a person's movement label is 'walking'", {"movement": {"walking"}}),
    Rule("standing_still", "a person's movement label is 'inactive' for at least 2 s (excluding a fallen person)",
         {"movement": {"inactive"}}, object_exclude={"context": {"drop down"}}, min_duration_sec=2.0),
    Rule("browsing", "a person's situation label is 'browsing'", {"situation": {"browsing"}}),
    Rule("shop_enter", "a person's situation label is 'shop enter' (the entering moment)",
         {"situation": {"shop enter"}}, min_duration_sec=0.4),
    Rule("shop_exit", "a person's situation label is 'shop exit' (the leaving moment)",
         {"situation": {"shop exit"}}, min_duration_sec=0.4),
    Rule("fallen", "the 'drop down' person is no longer walking (falling, then on the floor)",
         {"context": {"drop down"}, "movement": {"active", "inactive"}}),
    Rule("meeting", "a group's situation label is 'interacting'", group_fields={"situation": {"interacting"}}),
    Rule("person_present", "any tracked person is in view", any_person=True),
)
RULE_BY_CATEGORY = {r.category: r for r in RULES}

# Query set. kind: direct | paraphrase | ambiguous | appearance | negative | hard_negative.
# split: "dev" may be used for tuning; "test" is held out. Appearance queries have no publisher
# label (CAVIAR does not annotate clothing), so they stay unmeasured until a person labels them.
QUERIES = (
    dict(query="a person walking", category="walking", kind="direct", split="dev"),
    dict(query="pedestrian moving through the area", category="walking", kind="paraphrase", split="test"),
    dict(query="a person standing still", category="standing_still", kind="direct", split="dev"),
    dict(query="someone waiting in one place without moving", category="standing_still", kind="paraphrase", split="test"),
    dict(query="a person browsing at a display", category="browsing", kind="direct", split="dev"),
    dict(query="someone stopping to look at information on a board", category="browsing", kind="paraphrase", split="test"),
    dict(query="a person entering a shop", category="shop_enter", kind="direct", split="dev"),
    dict(query="a customer walking into a store", category="shop_enter", kind="paraphrase", split="test"),
    dict(query="a person leaving a shop", category="shop_exit", kind="direct", split="dev"),
    dict(query="someone coming out of a store", category="shop_exit", kind="paraphrase", split="test"),
    dict(query="a person falling to the floor", category="fallen", kind="direct", split="dev"),
    dict(query="someone collapsed and lying on the ground", category="fallen", kind="paraphrase", split="test"),
    dict(query="two people meeting and talking", category="meeting", kind="direct", split="dev"),
    dict(query="a small group of people standing together chatting", category="meeting", kind="paraphrase", split="test"),
    dict(query="a person", category="person_present", kind="ambiguous", split="test"),
    dict(query="someone acting suspiciously", category=None, kind="ambiguous", split="test",
         note="No objective publisher label; unmeasured until a reviewer defines and labels it."),
    dict(query="a person wearing a dark coat", category=None, kind="appearance", split="test",
         note="CAVIAR does not label clothing; needs human labels before it can be scored."),
    dict(query="a person carrying a bag", category=None, kind="appearance", split="test",
         note="CAVIAR does not label carried items in these clips; needs human labels."),
    dict(query="a car driving past", category=None, kind="negative", split="test",
         note="Indoor lobby and shopping-centre views; no vehicles are labelled."),
    dict(query="fire or smoke", category=None, kind="negative", split="test"),
    dict(query="a dog walking", category=None, kind="negative", split="test"),
    dict(query="a person running", category=None, kind="hard_negative", split="test",
         note="Visually close to walking; no 'running' movement label occurs in these clips."),
    dict(query="two people fighting", category=None, kind="hard_negative", split="test",
         note="Visually close to meeting; CAVIAR fight clips are not in this subset."),
    dict(query="a person leaving a bag behind", category=None, kind="hard_negative", split="test",
         note="Visually close to standing/browsing; CAVIAR left-bag clips are not in this subset."),
    dict(query="a person riding a bicycle", category=None, kind="hard_negative", split="test",
         note="Visually close to walking; no bicycle is labelled."),
)
MEASURABLE_KINDS = {"direct", "paraphrase", "ambiguous", "negative", "hard_negative"}


def _matches(element, fields: dict, exclude: dict | None = None) -> bool:
    hypothesis = element.find("hypothesislist/hypothesis")
    if hypothesis is None:
        return False
    value = lambda field: (hypothesis.findtext(field) or "").strip()  # noqa: E731
    if exclude and any(value(field) in values for field, values in exclude.items()):
        return False
    return all(value(field) in values for field, values in fields.items())


def frame_flags(xml_path: Path) -> tuple[int, dict[str, list[bool]]]:
    """(labelled frame count, {category: per-frame flag}) from one CAVIAR ground-truth XML file."""
    root = ET.parse(xml_path).getroot()
    frames = sorted(root.iter("frame"), key=lambda f: int(f.get("number")))
    numbers = [int(f.get("number")) for f in frames]
    if numbers != list(range(len(numbers))):
        raise ValueError(f"{xml_path.name}: frame numbers are not contiguous from 0")
    flags = {r.category: [False] * len(frames) for r in RULES}
    for i, frame in enumerate(frames):
        objects = list(frame.iter("object"))
        groups = list(frame.iter("group"))
        for rule in RULES:
            hit = bool(objects) if rule.any_person else (
                (rule.object_fields and any(_matches(o, rule.object_fields, rule.object_exclude) for o in objects))
                or (rule.group_fields and any(_matches(g, rule.group_fields) for g in groups)))
            flags[rule.category][i] = bool(hit)
    return len(frames), flags


def intervals(flags: list[bool], fps: float = FPS, merge_gap_sec: float = MERGE_GAP_SEC,
              min_duration_sec: float = 1.0) -> list[tuple[float, float]]:
    """Runs of flagged frames as [start, end) seconds; frame i covers [i/fps, (i+1)/fps)."""
    runs, start = [], None
    for i, on in enumerate(flags + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append([start, i])
            start = None
    merged = []
    for run in runs:
        if merged and (run[0] - merged[-1][1]) / fps <= merge_gap_sec:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(round(a / fps, 2), round(b / fps, 2)) for a, b in merged if (b - a) / fps >= min_duration_sec]


def clip_events(xml_path: Path) -> tuple[int, dict[str, list[tuple[float, float]]]]:
    count, flags = frame_flags(xml_path)
    return count, {r.category: intervals(flags[r.category], min_duration_sec=r.min_duration_sec) for r in RULES}


def load_clips(caviar_dir: Path, plan_path: Path) -> list[dict]:
    """Clip metadata from the local prepared copies (media-manifest.json) and the pinned plan."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    media = {m["filename"]: m for m in json.loads((caviar_dir / "media-manifest.json").read_text(encoding="utf-8"))}
    clips = []
    for c in plan["clips"]:
        name = c["name"] + ".mp4"
        m = media.get(name)
        xml = caviar_dir / "annotations" / (c["name"] + ".xml")
        if m is None or not (caviar_dir / "videos" / name).is_file():
            raise ValueError(f"Prepared video missing: {name}. Run download_caviar.py --download, then --prepare.")
        if not xml.is_file():
            raise ValueError(f"Publisher labels missing: {xml.name}. Run download_caviar.py --download.")
        clips.append(dict(clip_id=f"caviar-{c['name'].lower()}", video=name, xml=xml,
                          relative_path=f"data/cctv_validation/caviar/videos/{name}",
                          duration_sec=m["duration_sec"], fps=m["fps"], width=int(m["width"]),
                          height=int(m["height"]), decoded_frames=m["decoded_frames"],
                          video_sha256=m["sha256"], purpose=c.get("purpose", "")))
    return clips


def event_key(category: str, video: str, start: float, end: float) -> str:
    """Stable identity of a *derived* event: changes if the label rules change, so stale reviews are detected."""
    return f"{category}|{video}|{float(start):.2f}|{float(end):.2f}"


def build(clips: list[dict], verification: dict | None = None) -> dict:
    """Events per clip, the manifest rows, and ground-truth cases (existing evaluation format).

    verification: {event_key: {"status", "start_sec", "end_sec"}} from merge_reviews() (two reviewers)
    or single_review_verification() (one reviewer, provisional). "verified" -> human_verified,
    "provisional_confirmed" -> provisional_single_reviewer, both with the reviewed boundaries.
    "rejected" / "provisional_rejected" events are removed from the positives but become *contested*
    regions ("ignore_events" on the queries of that category): a rejection says the publisher label is
    doubtful there, not that the interval is a verified negative, so results inside it are not scored
    as right or wrong. Everything else stays publisher_label_unverified.
    """
    verification = verification or {}
    events, label_frames = {}, {}
    for clip in clips:
        count, per_category = clip_events(clip["xml"])
        label_frames[clip["video"]] = count
        for category, spans in per_category.items():
            for start, end in spans:
                if end > clip["duration_sec"] + 1 / FPS:
                    raise ValueError(f"{clip['video']}: label interval {start}-{end}s exceeds the video")
                events.setdefault(category, []).append(dict(video=clip["video"], start_sec=start,
                                                            end_sec=min(end, clip["duration_sec"]),
                                                            derived_start_sec=start,
                                                            derived_end_sec=min(end, clip["duration_sec"])))
    known = {event_key(c, e["video"], e["start_sec"], e["end_sec"]) for c, spans in events.items() for e in spans}
    stale = sorted(set(verification) - known)
    if stale:
        raise ValueError("Review results refer to events that no longer exist (label rules changed?): "
                         + "; ".join(stale[:5]))
    rejected = []
    for category, spans in events.items():
        kept = []
        for e in spans:
            v = verification.get(event_key(category, e["video"], e["start_sec"], e["end_sec"]))
            status = v["status"] if v else None
            if status in ("rejected", "provisional_rejected"):
                rejected.append(dict(e, category=category, verification=VERIFIED if status == "rejected" else PROVISIONAL,
                                     rejected_by="two_reviewers" if status == "rejected" else "single_reviewer"))
                continue
            if status in ("verified", "provisional_confirmed"):
                e.update(start_sec=v["start_sec"], end_sec=v["end_sec"],
                         verification=VERIFIED if status == "verified" else PROVISIONAL)
            else:
                e["verification"] = UNVERIFIED
            kept.append(e)
        events[category] = kept
    rows, cases = [], []
    for q in QUERIES:
        expected = events.get(q["category"], []) if q["category"] else []
        measurable = q["kind"] in MEASURABLE_KINDS and (q["category"] is not None or q["kind"] in
                                                        {"negative", "hard_negative"})
        expected_clips = sorted({e["video"] for e in expected})
        for clip in clips:
            mine = [e for e in expected if e["video"] == clip["video"]] or [None]
            for e in mine:
                rows.append(dict(
                    clip_id=clip["clip_id"], dataset=DATASET, relative_path=clip["relative_path"],
                    duration_sec=clip["duration_sec"], resolution=f"{clip['width']}x{clip['height']}",
                    fps=clip["fps"], licence=LICENCE, attribution=ATTRIBUTION,
                    event_category=q["category"], event_start_sec=e and e["start_sec"],
                    event_end_sec=e and e["end_sec"], query=q["query"], query_kind=q["kind"], split=q["split"],
                    event_present=e is not None if measurable else None, expected_clips=expected_clips,
                    annotation_confidence=(e["verification"] if e else UNVERIFIED) if measurable else "unlabelled",
                    annotation_notes=q.get("note") or (RULE_BY_CATEGORY[q["category"]].description
                                                        if q["category"] else "")))
        states = {e["verification"] for e in expected}
        state = "unlabelled" if not measurable else _combined_state(states)
        contested = [dict(video=r["video"], start_sec=r["derived_start_sec"], end_sec=r["derived_end_sec"],
                          rejected_by=r["rejected_by"]) for r in rejected if r["category"] == q["category"]]
        cases.append(dict(query=q["query"], event_type=q["category"] or q["kind"], query_kind=q["kind"],
                          split=q["split"], measurable=measurable, verification=state, note=q.get("note", ""),
                          events=[dict(video=e["video"], start_sec=e["start_sec"], end_sec=e["end_sec"],
                                       verification=e["verification"]) for e in expected] if measurable else [],
                          ignore_events=contested if measurable else []))
    return dict(events=events, label_frames=label_frames, rows=rows, cases=cases, rejected=rejected)


def single_review_verification(reviews: dict[str, dict]) -> dict[str, dict]:
    """One reviewer's answers as a *provisional* verification map (never "verified"): confirm/adjust ->
    provisional_confirmed with the reviewed boundaries; reject -> provisional_rejected (a contested region)."""
    out = {}
    for key, r in reviews.items():
        status = "provisional_rejected" if r["verdict"] == "reject" else "provisional_confirmed"
        out[key] = dict(status=status, reviewers=[r["initials"]], start_sec=r["start_sec"], end_sec=r["end_sec"],
                        verdict=r["verdict"], notes=r.get("notes", ""))
    return out


def _combined_state(states: set) -> str:
    if not states:
        return UNVERIFIED            # e.g. negative queries: absence comes from publisher labels only
    if len(states) == 1:
        return next(iter(states))
    return "partially_verified" if VERIFIED in states else "partially_provisional" if PROVISIONAL in states else UNVERIFIED


def write_outputs(clips: list[dict], built: dict, out_dir: Path, review_csv: Path | None,
                  suffix: str = "", truth_path: Path | None = None, provenance: dict | None = None) -> dict[str, Path]:
    """Write events, manifest and ground truth (and the blank review sheet when review_csv is given).
    suffix/truth_path/provenance let a provisional dataset be written beside, never over, the main one."""
    out_dir.mkdir(parents=True, exist_ok=True)
    header = dict(dataset=DATASET, source_page=SOURCE_PAGE, licence=LICENCE, attribution=ATTRIBUTION,
                  label_source="CAVIAR publisher ground-truth XML; intervals derived by tanya.real_dataset",
                  verification=_overall_state(built), fps=FPS, merge_gap_sec=MERGE_GAP_SEC,
                  rules={r.category: dict(description=r.description, min_duration_sec=r.min_duration_sec)
                         for r in RULES},
                  clips=[{k: v for k, v in c.items() if k != "xml"} | {"label_frames": built["label_frames"][c["video"]]}
                         for c in clips])
    if provenance:
        header["provenance"] = provenance
    events_path = out_dir / f"caviar-events{suffix}.json"
    events_path.write_text(json.dumps(dict(header, events=built["events"], rejected_events=built["rejected"]),
                                      indent=2) + "\n", encoding="utf-8")
    manifest_path = out_dir / f"caviar-manifest{suffix}.jsonl"
    manifest_path.write_text("".join(json.dumps(r) + "\n" for r in built["rows"]), encoding="utf-8")
    truth_path = truth_path or out_dir.parent / "caviar_ground_truth.json"
    truth_path.write_text(json.dumps(dict(
        description="CAVIAR real-camera (staged) events derived from publisher labels. Each event says whether "
                    "two independent reviewers verified it (human_verified), one reviewer provisionally reviewed it "
                    "(provisional_single_reviewer), or neither (publisher_label_unverified). Rejected events are "
                    "contested regions (ignore_events), not verified negatives. Only cases with measurable=true are "
                    "scored. Not deployment accuracy.",
        attribution=ATTRIBUTION, licence=LICENCE, verification=_overall_state(built),
        **({"provenance": provenance} if provenance else {}), cases=built["cases"]), indent=2) + "\n", encoding="utf-8")
    paths = dict(events=events_path, manifest=manifest_path, ground_truth=truth_path)
    if review_csv is None:
        return paths
    review_csv.parent.mkdir(parents=True, exist_ok=True)
    with review_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(REVIEW_COLUMNS)
        for row in review_items(built):
            w.writerow([row["event_id"], row["event_key"], row["video"], row["category"], row["derived_start_sec"],
                        row["derived_end_sec"], row["rule"], "", "", "", "", ""])
    return dict(paths, review=review_csv)


def _overall_state(built: dict) -> str:
    return _combined_state({e["verification"] for spans in built["events"].values() for e in spans})


def review_items(built: dict) -> list[dict]:
    """Every derived event (including rejected ones) in a fixed order, for review sheets and pages."""
    items = [(c, e) for c, spans in built["events"].items() for e in spans] + \
            [(e["category"], e) for e in built.get("rejected", [])]
    items.sort(key=lambda ce: (ce[0], ce[1]["video"], ce[1]["derived_start_sec"]))
    return [dict(event_id=f"E{i:03d}", category=c, video=e["video"], derived_start_sec=e["derived_start_sec"],
                 derived_end_sec=e["derived_end_sec"], rule=RULE_BY_CATEGORY[c].description,
                 event_key=event_key(c, e["video"], e["derived_start_sec"], e["derived_end_sec"]))
            for i, (c, e) in enumerate(items, 1)]


def read_review(path: Path, durations: dict[str, float]) -> tuple[dict[str, dict], list[str]]:
    """One reviewer's filled sheet -> ({event_key: {verdict, start_sec, end_sec, initials, notes}}, problems)."""
    reviews, problems = {}, []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), 2):
            key = (row.get("event_key") or "").strip()
            verdict = (row.get("reviewer_verdict (confirm/adjust/reject)") or "").strip().lower()
            if not key:
                problems.append(f"line {n}: missing event_key (use a sheet generated by build_real_dataset.py)")
                continue
            if not verdict:
                continue                                  # not reviewed yet
            if verdict not in REVIEW_VERDICTS:
                problems.append(f"line {n}: verdict must be confirm, adjust or reject, not {verdict!r}")
                continue
            initials = (row.get("reviewer_initials") or "").strip()
            if not initials:
                problems.append(f"line {n}: reviewer_initials is required")
                continue
            start, end = float(row["derived_start_sec"]), float(row["derived_end_sec"])
            if verdict == "adjust":
                try:
                    start, end = float(row["verified_start_sec"]), float(row["verified_end_sec"])
                except (TypeError, ValueError):
                    problems.append(f"line {n}: adjust needs numeric verified_start_sec and verified_end_sec")
                    continue
                duration = durations.get(row.get("video", ""))
                if not 0 <= start < end or (duration is not None and end > duration + 1e-6):
                    problems.append(f"line {n}: adjusted window {start}-{end}s is outside the {duration}s video")
                    continue
            reviews[key] = dict(verdict=verdict, start_sec=start, end_sec=end, initials=initials,
                                notes=(row.get("notes") or "").strip())
    return reviews, problems


def merge_reviews(a: dict[str, dict], b: dict[str, dict], tolerance_sec: float = 1.0) -> dict[str, dict]:
    """Combine two independent reviews. Verified only when both keep the event and their boundaries
    agree within tolerance (the mean is used); rejected only when both reject; else a disagreement."""
    merged = {}
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        if ra is None or rb is None:
            merged[key] = dict(status="incomplete", reason="only one reviewer answered")
            continue
        if ra["initials"].casefold() == rb["initials"].casefold():
            raise ValueError(f"{key}: both reviews have the same initials; reviews must be independent")
        reviewers = [ra["initials"], rb["initials"]]
        kinds = {ra["verdict"] == "reject", rb["verdict"] == "reject"}
        if kinds == {True}:
            merged[key] = dict(status="rejected", reviewers=reviewers)
        elif kinds == {True, False}:
            merged[key] = dict(status="disagree", reason="one reviewer rejected the event", reviewers=reviewers)
        elif (abs(ra["start_sec"] - rb["start_sec"]) <= tolerance_sec
              and abs(ra["end_sec"] - rb["end_sec"]) <= tolerance_sec):
            merged[key] = dict(status="verified", reviewers=reviewers,
                               start_sec=round((ra["start_sec"] + rb["start_sec"]) / 2, 2),
                               end_sec=round((ra["end_sec"] + rb["end_sec"]) / 2, 2))
        else:
            merged[key] = dict(status="disagree", reviewers=reviewers,
                               reason=f"boundaries differ by more than {tolerance_sec} s: "
                                      f"{ra['start_sec']}-{ra['end_sec']} vs {rb['start_sec']}-{rb['end_sec']}")
    return merged


def validate_manifest_rows(rows: list[dict], durations: dict[str, float]) -> list[str]:
    """Problems in manifest rows (empty list = valid): required fields, bounds, present/absent consistency."""
    required = ("clip_id", "dataset", "relative_path", "duration_sec", "resolution", "licence", "query",
                "query_kind", "split", "annotation_confidence")
    problems = []
    for i, r in enumerate(rows):
        missing = [k for k in required if r.get(k) in (None, "")]
        if missing:
            problems.append(f"row {i}: missing {missing}")
        start, end = r.get("event_start_sec"), r.get("event_end_sec")
        if (start is None) != (end is None):
            problems.append(f"row {i}: start/end must both be set or both empty")
        if start is not None:
            duration = durations.get(Path(r["relative_path"]).name)
            if not 0 <= start < end or (duration is not None and end > duration + 1e-6):
                problems.append(f"row {i}: event {start}-{end}s outside the {duration}s video")
            if r.get("event_present") is not True:
                problems.append(f"row {i}: has an event window but event_present is not true")
        elif r.get("event_present") is True:
            problems.append(f"row {i}: event_present is true without a window")
        if r.get("split") not in {"dev", "test"}:
            problems.append(f"row {i}: split must be dev or test")
    return problems
