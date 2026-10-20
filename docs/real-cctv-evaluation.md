# Real-camera search evaluation — 20 October 2026

**Bottom line.** A reproducible benchmark now exists for real (staged) CCTV footage, with
30 labelled events and 22 scoreable queries. **No live AI search has been run on it**, so its
real-world accuracy is **unmeasured**: every ranked-search and scene-scan score below is either
"unavailable", a replay of earlier *synthetic* runs, or a geometric upper bound. Running the
live benchmark needs paid Gemini calls and your approval (see "Live run plan").

## What each search mode really does (verified in code)

| Mode | Inference | What is sent / used |
|---|---|---|
| Fast similarity search (ranked) | **Live**: Gemini Embedding 2 via SentrySearch (`sentry_client.search` → `search_engine/tanya_bridge.py`) | Query text per search; whole videos as 10 s chunks (2 s overlap) once, at AI preparation (`search_sync`) |
| Ranked + image check | **Live**: ranked results, then the image-check model (`visual_review.run_review`, default `gemini-3.8-flash`) | Up to 6 frames from each of the top 5 windows |
| Scene scan | **Live**: image-check model over every window (`scenario_scan`) | 12 s windows every 6 s, up to 6 of the 1 s frames each, 5 windows per request |
| Offline replay demo | **None**: recorded responses (`offline_demo.replay_search`) | Nothing; 4 fixed synthetic queries |
| This benchmark | **None** unless `--record-live-scan --approve-api-calls` is given | Nothing by default |

## Dataset (deliverable 1)

Footage: the five CAVIAR clips (University of Edinburgh; publisher states CC BY-SA, version not
given; attribution "EC Funded CAVIAR project/IST 2001 37540"). 130.5 s in total, 384×288,
25 fps, two sites (INRIA lobby, Portuguese shopping corridor). **Staged** scenes, not real
incidents. The six RainSnow traffic clips were not used: they have no event labels, need Kaggle
credentials and add 193 MB, so they cannot be scored yet.

```powershell
$env:TANYA_SENTRY_PYTHON = "$HOME\sentrysearch-trial\tools\sentrysearch\Scripts\python.exe"
.\.venv\Scripts\python.exe backend\scripts\download_caviar.py --download   # 38 MB, hash-pinned
.\.venv\Scripts\python.exe backend\scripts\download_caviar.py --prepare    # local H.264 copies + frames
.\.venv\Scripts\python.exe backend\scripts\build_real_dataset.py --sheets  # manifest, labels, review sheets
```

Outputs (committed, no footage): `evaluation/datasets/caviar-events.json` (derived intervals,
rules, licence), `evaluation/datasets/caviar-manifest.jsonl` (one row per query × clip × event
with clip ID, path, duration, resolution, fps, licence, category, start/end, query, presence,
expected clips, annotation confidence, notes, split), `evaluation/caviar_ground_truth.json`
(benchmark format) and `evaluation/review/caviar-review.csv` (human verification sheet).
Footage, frames and contact sheets stay under git-ignored `data/cctv_validation/caviar/`.

### Where the labels come from

Every interval is derived from the **publisher's per-frame ground truth XML** by a fixed rule in
`backend/tanya/real_dataset.py`; none is invented or produced by a model. Frame *i* covers
[i/25, (i+1)/25) s; runs separated by ≤ 0.5 s are merged; short runs are dropped (1 s default,
2 s for standing still, 0.4 s for shop entry/exit).

**Important finding while building it:** CAVIAR's `context` field is a whole-track scenario
label, not the person's current state. The person who later falls is labelled "drop down" from
the moment they walk in (19.2 s) although the fall happens at about 26 s. Rules based on
`context` produced intervals about 2–11× too long and would have inflated recall and broken IoU. The
rules now use the instantaneous `movement`/`situation` fields (`context` only selects the faller),
and a regression test covers it. Contact sheets for "fallen" (26.2–38.0 s: collapses, lies,
gets up) and shop entry were spot-checked by the assistant; this is **not** independent
human verification.

| Category | Events | Clips | Median length | Label rule |
|---|---:|---:|---:|---|
| walking | 13 | 5 | 4.4 s | movement = walking |
| person present | 7 | 5 | 15.3 s | any tracked person |
| standing still | 5 | 2 | 4.1 s | movement = inactive ≥ 2 s, not the fallen person |
| meeting | 2 | 2 | 10.7 s | group situation = interacting |
| shop enter | 2 | 2 | 1.3 s | situation = shop enter |
| shop exit | 2 | 2 | 2.1 s | situation = shop exit |
| browsing | 1 | 1 | 8.1 s | situation = browsing |
| fallen | 1 | 1 | 11.8 s | "drop down" person not walking |

### Queries

25 queries in operator language: 7 direct (dev split), 7 paraphrases (test), 1 ambiguous
("a person"), 3 negatives (car, fire/smoke, dog), 4 hard negatives (running vs walking, fighting
vs meeting, leaving a bag vs standing, bicycle vs walking) — **15 positive and 7 negative
scoreable queries**. 3 more ("someone acting suspiciously", "a person wearing a dark coat",
"a person carrying a bag") have no publisher label and are reported as **unmeasured**, never
scored. Filenames do not reveal answers to the engine (it searches content); several categories
span both sites. Use the dev split for any tuning and report the test split separately.

### Human verification workflow (still required: 0 of 30 events verified)

Two people review all **33 derived events** (30 are scored; 3 duplicate a walking interval as
"person present") independently. Budget about 30–45 minutes per reviewer.

1. **Open the review page** (local only; footage never leaves the computer):

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\build_real_dataset.py --sheets
   .\.venv\Scripts\python.exe backend\scripts\build_real_dataset.py --serve-review
   ```

   Open **http://127.0.0.1:5003/**, enter your initials and press **Start my review**. Each event
   shows its contact sheet (1 s before, start, middle, end, 1 s after) and the video.
   Use the server rather than opening `review.html` from disk: it supports seeking in every browser.
2. **For each event** press the **Play from … s** button (it jumps 1 s before the event's start, e.g.
   "Play from 25.20 s (1 s before the 26.20 s start)") and watch past the end. The browser's own
   clock shows whole seconds only (25.20 s appears as 0:25); use the exact **Video time … · frame …**
   readout under the video instead. Choose:
   - **confirm**: the event happens and both boundaries are right within about 1 s;
   - **adjust**: the event happens but a boundary is off; pause at the true start and end and
     press **Set start** / **Set end** (the burned-in camera clock helps);
   - **reject**: the event does not happen in this interval. Add a note for every adjust/reject.
   Answers autosave per reviewer (by initials) in that browser.
3. **Press "Download my review CSV"** (`caviar-review-<initials>.csv`). The second reviewer
   reloads the page and starts with their own initials; they must not see the first CSV.
4. **Merge** (local; regenerates the ground truth):

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\apply_label_review.py caviar-review-AB.csv caviar-review-CD.csv
   ```

   An event becomes `human_verified` only if both keep it and their boundaries agree within 1 s
   (the average is used); it is removed only if both reject it. Identical initials are refused.
   The command reports Cohen's kappa for the keep/reject decision and writes
   `evaluation/review/caviar-verified.json` and `evaluation/review/caviar-disagreements.csv`.
5. **Resolve disagreements** together, each reviewer updates their own answers on the page,
   downloads again, and step 4 is rerun until the disagreement file is empty.
6. Decide what to do with the 3 unmeasured queries (define and label them, or keep them out).

`run_benchmark.py` prints "N of 30 events human-verified" in every report. Until N = 30, every
CAVIAR score must say "publisher labels, not independently verified". If the label rules ever
change, earlier reviews no longer match and `apply_label_review.py` refuses them instead of
applying them to different intervals.

### Provisional single-reviewer dataset (20 October 2026)

One reviewer (Ys) reviewed all 33 events: 31 confirm, 2 reject (E019, E020: "standing still" in
Walk1 at 12.48–16.60 s and 19.92–24.44 s; no notes given). Until a second independent review exists,
this is used only through a **separate, clearly labelled** path that never writes the two-reviewer
files and never marks anything human_verified:

```powershell
.\.venv\Scripts\python.exe backend\scripts\prepare_provisional_benchmark.py C:\path\to\caviar-review-Ys.csv
.\.venv\Scripts\python.exe backend\scripts\run_benchmark.py --ground-truth evaluation\provisional\caviar_ground_truth.provisional_single_reviewer.json --events evaluation\provisional\caviar-events.provisional_single_reviewer.json
```

Outputs in `evaluation/provisional/` are labelled `provisional_single_reviewer` and record the CSV's
SHA-256 (not its location). **Rejected events are contested regions, not negatives**: they are removed
from the positives, and results falling inside them are scored neither right nor wrong (this rule
now also applies to events both reviewers reject). Negative queries remain publisher-based
(`publisher_label_unverified`): the review covered events, not absences.

## Benchmark (deliverable 3)

```powershell
.\.venv\Scripts\python.exe backend\scripts\run_benchmark.py                 # CAVIAR, no AI calls
.\.venv\Scripts\python.exe backend\scripts\run_benchmark.py --plan          # exact upload bounds
.\.venv\Scripts\python.exe backend\scripts\run_benchmark.py --ranked RUN.json --scan RUN.json --json out.json
```

Metrics (definitions in `backend/tanya/benchmark.py`): hit@1/5, event recall@1/5, precision@1/5,
localisation hit at IoU ≥ 0.3 / 0.5 (top 1 and top 5), missed-event rate, negative-query false
positive rate, latency, and counts of ok / failed / unavailable queries. Negatives are never in
recall denominators. Ranked search always returns its nearest windows, so its negative false
positive rate is 1.0 by design; for scene scan a negative counts as a false positive only when a
window is marked "supported" — which is an AI-supported candidate, not a verified detection.
Ranked vs scan are compared only on queries both answered. Run records must say `live` or
`replay`; replayed or synthetic results are never presented as live inference.

## Results (deliverable 4)

### Real-camera (CAVIAR, publisher labels, unverified)

| Mode | Scored | Result |
|---|---|---|
| Ranked search | 0 / 22 | **unavailable** — videos not indexed in SentrySearch (paid) |
| Scene scan | 0 / 22 | **unavailable** — would send frames to Gemini (paid) |
| Comparison | 0 common queries | not possible yet |

### Structural ceiling on the same 30 events (no model; perfect ranker)

Window geometry alone limits timestamp accuracy. Even a perfect ranker could localise only
**30%** of events at IoU ≥ 0.5 with the 10 s ranked chunks and **43%** with 12 s scan windows;
at IoU ≥ 0.3 the figures are 70% and 67%. The median event lasts 4.4 s and 11 of 30 are shorter
than 4 s. Shop entry/exit (1.3–2.1 s) cannot reach IoU ≥ 0.5 in either mode. Five events fall
under exactly one sampled frame in their best scan window (none under zero).

### Synthetic replay (recorded live runs on cartoon footage — not real-world evidence)

| Run | Scored | Key numbers |
|---|---|---|
| Ranked, 2026-10-19 recording (`--ranked-recording`) | 11 positive, 5 negative | hit@1 0.818, recall@5 1.0, P@5 0.508, loc@1 IoU ≥ 0.5 0.364; negative FP rate 1.0 (by design) |
| Ranked + image check, 2026-10-19 (`--checked-recording`) | 3 positive | loc@1 IoU ≥ 0.3: window 0.667 → evidence span **1.0**; IoU ≥ 0.5: 0.333 → **0.667**; hit@1 unchanged 1.0; median latency 70 s |

The new benchmark reproduces the existing harness's merged hit, recall and precision exactly
on the same recording (regression-tested).

## Failure analysis (deliverable 5)

Ordered by measured evidence, not by guesswork:

1. **No live measurement on real footage.** The dominant gap: every real-world accuracy claim is
   unsupported. Fix: the approved live run below, after human label review.
2. **Timestamp localisation is capped by window size.** Measured by the ceiling: 57–70% of the
   real events cannot reach IoU ≥ 0.5 even with perfect ranking. Short actions (entering,
   leaving) are the worst case. This affects both modes.
3. **Ranked search cannot reject.** Recorded runs: all negative queries (5/5 synthetic) still
   return nearest windows; an irrelevant clip scored close to a correct one (README). No score
   threshold is justified by current data.
4. **Image-check latency.** Median 70 s per query (3 recorded runs); one sequence request timed
   out (`2026-10-19-direct-sequences.json`). Scene scan of this dataset is up to 4 requests per query.
5. **Sparse sampling for brief events.** 5 of 30 real events get one sampled frame in the best
   scan window, so the checker sees a single instant of the action.
6. **Query interpretation and appearance** remain unmeasured: CAVIAR has no clothing labels.

Cause attribution (sampling vs representation vs ranking vs query) needs live outputs; the
benchmark's per-query rows and ceiling table are designed to separate them once a run exists.

## Change made from this evidence (deliverable 6)

**Evidence span** (`visual_review.evidence_span`): when the image checker supports a window and
cites frames, results now also carry the range from the first to the last cited frame, padded by
half the sampling gap and clipped to the window. The window itself stays the provenance. The UI
shows "Evidence span m:ss–m:ss" with a play button. Before/after on the only recorded checker
outputs with labels (synthetic, 3 queries): localisation at IoU ≥ 0.5 0.333 → 0.667 and at
IoU ≥ 0.3 0.667 → 1.0, detections unchanged, no case worse. Geometric upper bound on CAVIAR if the
checker cites exactly the in-event frames: IoU ≥ 0.5 for 93% of events vs 43% for windows. Real
effect on CAVIAR is unknown until the live run. Tests: `test_real_benchmark.py`.

Also fixed: the CAVIAR/RainSnow `--prepare` steps now find FFmpeg via `TANYA_SENTRY_PYTHON`
on Windows (shared `playback.find_local_ffmpeg`), as the offline demo already did.

Not changed, deliberately: chunk length, scan stride, merge ratio, thresholds and models. None
can be justified without live results, and tuning on 30 unverified events would overfit.

## Live run plan (needs your approval; nothing has been sent)

From `run_benchmark.py --plan` on this dataset (22 scoreable queries):

| Step | Operation | Data sent | Bound | Estimated cost |
|---|---|---|---|---|
| 1 | Index the 5 CAVIAR copies with SentrySearch (Gemini Embedding 2) | 17 video chunks (130 s of footage) | 153 billed frames | ≈ US$0.12 at the stored US$0.00079/frame (paid tier) |
| 2 | Ranked queries (`evaluate_search.py --live --approve-api-calls --save`) | 22 query texts | 22 embedding requests | small; text price not stored here — confirm |
| 3 | Scene scan (`run_benchmark.py --record-live-scan OUT --approve-api-calls`) | sampled JPEG frames + query text to `gemini-3.8-flash` | ≤ 2,508 images, ≤ 88 requests | **not stored in this project** — confirm current per-image/token pricing |

The footage is CC BY-SA public research footage, not private CCTV. On the free tier Google may
use submitted content. A smaller first step is possible: step 3 on the 7 dev queries only
(≤ 798 images, 28 requests).

## Limitations

5 short staged clips, two sites, 384×288, daytime indoor; no night, weather, vehicles, crowds or
modern resolutions; one fall, two meetings, one browsing event; labels unverified; no live
inference. None of these numbers is production accuracy. RainSnow needs event labels first.
