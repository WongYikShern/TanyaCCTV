# Continue TanyaCCTV work from another device

Checkpoint: 18 October 2026. Branch: `feature/local-web-dashboard`.
Pull Request: https://github.com/WongYikShern/TanyaCCTV/pull/2

## Teammate: resume this branch

Review PR #2 before merging. In an existing clean checkout:

```bash
git fetch origin
git switch feature/local-web-dashboard
git pull --ff-only origin feature/local-web-dashboard
```

If you have local changes, save them before switching; do not discard them. Follow the README
for the main Python environment and the separate Python 3.12 search environment. Configure
your own key privately. Then:

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python backend/scripts/run_web.py
```

Open http://localhost:5001/. Your checkout will not contain this laptop's four videos or AI
index. Upload authorised test footage, extract frames, review the AI preparation plan and
approve its Google upload/cost before testing. Continue commits on this feature branch and
push it to update the same PR. Do not merge main merely to resume development.

## What works

- Local Flask website/API, uploads, frame extraction, frame timeline, compatible video playback.
- SentrySearch/Gemini text-to-video retrieval. It returns nearest ranked clips, including
  unrelated ones. It is not reliable incident detection or a clothing detector.
- Preparation status, explicit consent for AI indexing, and video-bound time-window fixes.

## Current work: optional visual review

Implemented a second stage that sends up to six sampled JPEGs from each of the first five
retrieved windows to Gemini after explicit per-search consent. Results are separated into
supported, unclear, and not-supported groups, with reasons and sampled evidence timestamps.
All underlying result statuses remain uncertain. Missing frames or malformed output cannot
be turned into supported matches. Unchecking image checking retains the old ranking-only flow.

Files: `backend/tanya/visual_review.py`, `search_engine/visual_review_bridge.py`, web routes,
dashboard UI, and regression tests. Offline suite: **163 passed, 4 skipped**. The skipped tests
need the original synthetic trial index. Browser consent controls were checked.

## Latest addition: local search feedback

Correct/Wrong/Unsure buttons now save the original query, indexed filename, video id, window,
search mode and UTC review time in `search_feedback.db` beside the index. A repeated choice
updates the same query/window/mode record. CSV export is available even before any reviews.
Reviews do not retrain the AI; new cards do not preload old selections. No new Google calls
were made for this work. No new footage has been supplied. Key replacement is still unverified.

Validation: offline persistence/update/CSV and invalid-input checks; browser saved Correct,
changed to Wrong and downloaded CSV using an isolated synthetic fixture. The real four-video
application was restored afterward. All data from that UI fixture stayed outside the real
library. See README for use. Next: get real authorised footage, verify private key rotation,
and have the teammate review PR #2. Do not merge automatically.

## Earlier limited single-frame checks

The user approved three visual queries: “people wearing black shirt”, “person wearing black
clothing”, and “fire and smoke”, with up to 90 sampled frames total and an estimated cost below
US$0.10 (not a billing cap). All three initial requests failed with a Google ClientError.

A text-only diagnostic then identified HTTP 404: `gemini-2.5-flash` was listed but unavailable
to new users. Google recommended `gemini-3.8-flash`. A renewed three-query attempt (up to 90
frames, estimated below US$0.15, actual billing may vary) then found HTTP 400: MINIMAL thinking
was unsupported for this account/model. The batch was interrupted. The unsupported thinking
configuration has been removed, and a text-only structured generation request succeeded.

To remain inside that approval's frame allowance, subsequent smoke tests use only two windows
and one frame per window, with no changes to the production five-window/six-frame limits:

- “people wearing black shirt”: both checked room windows were **unclear** because a zipped
  black jacket hides whether a black shirt is underneath. No supported match was invented.
- “person wearing black clothing”: the room clip was supported at 0 seconds; the checked
  synthetic clip was rejected because no person is present. Other windows were not checked.
- “fire and smoke”: the first small attempt failed during text retrieval, before frame upload;
  the first image retry timed out. A final two-image retry with a longer timeout succeeded:
  both synthetic square samples were not supported, with no visible fire or smoke. The other
  three retrieved windows were not checked. No further frame sends remain in this approval.

These checks do not validate all frames, all retrieved candidates, or general CCTV accuracy.
Do not claim a finished detector or that absent events have been ruled out.

## Default multi-frame website follow-up

The user separately approved the same three queries, up to 90 frames total, through the actual
website with unchanged production limits. No retries are included without checking that cap.

| Query | Images / windows | Website outcome |
|---|---|---|
| people wearing black shirt | 29 / 5 | 0 supported, 2 unclear room windows (shirt hidden by jacket), 3 unrelated windows not supported |
| person wearing black clothing | 23 / 4 | 1 supported room window, 0 unclear, 3 unrelated windows not supported |
| fire and smoke | 29 / 5 | 0 supported, 0 unclear, all 5 windows not supported in sampled images |

The supported evidence button at 6 seconds opened the room video at exactly 6 seconds with
media ready and no reported playback error. Offline integration now exercises real frame
sampling and all three result groups, including thumbnail and range-enabled video URLs.

Next steps:

1. The three approved website tests completed, using 81 images total, without retries.
   No additional live tests were run. Results do not establish absence between sampled frames.
2. Validate on representative authorised CCTV with independent annotations. Use
   `docs/cctv-accuracy-checklist.md` and a private copy of `docs/cctv-validation-template.csv`.
   The current four clips are not a deployment benchmark. Obtain new Google upload/cost
   approval before additional requests beyond the current three-query allowance.
3. Privately replace/revoke previously shared API keys; never paste the replacement in chat.
4. Fix issues found in broader testing, update this checkpoint and push this same branch.

## Device and data boundaries

The existing website is http://localhost:5001/ on the laptop. It is not cloud-hosted and is not
available when that laptop is offline. Cloud coding needs a separately configured environment
with access to the private repository. It does not automatically copy local footage, extracted
frames, databases, search embeddings, Python environments, or `.env`.

No footage, images, databases, or API keys are committed. Never paste a key into chat. Keys
previously pasted by the user still need private replacement and revocation. Telegram alerts
remain deferred. Do not merge the PR without the user's instruction.
