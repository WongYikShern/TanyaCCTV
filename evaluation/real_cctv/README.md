# Real-camera search benchmark — preparation, not measured accuracy

Based on integration/pr5-handover at 56a7ad2. Work branch: feature/real-cctv-evaluation.

## Completed on 20 October 2026

- Verified prepared-file SHA-256 hashes for all 11 local clips (1,930.18 seconds).
- Prepared 12 realistic query drafts and per-clip review slots in `draft.json`.
- Added publisher annotation navigation hints, kept separate from ground truth.
- Added an offline scoring tool with separate ranked/scene-scan results, Recall@5,
  IoU >= 0.5, event timing errors, false-positive windows and failure cases.
- Added a dataset fingerprint so recordings cannot silently use different labels.
- Missing, uncertain, disagreeing labels and incomplete runs are not correct negatives.
- Metadata-only GET requests confirmed gemini-embedding-2 and gemini-3.8-flash are
  accessible to the configured credential. This does not establish available quota.
- No footage, query or frame was sent to Google during this phase; no training.

## Next: two independent human reviews

Open each video from the local paths in `draft.json` in a video player. Both reviewers
must watch the full clip for every query, not only the publisher's suggested intervals.
CAVIAR uses staged actors; RainSnow contains natural traffic. These are different
populations and results should also be inspected by source/event type.

Each case has one `clip_reviews` row per clip. Each reviewer independently supplies:

```json
{"reviewer":"a distinct reviewer name","method":"human_full_video",
 "presence":"present","events":[{"start_sec":12.4,"end_sec":15.2}]}
```

Use `"presence":"absent","events":[]` only after watching the entire clip.
Leave unknown reviews null. The last four query hypotheses are candidate negatives,
not verified absences. Record all qualifying occurrences, including other videos.
Use seconds from the prepared MP4, start inclusive/end exclusive. Verify boundary
frames, rather than trusting the player's rounded clock. Publisher states are hints:
notably the broad “drop down” state includes walking before and after the fall.
Agree beforehand what counts as a parked vehicle, crossing, and start/end of a fall.

The checker requires two distinct reviewers with matching resolved intervals. Keep
independent initial labels separately; resolve differences together and document the
reason in a `resolution_notes` field. Names are declarations, not authentication.
Freeze the reviewed JSON before any live run and retain its fingerprint. A subset
pilot needs its own dataset file containing exactly the chosen clips/cases and reviews.
Do not select test queries based on successful AI output. Use held-out cases when tuning.

## Offline commands (run from the repository root)

```bash
.venv/bin/python backend/scripts/evaluate_real_benchmark.py check
.venv/bin/python backend/scripts/evaluate_real_benchmark.py plan
.venv/bin/python backend/scripts/evaluate_real_benchmark.py evaluate --dataset reviewed.json --recording recording.json --output report.json
```

The script has no live execution option. Raw footage remains ignored under data/.
`check` verifies local media hashes and reports label blockers. `plan` sends nothing.
On Windows use the equivalent Python executable in the project environment.

## Recording contract

A recording contains `dataset_sha256` from `check`, `mode` (`ranked` or `scene_scan`),
`indexed_clips` (all dataset clip IDs), `provenance`, and `queries`.
Provenance requires `inference`: `mock`, `offline_replay`, or `live_ai`. Live recordings
also require model, run_id and recorded_at; retain original responses and request logs
in the ignored local run directory. Replayed outputs never establish new live inference.

Each query entry has `case_id`, `status` (`completed`, `partial`, or `error`) and `windows`.
Windows have `video` (clip ID), start_sec, end_sec and optional finite score. Preserve
ranked output order; record raw chunks and merged results as separate recordings.
Scene windows additionally require verdict (`supported`, `unclear`, `not_supported`).
Set `coverage_complete: true` only after checking every planned batch/window completed;
retain the plan and batch logs. It is a producer assertion, not independently authenticated.
Never replace a timeout with an empty completed response. The scorer does not run models.

Scene scans are chronological: their Recall@5 is explicitly chronological, and
`recall_all` covers all returned supported windows. Ranked negatives measure irrelevant
retrievals, whereas scan negatives measure false visual support. Neither zero sampled
supports nor a high similarity score proves an event absent/present in every frame.
Report timing errors alongside missed events; matched-only timing averages omit misses.
Keep modes and inference provenance in separate reports. Unit tests use invented labels.

## Cost and permission gate

`budget-plan.json` is an unapproved planning estimate for the full 11-clip/12-query scope:
245 indexing calls plus 12 text queries, 2,397 billed video frames; scene scan up to
756 requests / 22,536 sampled images. Estimated total **US$33.5701**, predominantly
scene scanning. This is not a spending cap or an instruction to execute.

Rates checked 20 October 2026: [official Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).
Embedding video estimate $0.00079/frame and text $0.20/million tokens; Flash standard
$0.75/million input and $3.75/million output tokens. Image budgeting assumes 1,120
input tokens/image; see [media resolution](https://ai.google.dev/gemini-api/docs/media-resolution).
Actual token accounting, thinking/output, quotas and billing may differ. The plan
includes overlapping windows and assumes no free tier or discounts. Rates can change.

**Remaining quota and billing tier are unverified.** Check the active project's limits
in AI Studio using [Google's rate-limit guidance](https://ai.google.dev/gemini-api/docs/rate-limits).
Model metadata access is not an inference-quota check. Do not start this full run.
First finish labels, choose a smaller pilot, verify the project limits, and obtain
approval for named clips/queries, image/request bounds, model, retry policy and budget.
Use an isolated benchmark index, not the owner's library. No automatic retries.

## Still pending

1. Two human full-video reviews, reconciled boundaries, and verified negative queries.
2. Active Gemini quota/billing verification and explicit pilot scope/budget approval.
3. Adapter/run capture against the approved frozen dataset, then genuine AI results.
4. Investigate measured failures; compare improvements on held-out queries/footage.

No real-camera accuracy percentage or exact event-timing reliability is established yet.

## Easier human review: local video page

```bash
.venv/bin/python backend/scripts/review_real_benchmark.py
```

Open **http://localhost:5012/** while the command stays running. This is a separate,
local-only labelling page; it does not modify the main application or call Google.
It verifies clip hashes before startup and serves only the page, dataset and selected
media. Video byte-range responses support seeking. No repository directory listing.

Enter your own reviewer name, select a clip/query, watch the whole clip, mark all
intervals, and save. Unknown is the default; an absence declaration requires a full
review confirmation. Progress is stored in the current browser, per dataset/reviewer.
Download a JSON backup. Unsaved changes are not exported, so always Save first.
Reviewers should not inspect each other's decisions before finishing independent work.
The page hides the dataset's prior reviewer decisions and publisher hints.

Combine two exported reviews without overwriting the original files:

```bash
.venv/bin/python backend/scripts/merge_benchmark_reviews.py alice.json bob.json --output data/cctv_validation/reviewed-v1.json
.venv/bin/python backend/scripts/evaluate_real_benchmark.py check --dataset data/cctv_validation/reviewed-v1.json
```

Partial exports remain blocked. Duplicate decisions, stale dataset fingerprints and
same-name reviewers are rejected. Disagreements remain blocked until humans reconcile
them; the tool never picks a winner. Preserve the initial exports and resolution notes.
`local-observations.json` contains AI-assisted local sampled-frame notes for all 11
clips. These are navigation aids, not independent human reviews or absence labels.
