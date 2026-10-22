"""CAVIAR review page: seeking, exact time readout, timestamp alignment, invalid input, local server.

The "00:25" report: E002 starts at 26.20 s, so "1 s before start" is 25.20 s, which the browser's
own clock shows as 0:25 (whole seconds). Browser checks showed video time n/25 displays label frame
n exactly. These tests pin that behaviour so a real offset or rounding bug cannot slip in.
"""
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tanya import real_dataset
from tests.test_label_review import fill, workspace  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
import build_real_dataset  # noqa: E402

CAVIAR = ROOT / "data" / "cctv_validation" / "caviar"
NODE = shutil.which("node")


def page_script(built, tmp_path) -> str:
    page = build_real_dataset.review_page(built, tmp_path / "review")
    return re.search(r"<script>(.*)</script>", page.read_text(encoding="utf-8"), re.S).group(1)


def run_node(script: str, checks: str):
    """Run the page's pure helpers (FPS, seekTarget, readout) with assertions, without a DOM."""
    helpers = re.search(r"const FPS = .*?\n(?=// Each reviewer)", script, re.S).group(0)
    subprocess.run([NODE, "-e", helpers + "\nconst assert = require('node:assert/strict');\n" + checks],
                   check=True, capture_output=True, text=True)


@pytest.mark.skipif(not NODE, reason="Node is optional; the page was checked in a browser")
def test_seek_target_is_one_second_before_start_and_clamped(workspace, tmp_path):  # noqa: F811
    _, _, built = workspace
    run_node(page_script(built, tmp_path), r"""
assert.equal(FPS, 25);
assert.equal(seekTarget(26.2), 25.2);          // the reported "0:25" case: correct, not an offset
assert.equal(seekTarget(21.92), 20.92);
assert.equal(seekTarget(9.44), 8.44);
assert.equal(seekTarget("3.2"), 2.2);          // numbers arriving as text
assert.equal(seekTarget(0), 0);                // events at the very start of a clip
assert.equal(seekTarget(0.68), 0);             // less than 1 s in: clamp to 0, never negative
assert.equal(seekTarget(26.2, 20), 19.96);     // never past the last frame
assert.equal(seekTarget(26.2, NaN), 25.2);     // duration not loaded yet: no clamping
for (const bad of [null, undefined, "", "abc", NaN, Infinity, -1]) assert.equal(seekTarget(bad), null);
""")


@pytest.mark.skipif(not NODE, reason="Node is optional; the page was checked in a browser")
def test_readout_shows_exact_time_and_label_frame(workspace, tmp_path):  # noqa: F811
    _, _, built = workspace
    run_node(page_script(built, tmp_path), r"""
assert.equal(readout(25.2), "Video time 25.20 s · frame 630");
assert.equal(readout(26.2), "Video time 26.20 s · frame 655");
assert.equal(readout(0), "Video time 0.00 s · frame 0");
assert.equal(readout(NaN), "Video time –");
""")


def test_page_embeds_every_event_with_valid_start_and_its_sheet(workspace, tmp_path):  # noqa: F811
    _, _, built = workspace
    script = page_script(built, tmp_path)
    events = json.loads(re.search(r"const EVENTS = (\[.*?\]);", script, re.S).group(1).replace("<\\/", "</"))
    assert len(events) == len(real_dataset.review_items(built))
    for e in events:
        assert e["sheet"].endswith(".jpg") and e["derived_start_sec"] < e["derived_end_sec"]
        assert e["event_key"] == real_dataset.event_key(e["category"], e["video"], e["derived_start_sec"],
                                                        e["derived_end_sec"])
    assert '"Play from 1 s before start")' not in script    # old vague label (shown as "0:25") is gone
    assert '" s (1 s before the "' in script                  # the label states the exact seek time


def test_review_csv_rejects_backwards_and_non_numeric_adjustments(workspace, tmp_path):  # noqa: F811
    root, _, _ = workspace
    sheet = root / "evaluation/review/caviar-review.csv"
    for start, end, needle in (("4", "3", "outside"), ("x", "5", "numeric"), ("", "5", "numeric"), ("-1", "2", "outside")):
        bad = fill(sheet, tmp_path / "bad.csv", "AB", {"fallen": ("adjust", start, end)})
        problems = real_dataset.read_review(bad, {"Clip.mp4": 6.0})[1]
        assert problems and needle in problems[0], (start, end, problems)


def test_review_server_serves_page_and_ranged_video_only(tmp_path):
    folder = tmp_path / "caviar"
    (folder / "review").mkdir(parents=True)
    (folder / "videos").mkdir()
    (folder / "annotations").mkdir()
    (folder / "review/review.html").write_text("<p>ok</p>", encoding="utf-8")
    (folder / "videos/a.mp4").write_bytes(bytes(range(256)) * 4)
    (folder / "annotations/a.xml").write_text("<x/>", encoding="utf-8")
    (folder / "videos.db").write_bytes(b"db")
    client = build_real_dataset.review_app(folder).test_client()
    assert client.get("/").headers["Location"].endswith("/review/review.html")
    assert client.get("/review/review.html").status_code == 200
    ranged = client.get("/videos/a.mp4", headers={"Range": "bytes=10-19"})
    assert ranged.status_code == 206 and ranged.data == bytes(range(10, 20))   # seeking needs byte ranges
    for path in ("/annotations/a.xml", "/videos.db", "/videos/..%2fvideos.db", "/review/../videos.db"):
        assert client.get(path).status_code == 404, path


# --------------------------------------------------------------------------- real footage (skips if absent)

needs_caviar = pytest.mark.skipif(not (CAVIAR / "media-manifest.json").is_file(),
                                  reason="CAVIAR footage not downloaded/prepared on this machine")


@needs_caviar
def test_events_sit_on_frame_boundaries_inside_their_videos():
    data = json.loads((ROOT / "evaluation/datasets/caviar-events.json").read_text(encoding="utf-8"))
    durations = {c["video"]: c["duration_sec"] for c in data["clips"]}
    for spans in data["events"].values():
        for e in spans:
            for t in (e["derived_start_sec"], e["derived_end_sec"]):
                assert abs(t * real_dataset.FPS - round(t * real_dataset.FPS)) < 1e-6, e     # whole frames
            assert 0 <= e["start_sec"] < e["end_sec"] <= durations[e["video"]] + 1e-6


@needs_caviar
def test_prepared_copies_keep_label_frame_numbering():
    """Label frame n = prepared-copy frame n = original MPEG frame n, at 25 fps from time 0."""
    import cv2
    plan = json.loads((ROOT / "evaluation/datasets/caviar-small.json").read_text(encoding="utf-8"))
    media = {m["filename"]: m for m in json.loads((CAVIAR / "media-manifest.json").read_text(encoding="utf-8"))}
    for clip in plan["clips"]:
        m = media[clip["name"] + ".mp4"]
        assert m["fps"] == real_dataset.FPS and m["decoded_frames"] - clip["annotation_frames"] in (0, 1)
        cap = cv2.VideoCapture(str(CAVIAR / "videos" / (clip["name"] + ".mp4")))
        try:
            ok, _ = cap.read()
            assert ok and cap.get(cv2.CAP_PROP_POS_MSEC) == 0          # first frame at 0 s: no start offset
        finally:
            cap.release()

    def grey(path, lo, hi):
        cap, out, i = cv2.VideoCapture(str(path)), {}, 0
        while i <= hi:
            ok, f = cap.read()
            if not ok:
                break
            if i >= lo:
                out[i] = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype("int16")
            i += 1
        cap.release()
        return out
    for name, n in (("Rest_FallOnFloor", 655), ("Browse2", 548), ("Walk1", 236)):     # E002, E001 and a walk start
        orig = grey(CAVIAR / "originals" / f"{name}.mpg", n, n)[n]
        prepared = grey(CAVIAR / "videos" / f"{name}.mp4", n - 2, n + 2)
        diffs = {k: abs(f - orig).mean() for k, f in prepared.items()}
        assert min(diffs, key=diffs.get) == n, (name, n, diffs)


@needs_caviar
def test_committed_review_sheet_matches_current_events():
    rows = list(csv.DictReader((ROOT / "evaluation/review/caviar-review.csv").open(encoding="utf-8")))
    clips = real_dataset.load_clips(CAVIAR, ROOT / "evaluation/datasets/caviar-small.json")
    items = real_dataset.review_items(real_dataset.build(clips))
    assert [r["event_key"] for r in rows] == [i["event_key"] for i in items] and len(rows) == 33
