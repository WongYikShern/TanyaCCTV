# Describe a scene and search uploaded recordings

The default Search method is now **Scan footage for this scene**. It scans samples across
all locally indexed recordings, or a selected recording/time range, independently of similarity
rankings. The earlier pipeline could only visually check its first five retrieved windows;
a relevant scene omitted by retrieval was never checked. The new path removes that gate.

## Use

1. Upload authorised recordings. Local frame extraction happens after upload.
2. Open http://localhost:5001/#search and describe the visible scene in ordinary language.
3. Leave **All indexed recordings** selected, or choose one recording and optional start/end seconds.
4. Click **Review footage scan plan**. This step is local: no images are sent to Google.
5. Read the included filenames/ranges, excluded recordings, maximum images and API requests.
   Approve that plan, then click **Scan approved footage** to send its samples and query to Google.
6. Results appear batch by batch. Open the evidence timestamp or play the full candidate window.
   Supported results, unclear samples and contradicted descriptions remain separate. You can add
   clips to an investigation and save a human Correct/Wrong/Unsure review.

New uploads join the next plan after local indexing, without embedding preparation. Existing
approvals are fixed snapshots: adding a recording does not silently expand an approved send.
**Fast similarity search** remains available for quick rankings over the separate embedding index.
The research-only CAVIAR/RainSnow viewers and the synthetic offline demo still block new AI calls.
Launch `backend/scripts/run_web.py` for the owner's normal uploaded-video library.

## Scope and timing

- Every included recording/range is divided into overlapping 12-second windows, starting 6 seconds
  apart. Up to six existing local frame images per window are distributed over that window.
- At most five windows / 30 images are sent per API request, with one transport attempt.
- Plan limits are at most 500 windows (up to 3,000 image sends and 100 API requests). Large
  libraries must be narrowed to a recording/range; they are never silently truncated. The maximum
  single-recording range is approximately 50 minutes. Charges depend on the configured Gemini
  model, image/token accounting and account pricing. The plan is an upload bound, not a dollar cap.
- Each client sends batches in order and renders progress and partial results. Stop prevents the
  next batch; an in-flight request may finish and incur charges. Closing the page stops future
  client submissions. A model/transport failure stops the scan with partial results retained;
  retries require a new reviewed plan. Plans expire after one hour or a server restart.
- Source file hashes are checked before planning and before a batch's footage is read. Missing,
  changed or failed recordings are reported; none is silently substituted. Frame reads retain
  existing path-escape protection.

These are sampled visual matches, not complete video reasoning. The model is instructed to
respect required details and ordered actions, and use **unclear** if an essential step is not
visible. Short actions can occur between samples, long sequences may span windows, small
objects/garments can be ambiguous, and motion/colour/scene interpretation can be wrong.
Window limits and evidence image times are not exact event onset/end estimates. Overlapping
supported windows can refer to the same event. A negative result does not establish absence.
No identity, intent, crime or automatic alarm is inferred.

## Verification checkpoint

Offline tests check multi-recording and tail coverage, new uploads versus fixed approvals,
explicit exclusions and range bounds, no retrieval dependency, per-request/image budgets,
replay/out-of-order rejection, source changes, transport failures without retransmission,
CSRF/session ownership, cancellation and offline-demo restrictions. The live run and its
limitations must be reported separately from these code checks; passing these tests is not
an accuracy measurement.

### Live checks on the owner's existing four-video library

The owner separately approved all sends. No embedding calls or whole-video uploads occurred.
Private filenames are replaced with aliases in the committed recordings; no images or keys are
stored there. These are selected acceptance checks, not a representative accuracy benchmark.

| Description | Observed outcome |
|---|---|
| A person wearing dark clothing in a living room | Both overlapping living-room windows supported; both square clips and the boat rejected. |
| An orange and white boat on water | Boat window supported; both square clips and both living-room windows rejected. |
| Fire and smoke | All five windows rejected; no supported result. |
| A person falls down and remains lying on the floor | All five windows rejected; the standing person's raised hands were not mistaken for falling. |
| A person walks toward the camera and then raises both hands | First request timed out and stopped with no accepted match. After a separately approved retry using the supported low-thinking setting, both living-room windows were supported; other three windows rejected. The browser displayed evidence at 12 s and playback opened there, showing raised hands. |

The original three checks sent **87 images in three successful requests**. The sequence checks
included **one timed-out attempt**, one successful negative test and one separately approved
successful retry, each bounded at 30 images (29 images per completed scan). Five successful
requests checked **145 images**; the timed-out attempt may also have been processed/billed.
There were **no automatic retries**. The total approved allowance was 180 images / six requests
and is consumed; additional tests need their own reviewed upload plan.

Recordings: `evaluation/recordings/2026-10-19-direct-scenario.json` and
`evaluation/recordings/2026-10-19-direct-sequences.json`. The sequence retry was observed in the
actual Chrome website, rather than inferred from a mocked response.

The latency fix explicitly selects `low` thinking for `gemini-3.8-flash`, as supported by
[Google's thinking documentation](https://ai.google.dev/gemini-api/docs/generate-content/thinking?hl=en).
It retains one transport attempt; other configured model overrides keep their provider defaults.
Lower latency is a tuning goal, not a guarantee of prompt completion or identical accuracy.
A playback edge case found during the browser check was also fixed: an evidence time equal to
its window's end now opens the recording without an immediate zero-length stop. Old links with
that invalid range are guarded as well.

Still unverified: arbitrary long recordings, diverse natural CCTV accuracy, exact event
boundaries, systematic recall for brief events, and complex multi-stage scenarios spanning
multiple scan windows. Clothing type is not silently changed: a visible hoodie/jacket does
not establish a shirt. Possible matches with missing details remain available for review.

Final offline checkpoint: **339 passed, 6 skipped** in the full backend suite; JavaScript syntax check passed.
