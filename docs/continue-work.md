# Continue TanyaCCTV work from another device

Checkpoint: 18 October 2026. Branch: `feature/local-web-dashboard`.
Pull Request: https://github.com/WongYikShern/TanyaCCTV/pull/2

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
dashboard UI, and regression tests. Offline suite: **150 passed, 4 skipped**. The skipped tests
need the original synthetic trial index. Browser consent controls were checked.

## Live test status — limited single-frame checks; full validation pending

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

Next steps:

1. Do not resubmit frames beyond the approved cap.
2. Obtain approval for full multi-frame tests before sending additional frames to Google.
   Recheck pricing before quoting costs. Test the default website flow end to end.
3. Inspect actual reasons and evidence. A black hoodie/jacket does not establish the presence
   of a black shirt underneath; use unclear rather than silently broadening the query.
4. Fix any SDK/schema, quota, output-validation or matching issues. Add regression tests.
5. Update this checkpoint and the PR with actual live results and remaining limitations.

## Device and data boundaries

The existing website is http://localhost:5001/ on the laptop. It is not cloud-hosted and is not
available when that laptop is offline. Cloud coding needs a separately configured environment
with access to the private repository. It does not automatically copy local footage, extracted
frames, databases, search embeddings, Python environments, or `.env`.

No footage, images, databases, or API keys are committed. Never paste a key into chat. Keys
previously pasted by the user still need private replacement and revocation. Telegram alerts
remain deferred. Do not merge the PR without the user's instruction.
