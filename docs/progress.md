# Phases 6–9 progress

Branch `feature/investigation-casework`, based on `main` at `d1e51db`. Nothing is committed or pushed
without the project owner's approval.

## Plan and acceptance criteria

| Phase | Delivers | Accepted when |
|---|---|---|
| 6. Investigations | Create, rename, close and reopen investigations. Saved queries with their settings. Add or remove search candidates. Evidence timeline. Open footage at a timestamp. Notes and Correct/Wrong/Unsure decisions. Export. | Every action works through the API and the dashboard, has tests, and the demo workflow covers it. |
| 7. Event understanding | An extended synthetic event dataset (entry, exit, loitering, fall, vehicles, negatives). Per-event-type metrics, false-positive and miss analysis, and a support-level table. | The dataset and harness are reproducible. Measured results are shown only where real responses exist; everything else is labelled unvalidated. Live measurement needs the owner's approval. |
| 8. Evidence and reporting | An append-only audit history. Stable source references. Reports (HTML and JSON) separating human-confirmed evidence from candidates. Safe handling of missing or changed videos and corrupted data. | Tests show reviews are never silently overwritten, missing sources are flagged, and corrupt files fail safely. |
| 9. Polish and demo | Setup diagnostics for the new data. Dashboard states. Updated demo guide and end-to-end demo test. Measured performance. Docs. | The full suite passes with skips explained, `git diff --check` is clean, and the demo can be repeated. |

## Design decisions

1. **Investigations live in their own SQLite file** (`investigations.db`, next to the index). The
   Milestone 1 schema and the feedback store stay untouched.
2. **Evidence points at the video's SHA-256 content hash**, plus the file name and path at the
   time it was added, and the time window. Each time an investigation is read, that reference is
   checked against the current library:
   - a renamed file is still found
   - deleted or modified footage is flagged as missing
   - the stored reference is never rewritten.
3. **Nothing is silently changed.** Removing evidence is a soft removal, and every meaningful
   change goes into an append-only audit log, including a review's previous value.
4. **Reviews reuse the existing feedback store.** A decision on an evidence item is also saved as
   search feedback, so search result cards show it.
5. **Timeline order uses positions within each recording.** Nothing in the footage gives an
   absolute time. An operator can enter a recording's start time, which orders clips across
   cameras. Without it, the timeline groups clips by recording and says so.
6. **Reports keep the categories separate:** human-confirmed (Correct), rejected (Wrong), unsure,
   and unreviewed candidates. Retrieval scores appear only as ranking context, never as evidence.

## Status

### Phase 6: investigations (complete, 19 October 2026)

- **Storage.** `tanya/investigations.py` adds investigations, saved queries, evidence, recording
  start times and an append-only audit log, in a separate `investigations.db`.
- **API.** Routes for create, list, open, rename, close/reopen, saved queries (saved automatically
  when a search names an investigation), add and remove evidence, review (decision and note),
  camera start time, history, and report export (HTML/JSON, by POST).
- **Security.** Every method other than GET, HEAD and OPTIONS now needs the CSRF token.
- **Server-side references.** Evidence takes its source (content hash, name, path, duration) and
  its thumbnail from the server's own database; values sent by the browser are ignored.
- **Reviews.** Decisions are mirrored into the existing search feedback, so search cards show them.
- **Dashboard.** An Investigations panel, a "Save searches and clips to" selector, "Add to
  investigation" on result cards, the evidence timeline, decisions and notes, camera start
  times, report download and the change history.
- **Tests.** 34 investigation tests: storage rules, audit history, timeline, renamed and missing
  sources, CSRF on every method, ignored browser-sent hashes and thumbnails, HTML escaping in
  reports, closed investigations, and a corrupt `investigations.db`.
- **Browser walkthrough.** On the isolated synthetic workspace with the fake bridge: create, two
  saved searches, add clips, Correct/Unsure→Wrong, a note, camera start times (camera-time
  order confirmed), open footage at 0:16, HTML report (1 confirmed, 1 rejected, 2 embedded
  frames), and the change history. No console errors.
- **Backend suite.** 261 passed, 8 skipped, 0 failed (266 / 3 with `TANYA_SENTRY_PYTHON`).

### Phase 7: event understanding (complete offline; live measurement awaits approval)

- **Event dataset.** `make_demo_footage.py --set events` adds `cam3_entrance` (entering,
  loitering, leaving), `cam4_driveway` (car arriving and parking, parked, driving away) and
  `cam5_corridor` (walking, a 3 s fall, lying). The default demo set is unchanged and still
  byte-identical to the evaluated clips.
- **Ground truth.** `evaluation/synthetic_events_v2.json` has 16 queries (11 positive, 5
  negative), each annotated across all five clips.
- **Harness.** Adds an event-type breakdown, error analysis (confusions vs background, missed
  events), and an `indexed_videos` guard (events outside the recorded index are excluded, not
  counted as misses). Unmeasurable queries are reported as "not measured".
- **Measured findings** (recorded real search, 3 queries):
  - confusion between adjacent events in the same scene
  - background windows in the top 5
  - the negative query returns the scenes that have content in them.
- **No ranking or threshold changes.** Three queries can't justify them; one candidate (trimming
  window ends) was rejected as tuning to the data.
- **Support table** with approval details: `docs/event-support.md`. Measuring entry, exit,
  loitering, fall and the vehicle events needs about **US$0.15** of Google processing, on
  synthetic clips only. Approval was requested in the final report.
- **Tests.** 26 evaluation tests. Backend suite: 267 passed, 8 skipped, 0 failed (272 / 3 with
  `TANYA_SENTRY_PYTHON`).

### Phase 8: evidence and reporting (complete)

Built during Phase 6 and verified here:

- the append-only audit log
- source references by content hash
- soft removal
- reports separating human-confirmed evidence from candidates
- missing and renamed sources
- safe failure on a corrupt `investigations.db`

Added in Phase 8:

- **SQLite triggers** make the audit log append-only, forbid deleting evidence, and lock the
  evidence reference columns (hash, file, window, query, mode, time added). Only the decision,
  note and removal fields can change.
- **Source verification at export.** Every available source file is re-hashed (once per file) and
  compared with the reference. Reports show "content verified", or flag **CHANGED** when a file
  was modified after it was referenced. A "Changed sources" count appears in the summary.
- **Corrupt search-review file.** A review decision is still saved in the investigation. The
  search-card mirror is skipped with a warning, and the file is left unchanged.
- **Tests.** 5 new ones: triggers, verification, hash-once, the corrupt feedback file, and a
  missing thumbnail in a report. Investigations: 39 tests.

### Phase 9: polish and demo readiness (complete)

- **Setup check.** `check_setup.py` also verifies `investigations.db` and `search_feedback.db`
  (read-only integrity check; a damaged file is reported with a fix and left unchanged).
- **Dashboard.** "Preparing the report…" state, with the export buttons disabled while the
  sources are re-hashed. A warning when a decision was saved but the search-review mirror
  failed. Empty and closed states for investigations.
- **Demo.** `docs/demo.md` part 2 (steps 9–14: investigation, saved searches, timeline with
  camera times, decisions, report), plus new troubleshooting rows.
  `test_demo_workflow.py::test_documented_investigation_workflow` runs it end to end with
  recorded results.
- **Performance** (`docs/performance.md`), 50-clip investigation:
  - add a clip: 19 ms
  - open the investigation: 14 ms
  - JSON report: 47 ms
  - HTML report: 68 ms (1.2 MB)
  - SHA-256 hashing: about 1 GB/s, so verifying a 2 GB recording adds about 2 s at export
- **Docs.** README (investigations section, guides, layout, test counts), `continue-work.md`
  checkpoint, `event-support.md`, `search-evaluation.md`.
- **Final tests (Windows, no key).** Backend 279 passed, 8 skipped, 0 failed (284 / 3 with
  `TANYA_SENTRY_PYTHON`). Bridge offline 29 passed, 4 skipped.

## Pending, and needing the owner

- **Approve live measurement of the new event types.** 3 synthetic clips (150 s, about 182
  frames) prepared for AI search, plus 16 text queries: about **US$0.15**. See
  `docs/event-support.md`.
- **Approve AI preparation of the demo footage** for a live demo: about **US$0.10**.
- **Real authorised CCTV clips** with annotations. Real-world accuracy remains **unverified**.
- **Privately rotate** previously shared API keys.
- **Commit and push** this branch.
