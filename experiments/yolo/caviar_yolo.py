"""ISOLATED EXPERIMENT (not part of the TanyaCCTV app): pretrained YOLO person detection on CAVIAR.

Run it from its own environment outside OneDrive (see experiments/yolo/README.md), never the app's .venv:

    python experiments/yolo/caviar_yolo.py --weights %LOCALAPPDATA%\\TanyaCCTV-YOLO\\weights\\yolo26n.pt --imgsz 384

What it measures (only what the labels genuinely support):
- person DETECTION vs the CAVIAR publisher's per-frame person boxes: greedy one-to-one matching at
  IoU >= 0.5, precision/recall at a reporting confidence (default 0.25) and at several thresholds,
  AP50 over detections >= --min-conf, mean IoU of matched pairs, recall by person height;
- frame-level person PRESENCE vs (a) the publisher's per-frame boxes and (b) the provisional
  single-reviewer person_present events;
- speed, total time, first-frame latency, peak GPU memory, process memory, GPU vs CPU, failures.

Caveat measured on the footage: the publisher does not box every visible person (e.g. shoppers and
mannequins inside the shop window in EnterExitCrossingPaths1front), so precision vs these labels is a
LOWER BOUND; unmatched detections are saved as images for manual inspection.

It does NOT detect walking, entering/leaving, meeting or falling: a box per frame says nothing about
motion or posture over time. Those need temporal logic, pose estimation or an action-recognition model.

Offline by construction: YOLO_OFFLINE=1 (no Ultralytics analytics or online checks),
YOLO_AUTOINSTALL=False, settings sync=False, a socket guard that blocks and counts every outbound
connection attempt, weights only from a local file, boxes drawn with OpenCV (no font download).
Results go outside OneDrive by default.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAVIAR = ROOT / "data" / "cctv_validation" / "caviar"
PROVISIONAL_EVENTS = ROOT / "evaluation" / "provisional" / "caviar-events.provisional_single_reviewer.json"
FPS = 25.0
PERSON = 0                      # COCO class id
IOU_THRESHOLD = 0.5
PR_THRESHOLDS = (0.10, 0.25, 0.40, 0.50, 0.70)
SIZE_BUCKETS = ((0, 30, "small (<30 px tall)"), (30, 60, "medium (30-60 px)"), (60, 10_000, "large (>=60 px)"))
DEFAULT_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "TanyaCCTV-YOLO"


# --------------------------------------------------------------------------- pure helpers (unit-tested)


def iou(a, b) -> float:
    """IoU of two boxes (x1, y1, x2, y2)."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def publisher_boxes(xml_path: Path) -> dict[int, list[tuple]]:
    """{frame: [(x1, y1, x2, y2), ...]} from CAVIAR ground truth (box centre/size -> corners)."""
    out = {}
    for frame in ET.parse(xml_path).getroot().iter("frame"):
        boxes = []
        for obj in frame.iter("object"):
            b = obj.find("box")
            xc, yc, w, h = (float(b.get(k)) for k in ("xc", "yc", "w", "h"))
            boxes.append((xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2))
        out[int(frame.get("number"))] = boxes
    return out


def match_frame(dets: list[tuple], gts: list[tuple], conf: float, thr: float = IOU_THRESHOLD) -> dict:
    """Greedy one-to-one matching in descending confidence. dets: (x1, y1, x2, y2, score).

    Returns tp, fp, matched IoUs, indices of matched/missed ground-truth boxes, unmatched detections."""
    used, tp, ious, unmatched, hits = {}, 0, [], [], []
    for d in sorted((d for d in dets if d[4] >= conf), key=lambda d: -d[4]):
        best, best_iou = None, thr
        for i, g in enumerate(gts):
            if i not in used and (v := iou(d[:4], g)) >= best_iou:
                best, best_iou = i, v
        if best is None:
            unmatched.append(d)
        else:
            used[best] = d
            tp += 1
            ious.append(best_iou)
            hits.append(d)
    return dict(tp=tp, fp=len(unmatched), ious=ious, matched=sorted(used), matched_dets=hits, unmatched=unmatched,
                missed=[i for i in range(len(gts)) if i not in used])


def size_bucket(box) -> str:
    h = box[3] - box[1]
    return next(name for lo, hi, name in SIZE_BUCKETS if lo <= h < hi)


def detection_summary(per_frame: dict[int, list[tuple]], gt: dict[int, list[tuple]], conf: float) -> dict:
    """Precision/recall/mean IoU of person boxes vs publisher boxes, on frames that have labels."""
    tp = fp = 0
    ious = []
    by_size = {name: [0, 0] for _, _, name in SIZE_BUCKETS}          # [found, total]
    for f, gts in gt.items():
        m = match_frame(per_frame.get(f, []), gts, conf)
        tp, fp, ious = tp + m["tp"], fp + m["fp"], ious + m["ious"]
        for i, g in enumerate(gts):
            by_size[size_bucket(g)][1] += 1
            by_size[size_bucket(g)][0] += i in m["matched"]
    total = sum(len(v) for v in gt.values())
    return dict(conf=conf, iou_threshold=IOU_THRESHOLD, labelled_frames=len(gt), gt_boxes=total, tp=tp, fp=fp,
                fn=total - tp, precision=round(tp / (tp + fp), 3) if tp + fp else None,
                recall=round(tp / total, 3) if total else None,
                mean_iou_matched=round(statistics.mean(ious), 3) if ious else None,
                recall_by_size={k: dict(found=v[0], total=v[1], recall=round(v[0] / v[1], 3) if v[1] else None)
                                for k, v in by_size.items()})


def average_precision(per_frame: dict[int, list[tuple]], gt: dict[int, list[tuple]], min_conf: float) -> float | None:
    """AP at IoU 0.5 (all-point interpolation) over detections >= min_conf. Detections below min_conf were
    never recorded, so this is a truncated AP and slightly lower than a full-range AP."""
    scored, total = [], sum(len(v) for v in gt.values())
    for f, gts in gt.items():
        m = match_frame(per_frame.get(f, []), gts, min_conf)
        scored += [(d[4], 1) for d in m["matched_dets"]] + [(d[4], 0) for d in m["unmatched"]]
    if not total or not scored:
        return None
    scored.sort(key=lambda s: -s[0])
    tp = fp = 0
    points = []
    for _, hit in scored:
        tp, fp = tp + hit, fp + (1 - hit)
        points.append((tp / total, tp / (tp + fp)))
    ap, prev_r = 0.0, 0.0
    for i, (r, _) in enumerate(points):
        p_interp = max(p for _, p in points[i:])
        ap += (r - prev_r) * p_interp
        prev_r = r
    return round(ap, 3)


def presence_agreement(has_person: list[bool], reference: list[bool]) -> dict:
    """Frame-level agreement between 'YOLO saw a person' and a reference per-frame presence flag."""
    pos = [h for h, r in zip(has_person, reference) if r]
    neg = [h for h, r in zip(has_person, reference) if not r]
    return dict(frames=len(reference), reference_present=len(pos), reference_absent=len(neg),
                present_recall=round(sum(pos) / len(pos), 3) if pos else None,
                absent_false_alarm_rate=round(sum(neg) / len(neg), 3) if neg else None)


def intervals_to_flags(n_frames: int, intervals: list[tuple[float, float]], fps: float = FPS) -> list[bool]:
    return [any(a <= i / fps < b for a, b in intervals) for i in range(n_frames)]


class NetworkGuard:
    """Blocks and counts outbound connections and DNS lookups while active (the experiment needs none)."""

    def __init__(self):
        self.attempts: list[str] = []
        self._saved = None

    def __enter__(self):
        self._saved = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.create_connection)

        def refuse(kind):
            def blocked(*args, **kwargs):
                target = args[1] if kind.startswith("socket") and len(args) > 1 else (args[0] if args else "?")
                self.attempts.append(f"{kind}:{target}")
                raise OSError(f"network blocked by the TanyaCCTV YOLO experiment ({kind})")
            return blocked
        socket.socket.connect = refuse("socket.connect")
        socket.socket.connect_ex = refuse("socket.connect_ex")
        socket.getaddrinfo = refuse("getaddrinfo")
        socket.create_connection = refuse("create_connection")
        return self

    def __exit__(self, *exc):
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.create_connection = self._saved
        return False


# --------------------------------------------------------------------------- experiment


def offline_guards():
    os.environ["YOLO_OFFLINE"] = "1"            # Ultralytics treats itself as offline: no analytics events
    os.environ["YOLO_AUTOINSTALL"] = "False"    # never pip-install anything at runtime (default is True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(DEFAULT_HOME / "config"))   # settings stay in the experiment folder
    from ultralytics.utils import SETTINGS
    SETTINGS.update({"sync": False})            # analytics opt-out persisted in Ultralytics' own settings
    from ultralytics.utils.events import events
    if getattr(events, "enabled", False):
        raise SystemExit("Refusing to run: Ultralytics usage events are still enabled.")


def draw(frame, dets, conf, gts=None, match=None):
    """Yellow = detection; with gts: green = matched publisher box, red = missed publisher box."""
    import cv2
    if gts is not None and match is not None:
        for i, g in enumerate(gts):
            colour = (0, 200, 0) if i in match["matched"] else (0, 0, 255)
            cv2.rectangle(frame, (int(g[0]), int(g[1])), (int(g[2]), int(g[3])), colour, 1)
    for x1, y1, x2, y2, s in dets:
        if s >= conf:
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 220, 255), 1)
            cv2.putText(frame, f"{s:.2f}", (int(x1), max(9, int(y1) - 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.35,
                        (0, 220, 255), 1, cv2.LINE_AA)
    return frame


def expected_frames() -> dict[str, int]:
    media = CAVIAR / "media-manifest.json"
    return {m["filename"]: m["decoded_frames"] for m in json.loads(media.read_text(encoding="utf-8"))} if media.is_file() else {}


def run(args, guard: NetworkGuard) -> dict:
    offline_guards()
    import cv2
    import psutil
    import torch
    from ultralytics import YOLO

    if not args.weights.is_file():
        raise SystemExit(f"Weights file not found: {args.weights} (it is never downloaded automatically)")
    device = args.device or ("cuda:0" if torch.cuda.is_available() else "cpu")
    t_load = time.perf_counter()
    model = YOLO(str(args.weights))
    load_seconds = time.perf_counter() - t_load
    out = args.out
    (out / "samples").mkdir(parents=True, exist_ok=True)
    (out / "inspect").mkdir(parents=True, exist_ok=True)
    provisional = json.loads(PROVISIONAL_EVENTS.read_text(encoding="utf-8")) if PROVISIONAL_EVENTS.is_file() else None
    expected = expected_frames()
    proc = psutil.Process()
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    report = dict(environment=dict(python=platform.python_version(), torch=torch.__version__,
                                   ultralytics=__import__("ultralytics").__version__,
                                   cuda_available=torch.cuda.is_available(),
                                   gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                                   device_used=device, weights=args.weights.name, imgsz=args.imgsz, batch=1,
                                   half=args.half, conf_reported=args.conf, conf_recorded=args.min_conf,
                                   iou_threshold=IOU_THRESHOLD, model_load_seconds=round(load_seconds, 2)),
                  clips=[], errors=[])
    all_times, first_frame = [], None
    totals_gt, totals_det = {}, {}
    for video in sorted((CAVIAR / "videos").glob("*.mp4")):
        name = video.stem
        try:
            cap = cv2.VideoCapture(str(video))
            if not cap.isOpened():
                raise RuntimeError("OpenCV could not open the video")
            per_frame, has_person, times, i = {}, [], [], 0
            gt_all = publisher_boxes(CAVIAR / "annotations" / f"{name}.xml")
            inspect_budget = args.inspect_frames
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                t0 = time.perf_counter()
                # half is passed only when requested: Ultralytics 8.4.183 warns on every call that uses it.
                extra = {"half": True} if args.half else {}
                r = model.predict(frame, imgsz=args.imgsz, conf=args.min_conf, classes=[PERSON], device=device,
                                  verbose=False, **extra)[0]
                if device.startswith("cuda"):
                    torch.cuda.synchronize()
                dt = time.perf_counter() - t0
                times.append(dt)
                if first_frame is None:
                    first_frame = dt
                    # The device inference really ran on (Ultralytics keeps a separate copy for prediction).
                    predictor = getattr(model, "predictor", None)
                    report["environment"]["inference_device"] = str(getattr(predictor, "device", device))
                boxes = r.boxes
                dets = ([(*map(float, b), float(c)) for b, c in zip(boxes.xyxy.tolist(), boxes.conf.tolist())]
                        if boxes is not None else [])
                per_frame[i] = dets
                has_person.append(any(d[4] >= args.conf for d in dets))
                if i % int(args.sample_every * FPS) == 0:
                    cv2.imwrite(str(out / "samples" / f"{name}_{i:05d}_{i / FPS:06.2f}s.jpg"),
                                draw(frame.copy(), dets, args.conf))
                if inspect_budget and i in gt_all:
                    m = match_frame(dets, gt_all[i], args.conf)
                    if m["fp"] or m["missed"]:
                        if i % 25 == 0:          # at most one inspection image per second of video
                            inspect_budget -= 1
                            cv2.imwrite(str(out / "inspect" / f"{name}_{i:05d}_fp{m['fp']}_miss{len(m['missed'])}.jpg"),
                                        draw(frame.copy(), dets, args.conf, gt_all[i], m))
                i += 1
            cap.release()
            if i == 0:
                raise RuntimeError("no frames decoded")
            gt = {f: b for f, b in gt_all.items() if f < i}
            totals_gt.update({(name, f): b for f, b in gt.items()})
            totals_det.update({(name, f): d for f, d in per_frame.items()})
            pub_presence = [bool(gt.get(f)) for f in range(i)]
            labelled = [f in gt for f in range(i)]
            presence = dict(vs_publisher_boxes=presence_agreement(
                [h for h, lab in zip(has_person, labelled) if lab], [p for p, lab in zip(pub_presence, labelled) if lab]))
            if provisional:
                spans = [(e["start_sec"], e["end_sec"]) for e in provisional["events"].get("person_present", [])
                         if e["video"] == video.name]
                presence["vs_provisional_review"] = presence_agreement(has_person, intervals_to_flags(i, spans))
            confs = [d[4] for ds in per_frame.values() for d in ds if d[4] >= args.conf]
            all_times += times
            report["clips"].append(dict(
                video=video.name, frames=i, expected_frames=expected.get(video.name),
                skipped_frames=(expected[video.name] - i) if video.name in expected else None,
                detections=len(confs), frames_with_person=sum(has_person),
                confidence=dict(mean=round(statistics.mean(confs), 3), median=round(statistics.median(confs), 3),
                                min=round(min(confs), 3), max=round(max(confs), 3)) if confs else None,
                fps=round(i / sum(times), 1), seconds=round(sum(times), 2),
                detection_vs_publisher_boxes=detection_summary(per_frame, gt, args.conf),
                ap50=average_precision(per_frame, gt, args.min_conf),
                presence=presence))
            (out / f"{name}_detections.json").write_text(json.dumps([
                dict(frame=f, t=round(f / FPS, 2), boxes=[[round(v, 1) for v in d[:4]] + [round(d[4], 3)] for d in ds])
                for f, ds in per_frame.items()]), encoding="utf-8")
        except Exception as error:                                        # recorded, never hidden
            oom = "out of memory" in str(error).lower()
            report["errors"].append(dict(video=video.name, error=f"{type(error).__name__}: {error}"[:500],
                                         out_of_memory=oom))
            if oom and device.startswith("cuda"):
                torch.cuda.empty_cache()
    gt_keys, det_keys = totals_gt, totals_det        # keyed by (clip, frame) so clips never mix
    report["overall_detection"] = {f"conf_{c:.2f}": detection_summary(det_keys, gt_keys, c) for c in PR_THRESHOLDS
                                   if c >= args.min_conf}
    report["overall_ap50"] = average_precision(det_keys, gt_keys, args.min_conf)
    steady = sorted(all_times[1:]) if len(all_times) > 1 else all_times
    report["totals"] = dict(
        videos_ok=len(report["clips"]), videos_failed=len(report["errors"]),
        frames=sum(c["frames"] for c in report["clips"]),
        skipped_frames=sum(c["skipped_frames"] or 0 for c in report["clips"]),
        detections=sum(c["detections"] for c in report["clips"]),
        seconds=round(sum(all_times), 2), fps=round(len(all_times) / sum(all_times), 1) if all_times else None,
        steady_fps_median=round(1 / statistics.median(steady), 1) if steady else None,
        first_frame_ms=round(first_frame * 1000, 1) if first_frame else None,
        peak_gpu_allocated_mb=round(torch.cuda.max_memory_allocated() / 2**20, 1) if device.startswith("cuda") else None,
        peak_gpu_reserved_mb=round(torch.cuda.max_memory_reserved() / 2**20, 1) if device.startswith("cuda") else None,
        process_rss_mb=round(proc.memory_info().rss / 2**20, 1),
        network_attempts_blocked=len(guard.attempts), network_attempt_targets=guard.attempts[:10])
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(markdown_report(report), encoding="utf-8")
    return report


def markdown_report(r: dict) -> str:
    e, t = r["environment"], r["totals"]
    lines = [f"# YOLO person detection on CAVIAR ({e['weights']}, imgsz {e['imgsz']})", "",
             f"Device requested **{e['device_used']}**, inference ran on **{e.get('inference_device', '?')}** ({e['gpu'] or 'CPU'}), torch {e['torch']}, ultralytics {e['ultralytics']}, "
             f"batch 1, half={e['half']}. Reported confidence >= {e['conf_reported']}; matching IoU >= {e['iou_threshold']}.",
             "", f"- Videos: {t['videos_ok']} ok, {t['videos_failed']} failed; frames {t['frames']} "
             f"(skipped {t['skipped_frames']}); detections {t['detections']}",
             f"- Speed: {t['fps']} fps overall, {t['steady_fps_median']} fps steady (median), first frame "
             f"{t['first_frame_ms']} ms, total {t['seconds']} s",
             f"- Memory: peak GPU allocated {t['peak_gpu_allocated_mb']} MB (reserved {t['peak_gpu_reserved_mb']} MB), "
             f"process {t['process_rss_mb']} MB",
             f"- Network attempts blocked: {t['network_attempts_blocked']}", "",
             "## Person detection vs publisher boxes (all clips)", "",
             "| Confidence | Precision | Recall | TP | FP | FN | Mean IoU (matched) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, s in r["overall_detection"].items():
        lines.append(f"| {s['conf']:.2f} | {s['precision']} | {s['recall']} | {s['tp']} | {s['fp']} | {s['fn']} | {s['mean_iou_matched']} |")
    lines += ["", f"AP50 over detections >= {e['conf_recorded']}: {r['overall_ap50']} (truncated; see script notes)", "",
              "Precision is a lower bound: unannotated people (and mannequins) visible in the footage count as false positives.",
              "", "## Per clip (confidence " + str(e["conf_reported"]) + ")", "",
              "| Clip | Frames | fps | Precision | Recall | Recall small/medium/large | Presence recall (publisher) | False presence (publisher) |",
              "|---|---:|---:|---:|---:|---|---:|---:|"]
    for c in r["clips"]:
        d, p = c["detection_vs_publisher_boxes"], c["presence"]["vs_publisher_boxes"]
        sizes = "/".join(str(v["recall"]) for v in d["recall_by_size"].values())
        lines.append(f"| {c['video']} | {c['frames']} | {c['fps']} | {d['precision']} | {d['recall']} | {sizes} | "
                     f"{p['present_recall']} | {p['absent_false_alarm_rate']} |")
    if r["errors"]:
        lines += ["", "## Errors", ""] + [f"- {x['video']}: {x['error']}" for x in r["errors"]]
    lines += ["", "Person detection is not activity recognition: walking, entering, meeting or falling are not measured here."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--weights", type=Path, required=True, help="local .pt file (never downloaded by name)")
    p.add_argument("--imgsz", type=int, default=384, help="inference size; CAVIAR frames are 384x288")
    p.add_argument("--conf", type=float, default=0.25, help="confidence used for reported detections")
    p.add_argument("--min-conf", type=float, default=0.10, help="lowest confidence recorded in the raw files")
    p.add_argument("--device", default=None, help="cuda:0 or cpu (default: GPU if available)")
    p.add_argument("--half", action="store_true", help="FP16 on GPU (lower memory); default FP32")
    p.add_argument("--sample-every", type=float, default=5.0, help="seconds between saved annotated frames")
    p.add_argument("--inspect-frames", type=int, default=6, help="per clip: frames with misses/unmatched detections saved")
    p.add_argument("--out", type=Path, default=None, help=f"default: {DEFAULT_HOME}\\results-<imgsz>")
    p.add_argument("--allow-onedrive", action="store_true", help="permit an output folder inside OneDrive")
    args = p.parse_args(argv)
    args.out = args.out or DEFAULT_HOME / f"results-{args.imgsz}"
    if "onedrive" in str(args.out.resolve()).lower() and not args.allow_onedrive:
        print("Refusing: the output folder is inside OneDrive, which would upload annotated footage. "
              "Choose a local folder or pass --allow-onedrive.", file=sys.stderr)
        return 2
    with NetworkGuard() as guard:
        report = run(args, guard)
    t = report["totals"]
    print(json.dumps(dict(device=report["environment"]["device_used"], **{k: v for k, v in t.items()
                                                                          if k != "network_attempt_targets"}), indent=2))
    print(f"results: {args.out / 'results.json'}\nreport:  {args.out / 'report.md'}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
