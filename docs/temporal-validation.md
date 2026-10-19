# Retrieval versus event timing — 19 October 2026

A window can touch an event while including much unrelated footage. For the synthetic fall,
the returned 16–40 s window overlaps the labelled 20–23 s fall but its temporal intersection
over union (IoU) is only 3/24 = 0.125. Counting that as a retrieval hit does not establish
accurate onset/end times.

The evaluator now reports **two additional diagnostic thresholds**, IoU >= 0.3 and >= 0.5,
for raw chunks and merged windows. A relevant result must still refer to the same video and
have positive overlap, and also meet the threshold. Exact threshold equality passes.
These are reporting thresholds, not calibrated detector acceptance criteria. No ranking,
model, merge ratio or original overlap-based metric was changed.

## Measured on the saved five-clip synthetic run

All computations below reuse existing saved responses: no new API calls or footage.
Positive-event metrics average across 11 positive queries. Five negative queries are excluded
and remain listed separately as unrelated nearest results, never correct rejections.

| Timing requirement | Level | hit@1 | Precision@5 | Recall@5 |
|---|---|---:|---:|---:|
| Any positive overlap (original) | Raw chunks | 0.727 | 0.509 | 0.841 |
| Any positive overlap (original) | Merged | 0.818 | 0.508 | 1.000 |
| IoU >= 0.3 | Raw chunks | 0.636 | 0.309 | 0.795 |
| IoU >= 0.3 | Merged | 0.455 | 0.330 | 0.636 |
| IoU >= 0.5 | Raw chunks | 0.455 | 0.218 | 0.705 |
| IoU >= 0.5 | Merged | 0.364 | 0.267 | 0.455 |

At IoU >= 0.5, merged windows cover the labelled walking, lying, sustained-standing, red-car
and generic-car events in the top five. Entry, exit, fall, arriving/parking, parked-car and
vehicle-exit queries have zero recall@5 at this timing threshold. These are localization
failures on these examples, even where overlap-based retrieval or image review succeeds.

The successful targeted visual checks do not shorten those windows. Evidence timestamps are
sample positions, and **Inspect strongest chunk** is a navigation aid, not a timing detector.
Real-world timing remains unvalidated until independently annotated footage is available.

## Reproduce offline

```bash
.venv/bin/python backend/scripts/evaluate_search.py --ground-truth evaluation/synthetic_events_v2.json --recorded evaluation/recordings/2026-10-19-events.json
```

Add `--json` for per-query strict metrics under `localization`, keyed by `0.3` and `0.5`.
Unmeasured queries and annotations outside the recorded index stay excluded. Negative cases
receive no positive-event precision/recall. The original `summary` and `per_query` remain
backwards-compatible overlap metrics.

## Next experiment, not run

Use independently labelled clips to compare shorter source chunks or explicit onset/end
annotation against the current 10-second chunks. Report timing and recall trade-offs, rather
than choosing settings solely on these five clips. Any fresh video preparation or live
image check needs a specific reviewed upload/cost plan. No such extra requests were made.
