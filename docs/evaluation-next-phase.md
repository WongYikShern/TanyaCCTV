# Evaluation continuation — 21 October 2026

Work continues on `integration/pr5-handover`, starting at `7e09bea`. Existing website,
CAVIAR builder/review tools, provisional workflow and YOLO experiment were reused.
No model training, footage uploads or paid inference were performed in this continuation.

## What is actually available on this Mac

- Python 3.11.9 app environment; separate SentrySearch Python environment.
- All 11 licensed prepared videos: five staged CAVIAR clips and six RainSnow traffic clips.
- Existing publisher-derived CAVIAR data: 30 scoreable unique events, 22 measurable queries
  (15 positive, seven negative), plus three unmeasured appearance/ambiguity queries.
- Existing human review page and two-reviewer merge; provisional single-reviewer script.
- YOLO source and published experiment notes, but no `yolo26n.pt`, saved detection run or
  reviewed CSV found in the project, Downloads or the checked local experiment locations.
- App Python has no torch, ultralytics or psutil. No packages were installed or downloaded.

The teammate reports 31 confirmations and two rejections. The actual CSV is needed to
reproduce that provisional dataset; this Mac must not reconstruct reviewer decisions from
that summary. The default committed benchmark still has publisher labels only. RainSnow
still needs event labels. The Windows GPU results in the YOLO README were not rerun here.

## Changes in this continuation

1. Benchmark adds individual missed-event counts/rate and per-event best IoU and boundary
   errors. Legacy `missed_event_rate` remains for compatibility and gains the explicit alias
   `no_hit_query_rate`. Timing averages include matched events only; misses are listed separately.
2. Positive false-positive windows are counted over the evaluation horizon (top five for
   ranked; all supported windows for checked modes). Negative counts are also reported.
3. Mock-injected scene runs are `source=mock`, not `live`. Replays/mocks are labelled in reports.
4. Live scan recording refuses a plan with excluded recordings, rather than treating a
   partial-library scan as complete. No live scan was executed.
5. Added `experiments/yolo/analyse_cached.py`: replay saved boxes through confidence sweeps
   and optional static-region filters. This performs no model loading or inference. It
   rejects missing/duplicate cached frames, thresholds below the recorded confidence floor,
   unknown clips, malformed boxes and failed source runs. Inputs are hash-recorded.

Scan @k follows the supplied chronological order; it is not similarity rank. Individual
scan event recall uses all supported windows. Overlapping duplicate windows cannot increase
recall for a single labelled event. None of these changes establishes better model accuracy.

## Resume with the actual review and cached detections

Ask the teammate to copy these locally (not into Git):

- `caviar-review-<initials>.csv` containing the 33 decisions.
- YOLO run folders containing `results.json` and all five `*_detections.json` files; both 384
  and 640 runs if available. Detection JSON is enough for sensitivity analysis; weights are
  unnecessary for that step.
- The existing environment/weights location on the Windows laptop for any later fresh run.

On this Mac, keep the handoff under ignored `data/cctv_validation/handoff/`.
Do not transfer credentials. Use the existing commands:

```bash
.venv/bin/python backend/scripts/prepare_provisional_benchmark.py data/cctv_validation/handoff/caviar-review-XX.csv
.venv/bin/python backend/scripts/run_benchmark.py --ground-truth evaluation/provisional/caviar_ground_truth.provisional_single_reviewer.json --events evaluation/provisional/caviar-events.provisional_single_reviewer.json
.venv/bin/python backend/scripts/build_real_dataset.py --serve-review
```

The provisional benchmark is labelled single-reviewer; it does not become independently
verified. A second person should review independently through the existing page, then use
`apply_label_review.py` to compare and reconcile disagreements. Do not copy the first review
as the second. Ground-truth disagreement is not a model false positive.

Cached YOLO analysis, once the source files exist:

```bash
.venv/bin/python experiments/yolo/analyse_cached.py --run-dir data/cctv_validation/handoff/results-384 --out data/cctv_validation/yolo-analysis-384.json
```

Optional `--regions regions.json` accepts e.g. `{"Walk1.mp4": [[0, 0, 20, 20]]}`. These are
**format examples, not recommended camera masks**. Coordinates are original-frame pixels;
boxes with centres inside these half-open rectangles are removed. The publisher's boxes
remain unchanged, so masking an actual person reduces recall. Investigate the reception-desk
false-positive area manually before defining a mask; a stationary person is not background.
Outputs must be new local files outside OneDrive, either outside the repository or inside
ignored `data/cctv_validation`. No annotation images or raw output are committed.

Compare precision, recall, small-person recall and additional misses by clip, confidence
and 384/640 source run. Cached replay cannot recover detections below the source minimum
confidence, establish new speed figures or test a new model/input resolution. The source
image sizes need genuine saved runs. Camera-specific masks and thresholds must be tuned on
development footage and checked on separate held-out footage, not chosen from test successes.

## Event understanding: experiment plan, not implemented capability

Keep this separate from the natural-language search and website:

- **Tracking prerequisite:** associate detections across frames; measure ID switches and
  track continuity. Missing small-person detections break tracks. Publisher IDs can support
  association evaluation, but must never be fed to the model as detections.
- **Entering/leaving:** define each camera's doorway/region and an oriented crossing line.
  Require a stable track crossing it with hysteresis. Label crossing direction, timestamps,
  occlusion and incomplete tracks. A track disappearing at the image edge is not proof of exit.
- **Walking/stationary:** measure sustained motion relative to person scale and camera view.
  Pixel thresholds do not transfer across depth/cameras. Evaluate starts/stops and identity
  swaps; do not call a short pause loitering without an agreed duration rule.
- **Potential fall:** person-box width/height changes alone are weak evidence, particularly
  overhead. Study posture/pose plus a standing-to-ground transition and a subsequent dwell
  interval; inspect sitting, bending, occlusion and camera perspective as hard negatives.
  Report an experimental *potential fall* candidate for human review, never confirmed fall
  detection from YOLO person detections alone. This phase implements no fall classifier.

Do not add tracking/action dependencies before inspecting detector failure cases. Fixing
small-person recall comes first. No from-scratch training is planned.

## Demo and remaining gates

The normal dashboard and investigation workflow remain as implemented. The offline demo
is a replay demonstration. YOLO is optional research and has no production UI integration.
Run existing offline demo commands from README for rehearsal, with no Gemini calls.

Remaining gates: actual CSV/cached-run transfer; independent second review; labelled
RainSnow events; approved exact Gemini scope/model/cost/quota check; genuine ranked/scan
recordings; measured baseline failures; then held-out validation of any pipeline changes.
No accuracy percentage, GPU reproduction or detector improvement is claimed from unit tests.

Validation on this Mac after the changes: **495 backend tests passed, seven skipped**
with `TANYA_SENTRY_PYTHON` set. Four skips require the old synthetic trial index, one
requires the absent local provisional dataset, and two are Windows-only junction checks.
This verifies software behaviour using fixtures/mocks, not fresh CCTV search accuracy.

## Saved-run integrity and failure review

New scene-scan recordings now include a `dataset_contract`: a canonical SHA-256 of the
complete ground-truth JSON plus declared prepared-video names, hashes and durations.
The plan prints that contract. Before any batch is sent, the recorder compares the
planned library's indexed video hashes/names to it; the existing scan also re-hashes source
files before use. Excluded recordings or mismatched footage fail instead of becoming a
successful negative. Existing live recording files cannot be overwritten through the CLI.

On scoring, a present but mismatched contract is refused. Legacy recordings without one
remain readable with an explicit **UNBOUND / identity not verified** warning. Use
`--require-bound-runs` to refuse unbound inputs. This also refuses historical replay
adapters which cannot prove the old run's identity; it never adds a current contract to
an unrelated old response. A matching contract is a consistency check, not authentication
that a run genuinely used AI. Keep original responses and approval logs.

Important cross-machine detail: this Mac's prepared MP4 byte hashes differ from some
committed Windows-prepared clip hashes. Before live approval, rebuild metadata against
the actual prepared files and confirm the publisher-frame time alignment. Do not alter
hash fields merely to silence a mismatch or treat different encodings as identical bytes.

JSON reports now include `failure_cases` for each mode: failed/unavailable queries,
individual missed events, false-positive windows and matched events with IoU below 0.5.
Inspect their `event_timing` and original recordings to decide whether the issue is a
label, retrieval, visual check or loose window boundary. Generated reports remain under
ignored local data, not Git. These changes do not run or improve the model itself.

### Next operator checklist

1. Obtain the original single-reviewer CSV and complete saved YOLO run folders.
2. Preserve them under ignored local storage; reproduce the provisional dataset using the
   existing tool. Do not invent the missing two rejection decisions.
3. Have a second person review independently using the existing review page; resolve differences.
4. Replay YOLO boxes through threshold/region analysis and inspect losses in small-person recall.
5. Freeze local footage/labels, verify Gemini quota/model and agree on an exact small paid pilot.
6. Capture genuine ranked/scan runs, evaluate failures, and validate changes on held-out footage.
7. Keep tracking and potential-fall logic experimental; no integration into search is justified yet.

Final checkpoint validation including run-identity regressions: **498 passed, seven
skipped** (same missing trial/provisional data and Windows-only skips described above).
No footage, weights, generated results, reviews or credentials are included in this checkpoint.
