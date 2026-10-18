# Search evaluation harness

`backend/scripts/evaluate_search.py` measures how well search **ranks** clips against annotated
ground truth. It is a regression and comparison tool. **It does not measure detection accuracy**,
and similarity scores are never treated as probabilities.

## What is measured

A returned window is **relevant** if it overlaps an annotated event in the same video
(windows that only touch at a boundary don't count). For each query with at least one event:

| Metric | Meaning |
|---|---|
| hit@K | at least one of the top K windows is relevant |
| P@K | share of the top K windows that are relevant (divides by the number returned, if fewer than K) |
| R@K | share of the query's annotated events covered by the top K windows |
| MRR | 1 / rank of the first relevant window (0 if none) |
| start / end error, IoU | for the first relevant window, compared with the event it overlaps most |

Metrics are reported twice:

- for the **raw 10 s chunks** returned by SentrySearch
- for **TanyaCCTV's merged windows**, which group overlapping chunks (merge ratio 0.5)

**Negative queries** (no annotated event) have no precision or recall. The engine always returns
its nearest clips, so they are listed separately and never counted as correct rejections.

## Results: recorded real search, synthetic footage

Footage:

- `cam1_lobby.mp4` (60 s): person walking 20–40 s, lying on the floor 40–60 s
- `cam2_carpark.mp4` (40 s): red car 20–40 s

Both clips are made by `backend/scripts/make_demo_footage.py`. Its H.264 output is byte-identical
to the clips used in the recorded run.

Responses:

- the real Gemini Embedding 2 search of 17 October 2026, through the TanyaCCTV bridge (dedupe off)
- the top 5 chunks per query
- stored in `evaluation/recordings/2026-10-17-gemini-embedding-2.json`

Re-scoring them makes no API calls:

```powershell
.\.venv\Scripts\python.exe backend\scripts\evaluate_search.py
```

| Level | hit@1 | P@1 | P@3 | P@5 | R@5 | MRR | start err | end err | IoU |
|---|---|---|---|---|---|---|---|---|---|
| Raw 10 s chunks | 1.0 | 1.0 | 1.0 | 0.667 | 1.0 | 1.0 | 2.67 s | 10.0 s | 0.417 |
| Merged windows | 1.0 | 1.0 | 0.5 | 0.5 | 1.0 | 1.0 | 2.67 s | 0.67 s | 0.867 |

| Query | Top merged window | Event | IoU |
|---|---|---|---|
| a person walking | lobby 16–42 s | 20–40 s | 0.77 |
| a person lying on the floor | lobby 40–60 s | 40–60 s | 1.0 |
| a red car | car park 16–40 s | 20–40 s | 0.83 |
| fire and smoke (negative) | lobby 0–26 s | none | not scored: nearest clip, not evidence |

How to read this:

- **The right clip ranked first for all three positive queries.**
- **Merging improves timing.** IoU rises from 0.42 to 0.87, and the end error falls from 10 s to 0.7 s.
- **Merged P@3 is lower.** There are fewer, larger windows, so the slots after the first are more
  often leftover background clips.
- The negative query still returns clips. That is why every result stays `uncertain`.

`test_evaluation.py` locks these numbers as a regression baseline. They should change only with a
new recording.

## Event types, errors and the extended dataset (Phase 7)

- `evaluation/synthetic_events_v2.json` annotates **16 queries** (11 positive, 5 negative)
  across all five synthetic clips (`make_demo_footage.py --set all`). The event types are:
  person moving, lying, entry, exit, loitering, fall, vehicle present, vehicle entry, vehicle
  parked, vehicle exit, and negative.
- Reports now include a breakdown by event type, and for every query:
  - the non-matching windows in the top 5, each labelled as overlapping another annotated
    event (a confusion) or as "background"
  - any annotated events that were missed.
- A recording lists the videos its index contained (`indexed_videos`). Events in other videos are
  excluded rather than counted as misses. Queries without a response are reported as
  **not measured**, never scored.

Running v2 against the current recording measures only the 3 queries that recording covers:

```powershell
.\.venv\Scripts\python.exe backend\scripts\evaluate_search.py --ground-truth evaluation\synthetic_events_v2.json --allow-missing
```

See [event-support.md](event-support.md) for which event types are measured, unmeasured or
unsupported. It also gives the approval request (about US$0.15) needed to measure the rest.

## What this does not show

- **Accuracy on real CCTV.** Three positive queries on cartoon scenes cannot predict performance
  with real cameras, lighting, crowds or occlusion.
- **Statistical confidence.** With 3 positive queries, every metric is very coarse.
- **The dashboard's exact output.** The recording holds the top 5 chunks; the dashboard asks for
  10, so it can show more (mostly background) windows.
- **Absence.** A negative query's results never prove an event did not happen.

## Running on real authorised footage (pending)

1. Fill in a **private** copy of `docs/cctv-validation-template.csv` (see
   `cctv-accuracy-checklist.md`). Rows with the same query form one case. Leave the expected
   window blank for queries that should have no match. Use the indexed **file name** as
   `expected_video_alias`.
2. Index the clips locally, then prepare them for AI search through the dashboard plan or
   `sync_search_index.py`. That sends video to Google and needs its own approval and cost check.
3. Preview the live run. This prints the plan and sends nothing:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\evaluate_search.py --ground-truth C:\private\validation.csv --live
   ```

4. With approval, send only the query text (no footage or frames), and save the responses so
   later re-scoring is free:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\evaluate_search.py --ground-truth C:\private\validation.csv --live --approve-api-calls --save C:\private\recording.json
   ```

Keep real footage, annotations and recordings outside Git. Report per-condition results and
failures, not just averages.
