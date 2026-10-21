# Received handover: verification and saved-run analysis

The 21 October TanyaCCTV handover ZIP was extracted separately under ignored
`data/cctv_validation/handoff/TanyaCCTV-handover-2026-10-21/`. No supplied files, original
CSV, shared labels or media were overwritten. No footage upload, AI call, model download,
package installation or fresh YOLO inference was performed during this verification.

## Verification findings

- Archive inventory: 40 entries, about 6.1 MB uncompressed, no path traversal/symlink entries.
- All **38 listed SHA-256 checksums passed** before running the inspected verifier.
- All five supplied annotation XMLs match the package's publisher download hash manifest.
- All three saved YOLO runs have 3,262 recorded frames per run. The analysis tool also
  checks for duplicate/missing frame IDs rather than relying on array length alone.
- Per-clip stored TP/FP/FN counts fall within the rounded-confidence brackets used by the
  package verifier. Overall AP50 reproduces exactly: GPU 384 **0.360**, GPU 640 **0.431**,
  CPU 384 **0.360**. Reports record zero network attempts during the original runs;
  this is report provenance, not a newly rerun GPU measurement.
- Rebuilding from the original CSV reproduces the ground-truth and manifest contents
  (creation date normalised). The original CSV is unchanged: **31 confirm, two reject**.
- Scorer output: **28 unique provisional events, zero independently human-verified**, two
  contested regions. The two rejections have no explanatory reviewer notes. Category-level
  kept interval counts and unique scoreable-event counts are different denominators.

### The supplied verifier exits nonzero: two explained compatibility checks

Do not describe its raw outcome as “all checks passed”. It reports failures for:

1. **Detector script byte hash.** This checkout's LF hash begins `374605d7`; converting
   only line endings to Windows CRLF produces `b0b8e6cf957846eb7aba378571b350737670b8a74962b88f36a21efbd33b43b8`,
   matching the source identity expected by the verifier. This is a line-ending difference,
   not a change to detector logic. No source file was rewritten to force a match.
2. **Regenerated events JSON.** A recursive comparison finds only the creation date and
   the five `clips[*].video_sha256` fields differ. The Mac's prepared encodings have
   different bytes from the Windows encodings. The original MPEG/XML pins match, and
   the earlier Mac audit compared all 3,262 corresponding decoded frames with matching
   counts/fps and low compression differences. Shared events/review decisions match;
   no video hash was replaced merely to silence the mismatch.

Thus package integrity, annotation identity and saved metric consistency are verified,
with the above byte-level compatibility differences explicitly retained. The excluded
Windows MP4 files/weights were not independently hashed here; neither exact original
inference provenance nor the Windows GPU speed was rerun/authenticated on this Mac.

## Cached YOLO sensitivity analysis

Commands use the existing `experiments/yolo/analyse_cached.py`, with thresholds 0.10,
0.25, 0.2505, 0.40, 0.50 and 0.70, keeping all publisher boxes and applying no region mask.
All outputs stay under ignored local data (`yolo-handoff-analysis-*.json`).

Selected **cached recounts**, precision/recall against publisher boxes:

| Saved run | Confidence >= | Precision | Recall | Small-person recall (<30 px tall) |
|---|---:|---:|---:|---:|
| GPU 384 | 0.10 | 0.361 | 0.400 | 0.019 |
| GPU 384 | 0.25 | 0.850 | 0.306 | 1 / 2,204 boxes |
| GPU 384 | 0.40 | 0.987 | 0.267 | 0.000 |
| GPU 640 | 0.10 | 0.351 | 0.487 | 0.039 |
| GPU 640 | 0.25 | 0.633 | 0.405 | 0.014 |
| GPU 640 | 0.40 | 0.872 | 0.357 | 0.006 |
| CPU 384 | 0.25 | 0.850 | 0.306 | 1 / 2,204 boxes |

These use rounded saved confidences, not the original full-precision model scores. At
0.25 some borderline boxes change membership; 0.2505 excludes saved 0.250 scores. Keep
original `results.json` for originally reported figures and identify recounts explicitly.
Publisher annotations omit some visible people/mannequins, so unmatched boxes need manual
inspection and precision is limited by reference coverage. Frame/box samples are correlated;
these are not independent person/event success probabilities or deployment estimates.

**Implication:** increasing saved-run input resolution helped recall but did not solve
tiny-person/overhead views. Reducing confidence to 0.10 increases recall and unmatched
boxes substantially. No confidence value is selected for deployment. A static mask must
not be adopted without inspecting whether it removes genuine unannotated people; no mask
was applied or promoted from these results. Person-box recall is not fall recognition.

## Provisional search benchmark

The reviewed dataset is regenerated in ignored `evaluation/provisional/` using this Mac's
actual prepared-file metadata. The current offline report remains **22 unavailable
queries in ranked and scan modes**, with no measured real search accuracy. The earlier
approved three-query pilot used publisher labels and failed on its first HTTP 503 request;
it was not rerun or rebound to this new provisional ground truth.

The provisional report is local at `data/cctv_validation/handoff-provisional-local-report.json`.
It describes the single-reviewer dataset and geometric ceilings, not new AI inference.
A second independent review and successful, separately approved live tests remain necessary.

## Next actions

1. A second human reviews the 33 original derived events independently via the existing
   local page; compare CSVs with `apply_label_review.py`. Request explanations for the
   first review's two note-free rejections without pre-filling the second review.
2. Inspect representative YOLO misses/unmatched boxes locally before considering a
   camera-specific region filter or further input-resolution/model experiments.
3. Agree on a fresh scoped retry/live evaluation after checking service availability;
   do not reuse the failed pilot's approval for retries or treat it as measured accuracy.
4. Measure ranked retrieval and scene scan separately against the selected frozen label
   version, retaining source hashes, sample coverage and failure records.
5. Keep tracking/action logic experimental until detector continuity and event-level
   measurements support it. No automatic fall detection or new model training is justified.

The handover/continuation code is on `integration/pr5-handover`, including
`docs/evaluation-next-phase.md`; the package README's statement that it was missing is
historical. Pull the current branch before continuing. No merge into main was performed.

Validation after importing the real provisional files: **513 backend tests passed, six
skipped**. The previously skipped provisional-dataset test now runs and passes. Remaining
skips: four tests require a different synthetic trial index, two are Windows-only junction
checks. No new paid AI call was part of this suite or the handover verification.

## Further local inspection: exploratory reception-region filtering

Using the saved GPU 640 run at confidence >=0.25, unmatched detection centres concentrate
in the original-frame cell x=[32,64), y=[120,144): Walk1 113/125, Browse2 364/378,
Rest_FallOnFloor 417/422 unmatched boxes. Representative annotated frames were inspected
locally, including Walk1 10/20 s, Browse2 24 s and Rest_FallOnFloor 26.4/30.4 s.
The overhead-view misses include real people and the fall transition; a person box appears
in the later lying frame but does not establish recognition of the action sequence.

A counterfactual region filter was applied **only to cached detections**, on those three
lobby clips, with the publisher ground truth kept intact. Results over all five clips:

| Threshold | Baseline TP / unmatched | Filtered TP / unmatched | Filtered precision / recall |
|---|---|---|---|
| >=0.25 | 2,257 / 1,307 | 2,257 / 413 | 0.845 / 0.405 |
| >=0.2505 | 2,256 / 1,292 | 2,256 / 410 | 0.846 / 0.405 |

At 0.25, 894 unmatched boxes are suppressed and no additional publisher-labelled boxes
are missed. This is **post-hoc exploratory analysis on the same footage**, not a held-out
improvement or permission to mask that region in production. It may hide a genuine
unannotated seated person. Publisher annotations are incomplete and a precision increase
against them alone cannot settle that question. The filter does not improve tiny-person
recall or provide falls/entry/exit understanding. The region remains disabled in the app.

Local inspection images, cluster counts, region config and replay output are under
ignored `data/cctv_validation/yolo-local-inspection/`; no new inference, external request,
code change or image upload occurred. Further model/region decisions need human review
of the hotspot plus labelled, separate validation footage.
