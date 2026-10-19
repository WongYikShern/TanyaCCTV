# Teammate handoff — 19 October 2026

**Current branch:** `feature/macos-workflow-validation`
**Review PR:** https://github.com/WongYikShern/TanyaCCTV/pull/5
PR #5 is open, not merged. PRs #2–#4 were already merged before this branch started.
Do not continue from the older `feature/local-web-dashboard` branch.

## Latest core-search checkpoint

The default Search method is now **Scan footage for this scene**, covering all locally indexed
uploaded recordings (or a selected recording/range), without the previous top-retrieval gate.
No embedding preparation is needed for this path. A local plan lists the exact scope and maximum
image/request budget; explicit approval precedes Google sends. Results stream by bounded batches,
with evidence jumps, possible matches, cancellation and no automatic retries. Fast similarity
search remains available. Read **`docs/scenario-search.md`** for use, live outcomes and limits.

Live checks found the right living-room and boat footage, rejected fire/smoke and a false fall,
and supported the walking-then-raised-hands sequence in Chrome. One sequence attempt timed out;
a separately approved retry completed after a supported latency setting was applied. These
selected successes do not establish arbitrary-video reliability. All six approved attempts
are consumed; do not resend footage under these old approvals. No new CAVIAR/RainSnow Google
processing has been approved or run. The normal website is running at localhost:5001/#search;
research-only viewers use that same port and must be stopped before switching.

## Latest acquisition checkpoint

The initial varied-footage collection is complete: **11 licensed real-camera clips**, about
32 minutes 10 seconds total. Five CAVIAR staged indoor clips/labels are complemented by six
AAU RainSnow natural traffic clips across four intersections, with daylight/night, rain/snow,
vehicles and pedestrians. Originals and H.264 review copies are local and ignored by Git.
Source URLs/hashes are in `evaluation/datasets/caviar-small.json` and `rainsnow-small.json`.
Read **`docs/real-cctv-footage-handoff.md`** for permission, exact coverage, checks and reproduction.
Both viewers use localhost:5001; stop one before starting the other. Both block AI calls.
No real-camera Google processing has been approved or run. Full manual event labelling,
accuracy evaluation and exact timing remain next tasks.

## Resume safely

In a clean existing checkout (save your own uncommitted work before switching):

```bash
git fetch origin
git switch feature/macos-workflow-validation
git pull --ff-only origin feature/macos-workflow-validation
```

Read README; use your own Python environments and private key. No footage, frames, databases,
search indexes, virtual environments or keys are in Git. Do not copy `.env` into a PR/chat.
On macOS/Linux:

```bash
.venv/bin/python backend/scripts/check_setup.py
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python backend/scripts/run_offline_demo.py
```

On Windows replace `.venv/bin/python` with `.\.venv\Scripts\python.exe`. Stop any other
website on port 5001 first. Open http://localhost:5001/. The offline replay demo creates a
fresh isolated synthetic workspace and blocks new AI calls; export before stopping. Use
`run_web.py` instead for the real local library and configured search integration.

## Completed and verified

- Redesigned dashboard, upload/indexing, frames, browser playback and seeking.
- Search, local Correct/Wrong/Unsure feedback, investigations, notes/history and HTML/JSON reports.
- Mac compatibility fixes and strongest-source-chunk navigation, preserving full context.
- Five-clip live synthetic retrieval run: 32 video embeddings, 16 queries, no retries; saved
  recording `evaluation/recordings/2026-10-19-events.json`.
- Separate targeted visual run: 66 approved images, three calls, no retries. Loitering and
  parked-car true candidates became first supported; fall sequence supported, ambiguous
  upright/lying sequence stayed unclear. See `docs/targeted-visual-validation.md`.
- Additional strict temporal evaluation, entirely offline: `docs/temporal-validation.md`.
- Latest full backend verification after the direct-scan and playback fixes: **339 passed,
  6 skipped**. Four skips need exactly the original trial index; two are Windows junction
  tests. JS syntax validation passed. The suite includes multi-video direct scanning,
  approval/session boundaries, new-upload snapshots, changed sources, timeout/no-retry
  behaviour and the evidence-at-window-end playback regression.
- User confirmed private key replacement and old-key revocation; the new key completed the
  approved calls. Revocation is user-confirmed, not independently verified. `.env` is ignored.

## Actual limitations

Raw ranking still confuses loitering and parked/moving cars. Targeted visual filtering succeeded
on three selected positive synthetic queries, not a representative CCTV benchmark. Broad
windows still include multiple actions. Merged recall@5 is 1.000 for any overlap but only
0.455 at IoU >= 0.5. Five negative retrieval queries all returned irrelevant clips. No claim
of reliable detection, precise timing, absence, identity matching or automatic alarms.

## Next work, in order

1. Review PR #5 and decide whether to merge. Further development can continue on this branch
   and push to the same PR; do not merge automatically on the owner's behalf.
2. Use the acquired 11-clip real-camera collection. Watch locally, independently label events,
   verify supplied CAVIAR labels and annotate exact event times before searching. Add footage
   only for identified coverage gaps; collection alone does not establish detection accuracy.
3. Use `docs/cctv-accuracy-checklist.md` and a private copy of the CSV template. Agree what
   counts as a positive/negative and acceptable timing before using evaluation results.
4. Present the exact Google-upload/query/image plan and estimated cost before new API calls.
   The five-video/16-query and 66-image approvals are complete/consumed; do not silently reuse them.
5. Compare candidate timing improvements on held-out labels, including stricter localization
   metrics. Keep source scores as ranking signals, preserve uncertainty and manual review.
6. Push code, tests, measured outcomes and updated limitations to the review branch.

The public dataset acquisition is complete. Local label review can proceed; AI processing
requires the separate approval above. Broader real CCTV and generalization still need additional inputs. Telegram
alerts and online hosting remain optional future scope.
