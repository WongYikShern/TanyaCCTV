# Isolated YOLO experiment (not part of the TanyaCCTV app)

Pretrained person detection on the five CAVIAR clips, to judge whether a local detector could
support TanyaCCTV's natural-language search. Nothing here changes the app, its `.venv`, its search
engine or its UI. Status (20 October 2026): **approved, installed and run** (see Results). Note:
because the Claude desktop app is a packaged Windows app, `%LOCALAPPDATA%\TanyaCCTV-YOLO` created
from inside it is stored physically under
`%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\TanyaCCTV-YOLO` (4.5 GB), still local and
outside OneDrive; resetting or uninstalling the app removes it.

## Licence (read before any product use)

Ultralytics 8.4.183, its helper packages `ultralytics-thop` and `ultralytics-platform`, and the
pretrained YOLO weights are **AGPL-3.0**. Using them in a networked or distributed product requires
publishing that product's complete source under AGPL-3.0, or buying an Ultralytics Enterprise
licence. Local research like this experiment is fine. Permissively licensed alternatives exist
(torchvision detectors, BSD-3; YOLOX or RT-DETR, Apache-2.0) and would need their own evaluation.

## Location

Everything (environment, weights, settings, temporary files, results) goes in
`%LOCALAPPDATA%\TanyaCCTV-YOLO` (`C:\Users\<you>\AppData\Local\TanyaCCTV-YOLO`), which OneDrive does
not sync. The project folder itself is OneDrive-synced, so nothing large or derived from footage is
written there. Drive C: had 14.6 GB free when this plan was made.

## Original setup plan (already run on the teammate's Windows laptop)

The results below came from that existing installation. These commands are retained for
reproduction, not instructions to reinstall or redownload. First locate the environment,
weights and cached results; transferring code through Git does not transfer those files.

| Item | Source | Download | Installed |
|---|---|---|---|
| Python 3.11.5 virtual environment | already installed | 0 | ~0.05 GB |
| torch 2.14.1+cu126, torchvision 0.29.1+cu126 (driver 566.36 supports CUDA ≤ 12.7) | download.pytorch.org | ~2.65 GB incl. deps | ~5.5 GB |
| ultralytics 8.4.183 and its dependencies (opencv-python, numpy, matplotlib, polars, …) | PyPI | ~0.15 GB | ~0.5 GB |
| `yolo26n.pt`, SHA-256 `9b09cc8b…8ad4fef` | github.com/ultralytics/assets v8.4.0 | 5.5 MB | 5.5 MB |

Peak during installation ≈ 8.6 GB (installed files plus the 2.6 GB wheel being unpacked), leaving
about 6 GB free; after installation about 8.4 GB free. `--no-cache-dir` keeps pip from keeping a
second copy. The same environment can also run on the CPU (`--device cpu`) for a comparison.

```powershell
$Y = "$env:LOCALAPPDATA\TanyaCCTV-YOLO"
New-Item -ItemType Directory -Force "$Y\weights", "$Y\tmp", "$Y\config" | Out-Null
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv "$Y\venv"
$env:TMP = "$Y\tmp"; $env:TEMP = "$Y\tmp"
& "$Y\venv\Scripts\python.exe" -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu126 torch==2.14.1+cu126 torchvision==0.29.1+cu126
& "$Y\venv\Scripts\python.exe" -m pip install --no-cache-dir ultralytics==8.4.183
Invoke-WebRequest https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt -OutFile "$Y\weights\yolo26n.pt"
(Get-FileHash "$Y\weights\yolo26n.pt" -Algorithm SHA256).Hash   # must be 9B09CC8BF347F0FC8A5F7657480587F25DB09B34BF33B0652110FB03A8AD4FEF
```

## Offline safeguards built into `caviar_yolo.py`

Read from the Ultralytics 8.4.183 source: by default it sends usage analytics to Google Analytics
(`sync: True`), checks connectivity by DNS, downloads fonts when drawing, downloads weights by name
and pip-installs missing packages (`YOLO_AUTOINSTALL` defaults to True). Before importing
Ultralytics the script sets `YOLO_OFFLINE=1`, `YOLO_AUTOINSTALL=False` and `YOLO_CONFIG_DIR` (inside
the experiment folder), then sets `sync=False` and refuses to run if analytics are still enabled.
A socket guard blocks and counts every outbound connection or DNS lookup during the whole run (the
report shows the count; it must be 0). Weights load only from a local file; boxes are drawn with
OpenCV; results are refused inside OneDrive.

## Run (after approval)

```powershell
$Y = "$env:LOCALAPPDATA\TanyaCCTV-YOLO"
& "$Y\venv\Scripts\python.exe" experiments\yolo\caviar_yolo.py --weights "$Y\weights\yolo26n.pt" --imgsz 384
& "$Y\venv\Scripts\python.exe" experiments\yolo\caviar_yolo.py --weights "$Y\weights\yolo26n.pt" --imgsz 640
& "$Y\venv\Scripts\python.exe" experiments\yolo\caviar_yolo.py --weights "$Y\weights\yolo26n.pt" --imgsz 384 --device cpu --out "$Y\results-384-cpu"
```

Batch 1 (one frame at a time), FP32, reporting confidence 0.25 (raw detections down to 0.10 are
kept), matching IoU ≥ 0.5. The 640 run happens only if the 384 run leaves enough GPU memory free.

## What it measures, and what it cannot

- Person **detection** vs the CAVIAR publisher's per-frame boxes: 5,572 boxes on 3,259 labelled
  frames, 2,204 (39.6%) under 30 px tall. The publisher does not box every visible person (e.g.
  shoppers and mannequins inside the shop window), so precision is a **lower bound**; unmatched
  detections are saved under `inspect\` for manual checking.
- Frame-level person presence vs the publisher's boxes and vs the provisional single-reviewer
  `person_present` events.
- Speed (overall and steady fps, first-frame latency), total time, peak GPU memory, process memory,
  GPU vs CPU, skipped frames, failed videos, blocked network attempts.

A detector outputs boxes per frame. It does **not** recognise walking, standing still, entering or
leaving a shop, meeting, fighting or falling. Those need temporal logic over tracked boxes
(walking/standing: track speed; entering/exiting: crossing a door line), pose estimation (falls,
lying), or an action-recognition model (fighting), each needing its own labelled evaluation.

## Results (20 October 2026; yolo26n.pt, batch 1, FP32, confidence 0.25, IoU 0.5)

All five clips, 3,262 frames, 0 skipped, 0 failed, **0 network attempts** in every run. Full
per-clip reports, raw detections, samples and inspection images are in `%LOCALAPPDATA%\TanyaCCTV-YOLO`.

| Run | Speed | Peak GPU | Precision* | Recall | Recall small / medium / large | Person-present frames found |
|---|---|---:|---:|---:|---|---:|
| GPU, 384 px | 38–43 fps (two runs) | 51 MB | 0.85 | 0.31 | 0.00 / 0.34 / 0.86 | 30% |
| GPU, 640 px | 43.5 fps | 70 MB | 0.64 | 0.41 | 0.01 / 0.56 / 0.88 | 56% |
| CPU, 384 px | 22.2 fps | – | 0.85 | 0.31 | 0.00 / 0.35 / 0.86 | 30% |

\*Lower bound: unannotated people and mannequins count as false positives.

- **By camera:** the side-on shopping corridor works well (384 px: precision 0.99, recall 0.90);
  the overhead fisheye lobby clips work poorly (Walk1 recall 0.01 at 384, 0.07 at 640), because
  people seen from above and under ~30 px are unlike the model's training images.
- **Lobby false positives** are 81–100% one fixed spot (reception desk/chairs); whether a seated,
  unannotated person is there needs a human look. A per-camera static-region mask would remove it.
- **Lying person after the staged fall:** box found in 5% of frames at 384 px, 73% at 640 px. This
  is person detection, not fall recognition.
- The GPU is barely used (≤ 70 MB): speed is limited by per-frame overhead, not the model.

## Offline confidence and region-filter analysis (no model needed)

`analyse_cached.py` reuses this experiment's `results.json` and `*_detections.json` files.
It does not import torch/Ultralytics or run inference, and uses the existing network guard.
See [continuation guide](../../docs/evaluation-next-phase.md) for commands and input/output rules.
It reports baseline/filtered precision, recall, misses and size buckets at each confidence.
Ground truth is never masked, so suppressing a genuine person counts against recall.
Without the actual saved runs, this is a tested analysis tool, not a measured improvement.

## App integration: optional person-presence candidates (21 October 2026)

`person_candidates.py` runs this experiment's detector (same offline guards and socket guard,
batch 1, FP32, person class only, local weights) on **one** video and writes detections in the
same per-frame format, plus the identity of everything that produced them: video SHA-256,
weights SHA-256, image size, confidence floor, the script's line-ending-independent SHA-256,
package versions and device. On the corridor-front clip it reproduced the saved GPU 384 run
exactly (383/383 frames identical boxes; 18 s; 51 MB peak GPU; 0 network attempts).

The app (`backend/tanya/person_detection.py`, no torch import) uses it only when a person
selects **Find people** on a video's player page. Nothing runs at start-up. Results are cached
per video/weights/image size under `<data>/person_detections/`; a cache entry for different
footage is refused and one made with different weights is shown as stale. The offline demo
reuses the saved `results-384` run for the CAVIAR clips (bound via the prepared-media manifest,
since that run did not record input hashes; its weights hash is shown as unverifiable).

Candidates are frames with a person box at confidence >= 0.40, merged across gaps <= 0.5 s and
kept when >= 0.5 s long. On the saved GPU 384 run that threshold measured precision 0.987 and
recall 0.267 against the publisher's boxes (cached recount; same footage, not held-out). They
are **person-presence candidates for human review**: never falls, fights, entries or any other
action, and missing small/overhead people is common (the staged-fall clip yields no candidate at
this threshold). The reception-region filter stays disabled: its effect was measured only
post hoc on the same footage. The detector does not recognise the cartoon synthetic people.

Setup for the app: `TANYA_YOLO_HOME` (folder with `venv\` and `weights\`), or
`TANYA_YOLO_PYTHON` and `TANYA_YOLO_WEIGHTS`. Default: `%LOCALAPPDATA%\TanyaCCTV-YOLO`. Note:
an environment created from inside the Claude desktop app (a packaged app) is stored physically
under `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Local\TanyaCCTV-YOLO`; point
`TANYA_YOLO_HOME` there when starting the website from an ordinary terminal.
