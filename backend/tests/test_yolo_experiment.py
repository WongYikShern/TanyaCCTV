"""Isolated YOLO experiment: measurement helpers only (no model, no Ultralytics/torch import)."""
import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "yolo"))
import caviar_yolo as cy  # noqa: E402


def test_importing_the_experiment_loads_no_ml_packages():
    assert "ultralytics" not in sys.modules and "torch" not in sys.modules


def test_iou():
    assert cy.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert cy.iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)
    assert cy.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_publisher_boxes_convert_centre_size_to_corners(tmp_path):
    xml = tmp_path / "t.xml"
    xml.write_text('<dataset><frame number="0"><objectlist><object id="0"><box h="20" w="10" xc="50" yc="40"/>'
                   '</object></objectlist></frame><frame number="1"><objectlist/></frame></dataset>', encoding="utf-8")
    assert cy.publisher_boxes(xml) == {0: [(45.0, 30.0, 55.0, 50.0)], 1: []}


def test_matching_is_greedy_by_confidence_and_one_to_one():
    gts = [(0, 0, 10, 20), (100, 0, 110, 20)]
    dets = [(0, 0, 10, 20, 0.9), (1, 0, 11, 20, 0.8),         # duplicate on the same person -> one FP
            (100, 0, 110, 20, 0.2),                          # below the reporting threshold -> ignored
            (300, 0, 310, 20, 0.7)]                          # nobody there -> FP
    m = cy.match_frame(dets, gts, conf=0.25)
    assert (m["tp"], m["fp"], m["matched"], m["missed"]) == (1, 2, [0], [1])
    assert m["ious"] == [1.0] and m["matched_dets"] == [(0, 0, 10, 20, 0.9)]
    assert cy.match_frame([(0, 0, 10, 20, 0.9)], [(0, 0, 10, 40)], 0.25)["tp"] == 1     # IoU exactly 0.5 matches (>=)
    assert cy.match_frame([(0, 0, 10, 20, 0.9)], [(0, 0, 10, 41)], 0.25)["tp"] == 0     # below 0.5: no match


def test_detection_summary_reports_precision_recall_iou_and_size_buckets():
    gt = {0: [(0, 0, 10, 20), (0, 0, 20, 80)], 1: [(0, 0, 10, 40)]}
    dets = {0: [(0, 0, 20, 80, 0.9)], 1: [(0, 0, 10, 40, 0.5), (50, 50, 60, 60, 0.4)]}
    s = cy.detection_summary(dets, gt, conf=0.25)
    assert (s["tp"], s["fp"], s["fn"], s["gt_boxes"]) == (2, 1, 1, 3)
    assert s["precision"] == round(2 / 3, 3) and s["recall"] == round(2 / 3, 3) and s["mean_iou_matched"] == 1.0
    assert s["recall_by_size"]["small (<30 px tall)"] == dict(found=0, total=1, recall=0.0)
    assert s["recall_by_size"]["large (>=60 px)"]["recall"] == 1.0 and s["iou_threshold"] == 0.5


def test_average_precision_hand_example():
    # 2 people; detections by score: 0.9 hit, 0.8 false, 0.7 hit -> P/R points (0.5,1), (0.5,.5), (1,.667)
    gt = {0: [(0, 0, 10, 20)], 1: [(0, 0, 10, 20)]}
    dets = {0: [(0, 0, 10, 20, 0.9), (50, 50, 60, 60, 0.8)], 1: [(0, 0, 10, 20, 0.7)]}
    assert cy.average_precision(dets, gt, 0.1) == round(0.5 * 1.0 + 0.5 * (2 / 3), 3)
    assert cy.average_precision({}, gt, 0.1) is None


def test_presence_agreement_and_interval_flags():
    flags = cy.intervals_to_flags(75, [(1.0, 2.0)])                 # 3 s at 25 fps
    assert sum(flags) == 25 and flags[25] and not flags[50]
    has_person = [False] * 25 + [True] * 25 + [True] * 10 + [False] * 15
    r = cy.presence_agreement(has_person, flags)
    assert r["reference_present"] == 25 and r["present_recall"] == 1.0
    assert r["reference_absent"] == 50 and r["absent_false_alarm_rate"] == 0.2


def test_network_guard_blocks_and_counts_connections():
    with cy.NetworkGuard() as guard:
        with pytest.raises(OSError, match="network blocked"):
            socket.create_connection(("example.com", 443), timeout=1)
        with pytest.raises(OSError, match="network blocked"):
            socket.getaddrinfo("dns.google", 0)
    assert len(guard.attempts) == 2
    assert socket.getaddrinfo.__name__ != "blocked"                    # restored afterwards


def test_default_results_location_is_outside_onedrive():
    assert "onedrive" not in str(cy.DEFAULT_HOME).lower() and cy.DEFAULT_HOME.name == "TanyaCCTV-YOLO"


def test_refuses_to_write_annotated_frames_into_onedrive(tmp_path, capsys):
    onedrive = tmp_path / "OneDrive" / "results"
    assert cy.main(["--weights", str(tmp_path / "w.pt"), "--out", str(onedrive)]) == 2
    assert "OneDrive" in capsys.readouterr().err
    assert "ultralytics" not in sys.modules                 # refused before any ML import


def test_markdown_report_states_limits():
    r = dict(environment=dict(weights="yolo26n.pt", imgsz=384, device_used="cpu", gpu=None, torch="t", ultralytics="u",
                              half=False, conf_reported=0.25, conf_recorded=0.1, iou_threshold=0.5),
             totals=dict(videos_ok=1, videos_failed=0, frames=10, skipped_frames=0, detections=3, fps=20.0,
                         steady_fps_median=21.0, first_frame_ms=90.0, seconds=0.5, peak_gpu_allocated_mb=None,
                         peak_gpu_reserved_mb=None, process_rss_mb=300.0, network_attempts_blocked=0),
             overall_detection={"conf_0.25": cy.detection_summary({}, {0: [(0, 0, 1, 1)]}, 0.25)}, overall_ap50=None,
             clips=[], errors=[])
    text = cy.markdown_report(json.loads(json.dumps(r)))
    assert "lower bound" in text and "not activity recognition" in text and "Network attempts blocked: 0" in text


def test_full_pipeline_with_fake_ml_stack_and_perfect_detector(tmp_path, monkeypatch):
    """End-to-end run() with stand-ins for ultralytics/torch/psutil: a detector that returns exactly the
    publisher boxes must score precision = recall = 1, block no network and write every output."""
    import types
    from tests.conftest import make_video
    caviar = tmp_path / "caviar"
    make_video(caviar / "videos" / "Clip.mp4", seconds=2, fps=25, size=(96, 64))
    frames = 50
    boxes = {f: [(10.0, 10.0, 30.0, 50.0)] if f >= 10 else [] for f in range(frames)}     # person from 0.4 s
    xml = ['<dataset>'] + [f'<frame number="{f}"><objectlist>' + "".join(
        f'<object id="0"><box h="{b[3]-b[1]:g}" w="{b[2]-b[0]:g}" xc="{(b[0]+b[2])/2:g}" yc="{(b[1]+b[3])/2:g}"/></object>'
        for b in boxes[f]) + '</objectlist></frame>' for f in range(frames)] + ['</dataset>']
    (caviar / "annotations").mkdir()
    (caviar / "annotations" / "Clip.xml").write_text("".join(xml), encoding="utf-8")
    (caviar / "media-manifest.json").write_text(json.dumps([dict(filename="Clip.mp4", decoded_frames=frames)]),
                                                encoding="utf-8")
    monkeypatch.setattr(cy, "CAVIAR", caviar)
    monkeypatch.setattr(cy, "PROVISIONAL_EVENTS", tmp_path / "none.json")

    counter = {"i": 0}

    class Boxes:
        def __init__(self, bs):
            self.xyxy = types.SimpleNamespace(tolist=lambda: [list(b) for b in bs])
            self.conf = types.SimpleNamespace(tolist=lambda: [0.9] * len(bs))

    class FakeYOLO:
        def __init__(self, path):
            assert Path(path).is_file()                                      # local weights only

        def predict(self, frame, **kw):
            assert kw["classes"] == [0] and kw["imgsz"] == 384
            f = counter["i"]
            counter["i"] += 1
            return [types.SimpleNamespace(boxes=Boxes(boxes[f]))]
    settings = {}
    fake_utils = types.SimpleNamespace(SETTINGS=types.SimpleNamespace(update=settings.update))
    fake_events = types.SimpleNamespace(events=types.SimpleNamespace(enabled=False))
    cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_proc = types.SimpleNamespace(memory_info=lambda: types.SimpleNamespace(rss=200 * 2**20))
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO, __version__="fake"))
    monkeypatch.setitem(sys.modules, "ultralytics.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "ultralytics.utils.events", fake_events)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda, __version__="fake"))
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(Process=lambda: fake_proc))
    weights = tmp_path / "w.pt"
    weights.write_bytes(b"x")
    out = tmp_path / "results"
    monkeypatch.setenv("YOLO_OFFLINE", "0")           # registered so the script's changes are undone afterwards
    monkeypatch.setenv("YOLO_AUTOINSTALL", "True")
    monkeypatch.setenv("YOLO_CONFIG_DIR", str(tmp_path / "cfg"))
    assert cy.main(["--weights", str(weights), "--out", str(out), "--device", "cpu"]) == 0
    env = __import__("os").environ
    assert settings == {"sync": False} and env["YOLO_OFFLINE"] == "1" and env["YOLO_AUTOINSTALL"] == "False"
    r = json.loads((out / "results.json").read_text(encoding="utf-8"))
    clip = r["clips"][0]
    assert (clip["frames"], clip["skipped_frames"], clip["detections"]) == (50, 0, 40)
    d = clip["detection_vs_publisher_boxes"]
    assert (d["precision"], d["recall"], d["mean_iou_matched"], d["fp"], d["fn"]) == (1.0, 1.0, 1.0, 0, 0)
    assert clip["presence"]["vs_publisher_boxes"] == dict(frames=50, reference_present=40, reference_absent=10,
                                                          present_recall=1.0, absent_false_alarm_rate=0.0)
    assert r["overall_ap50"] == 1.0 and r["totals"]["network_attempts_blocked"] == 0
    assert r["environment"]["device_used"] == "cpu" and r["environment"]["inference_device"] == "cpu" and r["errors"] == []
    raw = json.loads((out / "Clip_detections.json").read_text(encoding="utf-8"))
    assert raw[10] == dict(frame=10, t=0.4, boxes=[[10.0, 10.0, 30.0, 50.0, 0.9]])
    assert (out / "report.md").is_file() and list((out / "samples").glob("*.jpg"))
