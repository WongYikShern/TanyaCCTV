# TanyaCCTV roadmap — 20 October 2026

Status at the time of writing: PR #5 (`feature/macos-workflow-validation`, head `fa4459c`) is open
and not merged. An integration copy (PR #5 + the owner's dashboard polish + the handover fixes)
passes 413 backend tests on Windows (420 with SentrySearch configured)
and a full synthetic browser walkthrough with mocked AI.

"Real footage" below means authorised CCTV-like recordings with human-made labels. "Paid API"
means Google Gemini calls that send queries, frames or videos and may be billed.

## Essential reliability (do before the demonstration)

| # | Priority | Problem it solves | Expected result | Depends on | Effort | Acceptance criteria | API / paid / real footage |
|---|---|---|---|---|---|---|---|
| R1 | P0 | PR #5 and the owner's UI polish live in different places; the running website on port 5001 serves stale code | One reviewed branch with everything, and a restarted website | Owner approval of the integration plan | Small | Branch contains PR #5 + owner UI edits + fixes; 413/420 tests pass on Windows; website restarted shows the hero dashboard and scene-scan controls | No |
| R2 | P0 | Demo must work without internet or a key | Offline replay demo runs on Windows with playable H.264 footage | R1 | Small | `run_offline_demo.py` with `TANYA_SENTRY_PYTHON` set: both clips "Plays in browser"; 4 replayed queries; report exports | No |
| R3 | P1 | Old scene-scan evidence added before the provenance fix still says "image check, rank N" | Existing investigations show accurate provenance | R1 | Small | Owner checks real investigations; any affected clip is removed and re-added (no migration rewrites history) | No |
| R4 | P1 | Changed-file detection uses file size only (cheap); same-size edits are caught only at export | Optional "Verify sources now" button that re-hashes on demand | R1 | Small | Button runs the export's hash check and updates badges; never automatic on page load | No |
| R5 | P1 | Scene scan holds the single global lock during a Google batch, so uploads/indexing wait | Clear "scan in progress" state; or a per-feature lock | R1 | Medium | During a scan, other actions show why they are disabled; no deadlocks in tests | No (tests mock the reviewer) |
| R6 | P2 | Text-file encoding bugs can reappear | Guard test stays in CI | Done (`test_text_encoding.py`) | — | Fails on any `read_text()`/`write_text()`/text `open()` without an encoding | No |

## Search quality and evaluation

| # | Priority | Problem it solves | Expected result | Depends on | Effort | Acceptance criteria | API / paid / real footage |
|---|---|---|---|---|---|---|---|
| S1 | P0 | CAVIAR events are derived from publisher labels but not independently checked | Human-verified events | Done: dataset, rules, review page (`build_real_dataset.py --serve-review`) and two-reviewer merge (`apply_label_review.py`) | Small (≈30–45 min per reviewer) | Two reviewers review all 33 events independently; `apply_label_review.py` reports 0 disagreements; benchmark shows 30 of 30 human-verified | Licensed public footage, local; no API |
| S2 | P1 | No live search result exists on real footage | Ranked and scene-scan scores on the 22 CAVIAR queries | S1; owner approval of `run_benchmark.py --plan` (≈US$0.12 indexing + ≤2,508 images / 88 requests) | Small to run | `run_benchmark.py --ranked … --scan …` reports per-mode and common-query results with sample sizes | **Paid API**, licensed public footage |
| S2a | P1 | Timestamps limited by window size (ceiling: IoU ≥ 0.5 possible for only 30–43% of real events) | Evidence span measured live; then decide on shorter chunks/stride | S2 | Medium | Evidence span vs window compared on CAVIAR test split; no tuning on the test split | Paid API |
| S2b | P2 | RainSnow has no event labels | Labelled vehicle/pedestrian events at night and in weather | Kaggle credentials; human labelling time | Medium | Same manifest format and review workflow as CAVIAR | Licensed public footage; no API to label |
| S3 | P2 | Merged windows are loose (recall@5 1.0 but only 0.455 at IoU ≥ 0.5) | Tighter "inspect this part" guidance | S2 baseline | Medium | Improvement shown on held-out labels, not the tuning set | Paid API only if re-querying |
| S4 | P3 | Loitering and parked-vs-moving cars are confused by ranking | Documented limitation, or a validated scene-scan workflow for them | S2 | Medium | Only claim support with measured results | Paid API, real footage |

## Optional features (after the demonstration)

| # | Priority | Problem it solves | Expected result | Depends on | Effort | Acceptance criteria | API / paid / real footage |
|---|---|---|---|---|---|---|---|
| F1 | P2 | Scene-scan searches are not saved to investigations like ranked searches | Saved scan queries with their plan (scope, image budget) | R1 | Small | Saved search shows "direct footage scan", scope and approval time; re-running needs fresh consent | No |
| F2 | P2 | No camera/site grouping | Camera name and location per recording | R1 | Medium | Library filter by camera; reports list camera | No |
| F3 | P3 | Alerts (e.g. Telegram) | Out of scope until accuracy is measured | S2 | Large | Not started without measured precision on real footage | Paid API, real footage |
| F4 | P3 | Online hosting / accounts | Out of scope: local prototype by design | Security review | Large | Not started for the hackathon | — |
