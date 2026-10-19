# Continue TanyaCCTV work from another device

## Latest: approved targeted image checks (19 October 2026)

Same PR #5 / branch `feature/macos-workflow-validation`. Owner approved 66 synthetic images
for loitering, parked car and falling, using cached retrieval. All three calls completed with
no retries; the allowance is consumed. No additional video/text embeddings or real CCTV.

The correct loitering window (raw rank 5) and parked car (rank 2) became the first supported
candidates. Falling was supported on the corridor's visible transition; the lobby's upright/
lying samples stayed unclear rather than inventing a fall. Checked totals: 3 supported,
7 not supported, 1 unclear; one additional candidate was not checked. Broad windows and raw
ranking are unchanged. Saved recording and detailed limitations:
`evaluation/recordings/2026-10-19-targeted-visual.json`, `docs/targeted-visual-validation.md`.

Offline verification: **304 passed, 6 skipped**, with the same original trial-index and Windows-only prerequisites.
SDK visual requests now allow one attempt; further sends require a fresh reviewed approval.
Pending: authorised real CCTV/labels and separate upload approval, independent validation
beyond these selected examples, precise timing, and teammate review. Do not claim reliable
real-world detection or merge the PR automatically.

## Previous: bounded source-chunk review (19 October 2026)

Same branch/PR #5. Compared merge ratios on both recorded datasets, offline: narrower windows
trade recall for timing, so no default/ranking change was justified. Added `review_focus` to API
results and **Inspect strongest chunk…** alongside full-window playback, with explicit wording
that source chunks are not event boundaries. Rankings, scores, full windows, human decisions and
investigation references are unchanged. Missing chunks omit the control; focus is clamped.

Browser replay verified car focus at 24 s with 24–34 s window and full context still 16–40 s.
No additional API calls or real CCTV used. Tests: **303 passed, 6 skipped**. See
`docs/window-review.md` for comparison data and limitations. Loitering/parked-car ranking is
still not fixed; independent real labels and separate further live-evaluation approval are needed.
No additional authorised real footage is available. Teammate review/merge remains their decision.

## Earlier: approved synthetic live evaluation (19 October 2026)

PR #5: https://github.com/WongYikShern/TanyaCCTV/pull/5, branch `feature/macos-workflow-validation`.
User confirmed a new unshared key was saved and both shared keys revoked. The key from `.env`
successfully completed the approved requests; revocation itself is user-confirmed, not independently
verified. `.env` mode was 0600 and the credential was not printed or committed.

- Approved: five synthetic clips (250 s; estimated 304 billed frames), 16 text queries, approx US$0.25.
- Completed: 32 video embeddings and 16 text embeddings, no errors and no automatic retries.
- Used an isolated temporary index, with all chunks included (no still skipping), 10 s / 2 s overlap,
  480 px / 5 fps preprocessing, 10 results per query. No change to the real four-video library/index.
- Saved sanitized recording and synthetic hashes at `evaluation/recordings/2026-10-19-events.json`.
  Re-score using the command in `docs/event-support.md`. Do not repeat live API calls unnecessarily.
- Merged: 9/11 hit@1, P@5 0.508, R@5 1.000, IoU 0.453. Recall uses any overlap, including broad windows.
  Loitering ranked fifth; parked car second; fall localization was poor. All five negatives returned
  unrelated clips. No detection-accuracy or image-check-validation claim.
- Offline regression verification after saving this run: **301 passed, 6 skipped** (same trial-index
  and Windows-only prerequisites as the earlier checkpoint).
- No threshold/model changes. Pending: independent authorised real CCTV and labels, separate Google
  approval for it, and teammate review. No additional real footage has been supplied.

## Previous checkpoint: macOS validation (19 October 2026)

Review PR: https://github.com/WongYikShern/TanyaCCTV/pull/5 (open, not merged).

Branch `feature/macos-workflow-validation`, based on merged main `4922b36` (PRs #2–#4 are
already merged). Earlier checkpoint language about unpushed branches below is historical.

- Setup checker and dependency integrity pass; existing local key presence is not proof of
  private key rotation, API access, or billing availability. No Google requests were made.
- Fixed strict media URL rejection (no double-slash redirect), a Windows-specific fake encoder
  in a Mac test, and the CLI-unconfigured test ignoring an installed auto-discovered environment.
- Added `run_offline_demo.py`: isolated synthetic clips and four recorded queries, server-blocked
  image checking and AI preparation, visible replay banner and appropriate example queries.
- Browser: created an investigation, saved search, added evidence, played at 16 s, sought to 25 s,
  saved decision/note, downloaded HTML and JSON and checked their contents. No console errors.
- Phone width 390 px: investigations/search/library had no horizontal overflow. Upload picker
  automation was blocked by extension file-URL access; no permissions were changed. API tests
  cover upload/indexing, duplicates, corrupt/missing/unsupported files and error handling.
- Backend with the configured pinned environment: **300 passed, 6 skipped** (four trial-index
  cases require exactly the original synthetic index; two junction cases are Windows-only).
- Bridge offline: **15 passed, 14 skipped, 4 live tests deselected** (original trial index
  unavailable). Full detail: `docs/macos-validation.md`.
- Offline recorded baseline reproduced: merged P@5 0.50, R@5 1.00, mean IoU 0.867 over just three
  positive synthetic queries. Entry/exit/loitering/fall/new vehicle queries remain unmeasured.

Run the offline demo per README; each launch creates a fresh workspace and does not touch the
real four-video library. Pending: separately approved live evaluation, representative real CCTV
annotations, private key rotation verification, and teammate PR review. Do not merge automatically.


## Latest checkpoint: branch `feature/investigation-casework` (19 October 2026)

This branch is based on `main` at `d1e51db`. It is not committed or pushed without the owner's
approval. It adds Phases 6–9 (details in `docs/progress.md`):

- **Investigations.** Saved searches, evidence clips referenced by content hash, a chronological
  timeline (optional camera start times), decisions and notes, an append-only history enforced
  by SQLite, and HTML/JSON reports with source verification at export.
- **Event evaluation.** A 5-clip synthetic event dataset (`--set events`) and 16 annotated
  queries. Per-type metrics, error analysis, and honest "not measured" handling.
- **Polish.** Setup checks for the new data files, report loading states, and both demo parts as
  automated tests.

Tests (Windows, no key):

- backend: **295 passed, 10 skipped, 0 failed**
- with `TANYA_SENTRY_PYTHON`: **302 passed, 3 skipped**
- bridge offline: **29 passed, 4 skipped**

No Google calls were made.

Pending, and needing the owner:

- approval to measure the new event types (about US$0.15, synthetic clips only; see
  `docs/event-support.md`)
- approval to AI-prepare the demo footage (about US$0.10)
- authorised real CCTV clips with annotations
- private key rotation
- committing and pushing this branch

## Latest checkpoint: branch `feature/investigation-workspace` (18 October 2026)

This branch is based on `main` at `3bdb1df`. It is not committed or pushed until the project
owner approves. It adds:

- **Setup check**: `backend/scripts/check_setup.py` gives read-only PASS/WARN/FAIL results with
  fixes. It reports only whether a key is set.
- **Startup**: `run_web.py` prints readiness, and exits cleanly with a message if port 5001 is
  busy. The website and command-line tools all find `.venv/sentry` automatically.
- **Duplicate uploads**: identical content already in the library is reported, and no second
  copy is kept. Existing files are never touched.
- **Earlier human reviews**: result cards show "Your earlier review: …" or "Not yet reviewed by a
  person". This is display only and never changes ranking or status.
- **Search evaluation**: `evaluate_search.py`, ground truth, and a recorded real-search baseline.
  See `docs/search-evaluation.md`. Live mode refuses to send anything without
  `--approve-api-calls`.
- **Demo**: `make_demo_footage.py` (byte-identical to the evaluated clips when FFmpeg is
  available), `docs/demo.md`, an automated 8-step demo workflow test, and
  `docs/performance.md` with measured numbers.

Tests (Windows, no key):

- backend: **227 passed, 8 skipped, 0 failed**
- with `TANYA_SENTRY_PYTHON`: **232 passed, 3 skipped**
- bridge offline: **29 passed, 4 skipped**

No Google calls were made, and the real `data/` was not modified.

Pending, and needing the owner:

- approval to AI-prepare demo footage (about US$0.10)
- authorised real CCTV clips with annotations
- private key rotation
- a decision on committing and pushing this branch

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

On Windows PowerShell, use `.\.venv\Scripts\python.exe` instead of `.venv/bin/python`, and see
README "Local website (Windows PowerShell)". Re-run `pip install -r backend\requirements.txt`
first if your environment predates the website (Flask was missing on the Windows laptop).

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
dashboard UI, and regression tests. Browser consent controls were checked.
The originally reported offline result (163 passed, 4 skipped) was from macOS/Linux. See
"Windows verification" below for the results on Windows.

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

## Windows verification (18 October 2026)

Checked on the Windows laptop (Python 3.14.5), with no API key present and no Google calls:

- The environment lacked Flask; `pip install -r backend\requirements.txt` added only Flask
  3.1.3 and its 6 dependencies.
- Before fixes, `pytest backend\tests` gave **2 failed, 160 passed, 5 skipped**. The 2 failures
  were symlink-based security tests crashing with `WinError 1314` instead of skipping.
- Fixed: the symlink tests skip only for that specific Windows permission error. New
  Windows-runnable tests cover the same protections using database paths that point outside
  the folders and directory junctions (which need no special rights). They prove that media
  outside `data/videos` and `data/frames` is neither served nor sent for visual review, and
  each one fails if the protection is removed.
- Fixed: uploads named only in non-Latin characters (e.g. `监控录像.mp4`) were rejected as
  "Choose an MP4…". The extension is now validated on the original name, with a safe fallback
  name `<id>_video.<ext>`.
- After fixes: **185 passed, 7 skipped, 0 failed**. With `TANYA_SENTRY_PYTHON` and the trial
  index, it is 189 passed, 3 skipped. The bridge offline tests give 29 passed, 4 skipped (the
  live Gemini tests, without a key).
- Isolated route and browser checks used copies of the synthetic clips and a fake search
  bridge: upload, indexing, library, frames, range playback, traversal blocking, ranked
  search, Correct feedback and the clip viewer all worked. The real `data/` was not modified.
- `run_web.py` starts on Windows. Without a key, `/api/status` reports `key_ready: false`, and
  the website still allows local upload, frame extraction and browsing.

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
