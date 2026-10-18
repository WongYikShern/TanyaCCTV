# macOS workflow verification — 19 October 2026

Base: merged `main` at `4922b36`; work branch: `feature/macos-workflow-validation`.
No Gemini calls or real CCTV processing were used. Local packages already satisfied the README;
`pip check` reported no broken requirements. The setup checker found the pinned Python 3.12
search environment, local database integrity, and key presence without showing its value.
Key presence is not verification of private rotation, API access, quota or billing.

| Priority | Verified | Limit |
|---|---|---|
| Setup/UI | Redesigned dashboard, system readiness, local H.264 synthetic footage | Current local key was not sent to Google |
| Playback | Search opened at 16 s; frame click sought to 25 s; media ready without player error | Broader CCTV codec coverage still needs recordings |
| Upload/index | API suite covers upload, duplicate content, non-Latin names, extraction and media ranges | Browser chooser automation blocked by extension file-URL access; no permissions changed |
| Investigations | Browser created case, saved search, added evidence, saved Correct with note | Rehearsal data lives in a separate temporary folder |
| Reports | HTML and JSON downloaded; inspected synthetic note, confirmed count and source verification | Source integrity is not proof that a scene is a real incident |
| File failures | Regression tests cover missing sources, corrupt stores, unsupported files and conversion errors | Not every camera vendor's export has been tried |
| Responsive UI | Investigations, search and library checked at 390 px with no horizontal overflow | Limited Chrome check, not an exhaustive device matrix |
| Image check | Existing consent, grouping, sampling and fail-closed tests pass | No new live image evaluation was run |
| AI evaluation | Re-scored existing four recorded queries, plus partial extended event dataset | No new predictions; entry/exit/loitering/fall/new vehicle events remain unmeasured |

## Fixes

- Double-slash media URLs now return 404 directly rather than redirecting. Folder confinement
  remains enforced by the existing resolved-path check.
- Failed-encoder regression uses a mocked nonzero process result rather than a Windows `.cmd`
  file, so it tests conversion failure on every OS.
- Unconfigured CLI test now isolates auto-discovery; an installed `.venv/sentry` no longer
  invalidates the test's assumption.
- Added a separately launched offline replay demo. It creates an isolated synthetic library,
  replays only the four recorded queries, blocks image checking and AI preparation server-side,
  and labels the UI/results as recorded replay. It works without a key. New uploads are local
  but not in recorded search results. Fresh launches start new workspaces; export before stopping.

## Test results

- Backend, pinned environment configured: **300 passed, 6 skipped**. Four skipped cases require
  the original two-video trial index; the current index is different. Two are Windows junction tests.
- Bridge, excluding live tests: **15 passed, 14 skipped, 4 deselected**. The skips require that
  same original trial index; no live tests ran.
- JavaScript syntax and whitespace checks passed. No browser console errors/warnings were
  observed during the recorded-search, evidence and report walkthrough.

## Recorded ranking baseline (three positive queries)

| Level | Precision@5 | Recall@5 | Mean first-relevant IoU |
|---|---:|---:|---:|
| Raw chunks | 0.667 | 1.000 | 0.417 |
| Merged windows | 0.500 | 1.000 | 0.867 |

The negative fire/smoke query returns irrelevant nearest windows. It is not a correct rejection
or proof of absence. The extended annotations include 16 queries, but only four have recorded
responses, of which three are positive. Unmeasured cases remain explicitly excluded. No
threshold or model tuning is justified by these small results.

Remaining: separately approved live evaluation, representative authorised footage and labels,
private key rotation confirmation, and teammate review of the new PR. Telegram, online hosting,
identity matching and automated incident decisions are outside this change.
