# Which events can TanyaCCTV search for?

Updated 19 October 2026 after an explicitly approved live retrieval run. **Measured** here means
real Gemini Embedding 2 responses scored against five labelled cartoon clips. Each event type
has only one query, except vehicle presence (two). **No event type is validated on real CCTV.**

| Event type | Query | Observed first relevant merged window | IoU |
|---|---|---|---:|
| Person moving | a person walking | rank 1, corridor 0–26 s (event 5–20 s) | 0.577 |
| Person lying | a person lying on the floor | rank 1, corridor 16–40 s (event 23–40 s) | 0.708 |
| Entering | a person entering through a door | rank 1, entrance 0–60 s (event 10–20 s) | 0.167 |
| Leaving | a person leaving through a door | rank 1, entrance 32–60 s (event 45–55 s) | 0.357 |
| Loitering | a person standing still for a long time | rank 5; first four results unrelated | 0.720 |
| Fall | a person falling down | rank 1, corridor 16–40 s (event 20–23 s) | 0.125 |
| Red vehicle | a red car | rank 1, car park 16–40 s (event 20–40 s) | 0.833 |
| Any vehicle | a car | rank 1, driveway 0–50 s (event 10–45 s) | 0.700 |
| Vehicle arriving | a car arriving and parking | rank 1, driveway 8–50 s (event 10–20 s) | 0.238 |
| Parked vehicle | a parked car | rank 2; moving-car clip incorrectly ranked first | 0.357 |
| Vehicle leaving | a car driving away | rank 1, driveway 0–50 s (event 35–45 s) | 0.200 |
| Negative queries (5) | fire/smoke, dog, bicycle, crowd, motorcycle | all returned unrelated nearest windows | not scored as correct rejections |

The windows above are the first relevant result, which is not always the first returned result.
An overlap is counted as relevance; a 60-second entrance clip overlaps entry, loitering and
exit without distinguishing them. This is why recall must be read with temporal IoU and precision.

## Complete synthetic retrieval measurement

- 5 clips, 250 seconds; 32 chunks (10 seconds, overlap 2 seconds), no still-frame skipping.
- 16 queries: 11 positive, 5 negative. All five videos were in a separate evaluation index.
- 32 video embedding requests plus 16 text embedding requests succeeded, with no automatic retries.
- Preprocessing: target 480 px, 5 fps; requested 10 results per query, dedupe disabled.
- Merged hit@1: **0.818 (9/11)**; precision@5: **0.508**; recall@5: **1.000**;
  MRR: **0.882**; mean first-relevant temporal IoU: **0.453**.
- The estimated video-input charge was US$0.24016 plus short text-query charges, inside the
  approved approximate US$0.25 plan. Actual billing was not inspected; the estimate is not a cap.
  Rate checked against [Google pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-embedding-2).
- Full sanitized responses and synthetic content hashes:
  `evaluation/recordings/2026-10-19-events.json`. No footage, index or credentials are in Git.

Re-score offline, with no API calls:

```bash
.venv/bin/python backend/scripts/evaluate_search.py --ground-truth evaluation/synthetic_events_v2.json --recorded evaluation/recordings/2026-10-19-events.json
```

## Targeted image-check follow-up

The separately approved 66-image run successfully filtered the three weak synthetic cases:
loitering's correct rank-5 window and the parked car's rank-2 window became the first supported
candidates; the correct falling sequence was supported while a discontinuous upright/lying
lobby sequence remained unclear. Raw rankings and broad event windows are unchanged.
See [targeted-visual-validation.md](targeted-visual-validation.md) for counts and limitations.
This is not a new general accuracy benchmark or a fix for precise event timing.

## Interpretation and next steps

- Broad windows cover the right recording but often include multiple actions; entering, falling
  and vehicle actions have poor temporal localization. They are not precise event detectors.
- Loitering and parked vehicles failed to rank first. Further independent labelled examples are
  needed before changing rankings or thresholds; no model or threshold was tuned to these clips.
- Negative queries always return neighbours. The retrieval run did not include the optional visual review
  stage: no claim of correct visual rejection or image-check accuracy follows from these results.
- Real CCTV testing still needs authorised footage with independent annotations and separate
  permission for Google processing. Use `cctv-accuracy-checklist.md`.
- Identity matching across cameras, counting, licence plates, faces and audio remain unsupported.
  No automatic alarms or decisions about people are justified by this evaluation.

The earlier two-clip, three-positive-query baseline is preserved in `docs/search-evaluation.md`.
Its metrics cannot be directly compared with this larger five-clip, 16-query run.
