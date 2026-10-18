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
dashboard UI, and regression tests. Offline suite: **147 passed, 4 skipped**. The skipped tests
need the original synthetic trial index. Browser consent controls were checked.

## Live test status — NOT PASSED

The user approved three visual queries: “people wearing black shirt”, “person wearing black
clothing”, and “fire and smoke”, with up to 90 sampled frames total and an estimated cost below
US$0.10 (not a billing cap). All three initial requests failed with a Google ClientError.

A text-only diagnostic then identified HTTP 404: `gemini-2.5-flash` was listed but unavailable
to new users. Google recommended `gemini-3.8-flash`. The default is now changed to 3.8 Flash
with minimal thinking. A text-only countTokens request to that model succeeded. **Actual image
generation/review with the changed model has not been tested. Do not claim detection works.**

Next steps:

1. Obtain renewed approval before resending frames; the original three visual attempts have
   been used. Recheck pricing for the new model before quoting costs.
2. Run the exact black-shirt query through the website and the other two agreed queries.
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
