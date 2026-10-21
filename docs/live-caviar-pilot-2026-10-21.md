# CAVIAR scene-scan pilot — 21 October 2026

This is a genuine, saved Gemini scene-scan attempt on five licensed CAVIAR clips, not an
offline replay. It uses **single-reviewer provisional labels**, not independently verified
ground truth. Two queries completed; the negative query did not. It is not a complete
benchmark, a calibrated detector, or evidence of reliable general CCTV accuracy.

## Approved operation and execution

Fresh explicit owner approval: Gemini 3.8 Flash, all five CAVIAR clips (130.48 s), three
queries, at most 342 sampled images and 12 requests, no indexing or automatic retries,
estimated US$0.49 (actual billing may vary). Queries were exactly:

- `a person falling to the floor`
- `a person entering a shop`
- `fire or smoke`

The provisional CSV-derived label version and Mac prepared-video hashes were frozen in a
dataset contract. The earlier publisher-label-only failed attempt was preserved separately.
Source code commit for this attempt: `614e7f2`; exact bridge/prompt/source hashes and an
operator-runner copy are saved with the ignored local run artifacts. Configuration:
`gemini-3.8-flash`, temperature 0, low thinking, 4,096 maximum output tokens/request,
12-second windows at 6-second stride, up to six frames/window, five windows/request,
minimum 15-second request-start spacing, one attempt per batch.

Read-only AI Studio refresh showed the visible default project on the free tier: 5 RPM,
250K TPM, 20 RPD, with 1/20 in the one-day view before this run. Dashboard figures can lag,
are not guaranteed capacity and do not prove every key's project mapping. No account or
billing settings were changed. Actual billing was not independently verified.

**Execution:** ten requests attempted, nine completed. The tenth returned Google HTTP
503 (model under high demand). The operator stopped immediately; no automatic retry or
model switch occurred. Up to **288 images were attempted** (258 in successful batches,
30 in the failed request). The approved 12-request/342-image limits were not exceeded.

## Per-query results against the provisional labels

| Query | Completed sampled windows | Annotated events found | Unrelated supported windows | Status |
|---|---:|---:|---:|---|
| Falling to the floor | 19/19, 114 images | 1/1 | 1 | Complete |
| Entering a shop | 19/19, 114 images | 1/2 | 0 | Complete |
| Fire or smoke | 5/19, 30 successfully checked images | Not measured | Not measured | Incomplete: HTTP 503 |

Found means a supported returned window overlaps a labelled event in the same video;
it does not mean the event or its exact time was independently confirmed. Fall returned
three supported windows: two overlapping the expected Rest_FallOnFloor event and one in
Browse2 that is unrelated according to the provisional reference. Shop-entry returned
one supported front-view window but missed the short corridor-view labelled event.

The fire query's completed first batch had no supported windows. Its remaining windows
were not successfully checked, so it is excluded from negative false-positive statistics.
Do not call it a correct rejection, completed scan or proof of absence.

## Timing and missed-event diagnostics

Only the two complete positive queries are scored (three labelled event instances):

- **One of three event instances missed.** Both positive queries had some match, so the
  legacy query-level no-hit rate is zero. This is why individual missed events matter.
- Macro event recall/chronological Recall@5: 0.75 on only two positive queries. Scan order
  is chronological, not similarity rank. This is not a deployment accuracy percentage.
- The completed-window report has one unrelated supported window. Negative-query
  false-positive rate remains unavailable because the negative query did not finish.
- Window localization IoU >=0.5 succeeds for one of the two positive queries. For matched
  events only, mean absolute start error is 2.10 s and end error 3.64 s; the missed event
  is excluded from these averages and explicitly counted separately.

Per-event raw-window localization:

| Reference | Best returned-window IoU | Start / end error |
|---|---:|---|
| Fall clip, 26.20–38.00 s | 0.700 | 2.20 / 2.00 s |
| Front shop entry, 8.00–10.04 s | 0.219 | 2.00 / 5.28 s |
| Corridor shop entry, 5.88–6.36 s | 0.000 | Missed |

The cited-image evidence span is not guaranteed to be a better event boundary. In this
pilot its best IoU is 0.455 for the fall and 0.306 for front entry: neither reaches 0.5.
It reduces mean matched start error to 1.15 s, but end error remains 3.47 s. For the fall,
it is worse by IoU than the original broad scan window. Do not promote the earlier small
synthetic improvement as a general result. Review whether the reference category's broad
“fallen” interval and the query's “falling” transition describe the same temporal target
before tuning. Do not change labels simply to improve a score.

## Failure cases and next experiments

1. **Overhead-view action confusion.** Browse2 0–12 s was supported as a fall. Local
   inspection of the supplied sample times (0, 2, 5, 7, 10, 12 s) shows a moving person
   with changing arm/leg positions; the model described a collapse not supported by the
   provisional reference. A human must review the full sequence before adjudication.
2. **Short entry missed.** The corridor label lasts 0.48 s. Fixed sparse samples and the
   overhead/doorway geometry need investigation; do not claim sampling alone is the
   established cause. Compare sampled/cited times to full playback after human review.
3. **Loose/biased temporal localization.** Inspect scanned windows and cited frames
   separately. Any future denser/adaptive sampling, crop or prompt experiment needs a
   new frozen run configuration and scoped upload/cost approval. Do not overwrite this
   baseline or tune on held-out queries.
4. **Service availability.** HTTP 503 prevented the negative test from completing.
   This is not an accuracy result. Any retry needs a new approval; no remaining batch
   was silently rerun.

The scan, model prompt, retrieval engine and YOLO integration were not modified during
this run. No failure was “fixed” by hiding it or excluding an answered difficult query.
Ranked retrieval/indexing was not approved or executed, so no ranked-vs-scan comparison
can be made yet. The other CAVIAR queries and all RainSnow search cases remain unmeasured.

## Local artifacts and reproduction

Ignored local directory:
`data/cctv_validation/pilot-provisional-three-queries-20261021/` contains the plan, frozen
three-query ground truth/events, consumed-request ledger, saved responses/coverage,
source provenance, operator runner, local inspection image and scored JSON report.
No footage, frames, CSV, private outputs or credentials are committed.

Re-score without making an API call:

```bash
.venv/bin/python backend/scripts/run_benchmark.py --ground-truth data/cctv_validation/pilot-provisional-three-queries-20261021/ground-truth.json --events data/cctv_validation/pilot-provisional-three-queries-20261021/events.json --scan data/cctv_validation/pilot-provisional-three-queries-20261021/live-run.json --require-bound-runs --json data/cctv_validation/pilot-provisional-three-queries-20261021/report.json
```

The owner agreed to perform the second independent review at http://127.0.0.1:5003/.
That human review is pending; no reviewer status was invented by the assistant. Preserve
both CSV originals and resolve disagreements before making independently verified claims.
