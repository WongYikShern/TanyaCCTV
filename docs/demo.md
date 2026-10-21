# TanyaCCTV demo guide

An honest demo of the local investigation workspace on synthetic footage, in two parts: searching
and reviewing (steps 1–8), then an investigation with an evidence timeline and a report
(steps 9–14). Allow about 15 minutes, plus one-time preparation. Commands are for Windows PowerShell, run in the project
folder. On macOS/Linux, use `.venv/bin/python` instead.

> **What to say up front:** TanyaCCTV helps a person *find* footage worth checking. Search results
> are ranked by similarity, not detected incidents. Every result stays unverified until a person
> reviews it, and a low or missing result does not prove that something did not happen.

## Free offline rehearsal (recommended when internet is unreliable)

1. Stop the existing website (Ctrl+C in its terminal).
2. On macOS/Linux run `.venv/bin/python backend/scripts/run_offline_demo.py`.
   On Windows, first point it at the local FFmpeg bundled with the search environment, so the
   generated footage is H.264 and plays in the browser (only the encoder is used; no key or Google
   client is loaded):

   ```powershell
   $env:TANYA_SENTRY_PYTHON = "$HOME\sentrysearch-trial\tools\sentrysearch\Scripts\python.exe"
   .\.venv\Scripts\python.exe backend\scripts\run_offline_demo.py
   ```

   If it prints "FFmpeg was not found … will NOT play", set `TANYA_SENTRY_PYTHON` (or
   `TANYA_FFMPEG`) and start again; frames, replayed search and reports still work without it.
3. Open http://localhost:5001/. Check the **OFFLINE REPLAY DEMO** banner. This generates the two
   synthetic clips in a new temporary workspace and indexes them locally. It does not load
   `.env`, use a key, call Google, or change the real library.
4. Create an investigation, then select it under **Save searches and clips to**. Run `a red car`,
   add the first candidate, open at 0:16 and seek to 0:25. Mark it Correct with a synthetic-demo
   note. Search `a person walking` and add that candidate too; set camera times if desired.
5. Export JSON and HTML reports; inspect decisions, source verification and history. Try
   `fire and smoke` to show unrelated nearest results rather than a detection. Try an unknown
   query to show the explicit unavailable-recording message. Image checks and AI preparation
   are disabled, including at the API.

Only four exact queries are replayed: `a red car`, `a person walking`, `a person lying on the floor`,
and `fire and smoke`. The results were recorded earlier; they are not new model predictions.
Uploaded videos can be locally indexed but are not in these recorded results. Each launcher
run uses a new folder and fresh investigations. Export your work before stopping, and retain
its printed workspace path if you need the raw local data. `--workspace` accepts a new empty
folder only and never overwrites an existing rehearsal.

The browser extension may refuse automated file selection unless it has file-URL access.
Manual local upload still works; this setting is unrelated to TanyaCCTV or Gemini. The current
Mac verification covered upload/indexing through the API rather than changing extension access.

## One-time preparation

1. **Check the setup.** This is read-only and never shows the key:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\check_setup.py
   ```

   Fix every `FAIL`. A `WARN` for the search engine or key only disables AI search.

2. **Create the demo footage.** These are cartoon scenes with known events and no real people.
   The script never overwrites existing files.

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\make_demo_footage.py
   ```

   This writes `cam1_lobby.mp4` and `cam2_carpark.mp4` into `data\videos`:

   - `cam1_lobby.mp4` (60 s): person walking 20–40 s, person lying on the floor 40–60 s
   - `cam2_carpark.mp4` (40 s): red car 20–40 s

   They are converted to H.264 (browser-playable) when FFmpeg is found on PATH or inside the
   SentrySearch environment. Otherwise they still index and search, but won't play in the browser.

3. **Start the website** with the search environment and your key set in the *same* window
   (see README, "Local website (Windows PowerShell)"):

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\run_web.py
   ```

   Open http://localhost:5001/ and select **Index local videos**. Frames are extracted locally,
   in seconds.

4. **Prepare AI search (needs approval, costs money).** On **System & AI setup**, select **Review AI indexing plan**. For
   the two demo clips it should list 2 videos and about 122 frames, which is about **US$0.10** on
   the paid tier (an estimate, not a spending cap). This sends the video to Google. Tick the
   approval box and select **Prepare AI search** only if you accept that. Do it once, well
   before the demo.

5. **Rehearse** steps 3–8 below once. If the network may be unreliable, keep the browser tab open
   afterwards, and also save review pages from the command line:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\search_videos.py "a red car" --html data\demo_car.html
   ```

## Part 1: search and review (8 steps)

| Step | Do | Point out |
|---|---|---|
| 1. Import a recording | Show the two clips in **Video library**. Optionally upload a short authorised clip with the permission box ticked. | Uploads stay local. Duplicate content is detected ("already in your library"). Non-Latin file names are accepted. |
| 2. Check readiness | Show the badges **Frames ready** and **AI prepared**, and the search panel's coverage line. | Extracting frames and preparing AI search are separate, explicit steps. |
| 3. Search | Untick image checking, then search **a red car**. | Ranked mode sends only the query text to Google. |
| 4. Ranked results | Point at **cam2_carpark.mp4, 0:16–0:40**, the "Ranked candidate · not visually checked" and "Not yet reviewed by a person" badges, and "Ranking score … (not a probability)". | Lower cards (for example the empty car park at 0:00–0:18) show that nearest neighbours always appear. That's why nothing is auto-confirmed. |
| 5. Open the footage | **Play from 0:16** opens the full 0:16–0:40 window. **Inspect strongest chunk 0:24–0:34** opens the shorter source chunk first. | It plays the original H.264 recording; other codecs get a local browser copy, the original is unchanged. |
| 6. Inspect frames | Scroll the **Frame timeline** and select a frame to jump to it. | The extracted frames are the evidence a person checks. |
| 7. Record a review | Select **Correct** on the car clip and **Wrong** on the empty car park. Run the same search again: the badges now read "Your earlier review: …". | Reviews are stored locally, don't retrain anything, and don't change ranking. |
| 8. Export | **Export my search reviews (CSV)**. | Spreadsheet formulas in exported text are neutralised. Check the file before sharing it. |

## Part 2: an investigation (about 5 more minutes)

| Step | Do | Point out |
|---|---|---|
| 9. Create an investigation | Under **Investigations**, create "Lobby and car park, Monday". It becomes the selection in **Save searches and clips to**. | Investigations are stored locally in `investigations.db`, and every change is recorded. |
| 10. Search into it | Search **a red car**, then **a person walking**. Each search is saved with its settings under **Saved searches**, and can be run again later. | The search settings are kept so the work can be reproduced. |
| 11. Collect candidates | Select **Add to investigation** on the top card of each search. | Each clip keeps its source: content hash, file name, window, query, rank and score. It stays an "Unreviewed candidate". |
| 12. Arrange by time | Under **Evidence timeline**, enter start times: lobby 2026-10-19 08:59:50, car park 09:00:00. The lobby clip (09:00:06) now comes before the car park clip (09:00:16). | Without start times, clips are grouped by recording, and the page says so. Absolute times depend on the camera clocks being right. |
| 13. Review | **Open footage →** on each clip. Mark the car **Correct** with a note, and the lobby clip **Unsure**. Change your mind once (e.g. Unsure → Wrong). | Earlier decisions aren't lost: **Change history** shows "unsure → wrong". |
| 14. Report | **Export report (HTML)**, then open the downloaded file. | Human-confirmed, rejected, unsure and unreviewed clips are listed separately, each with its content hash, a "content verified" check, the reviewer's note, the change history and the limitations. The report embeds frames, so share it only with authorised people. |

Optional, if approved for this demo:

- Search **fire and smoke**. It still returns clips, which shows why results are never treated as
  detections.
- Turn on image checking with its consent box. It sends up to 30 sampled frames per search to
  Google and costs extra. It sorts candidates into supported, unclear and not supported, all
  still requiring human review.

Expected ranked results, recorded on 17 October 2026 with these exact clips:

| Query | Top window |
|---|---|
| a person walking | lobby 0:16–0:42 |
| a person lying on the floor | lobby 0:40–1:00 |
| a red car | car park 0:16–0:40 |

A fresh index can differ slightly. See `docs/search-evaluation.md`.

## If something goes wrong

| Problem | What to do |
|---|---|
| "AI search: setup needed" in the top bar | The key or search environment isn't visible to the website. Stop it, set both in the same PowerShell window, and start it again. Run `check_setup.py`. |
| "Cannot start: 127.0.0.1:5001 is already in use" | A website is already running: open http://localhost:5001/, or close the other window. |
| Search fails or times out (network) | Local features still work: library, frames, playback, reviews and export. Show the saved `data\demo_*.html` pages and `docs/search-evaluation.md` instead. |
| The clip shows black / doesn't play | The video isn't H.264 and FFmpeg wasn't found for the browser copy. Set `TANYA_SENTRY_PYTHON` or `TANYA_FFMPEG`, or use the frame timeline. |
| A video is listed as "AI preparation needed" | Review and approve the AI indexing plan (costs money), or demo only the prepared clips. |
| "This investigation is closed" | Select **Reopen**: closed investigations are read-only on purpose. |
| A clip says **SOURCE MISSING** | Its recording was deleted or moved out of the library. The reference is kept; restore the original file to review it. |
| A report says **CHANGED** for a source | The video file was modified after the clip was added. Don't rely on it without checking the original recording. |
| "Investigation data could not be read" | `investigations.db` is damaged. It was left unchanged; restore it from a backup or move it aside. `check_setup.py` reports this too. |

Both parts of this guide are exercised by `backend/tests/test_demo_workflow.py`, using recorded
search results instead of live calls.

## Honest limitations to state

- **Not validated on real CCTV.** The recorded cartoon benchmark covers 16 queries
  (11 positive, five negative); it does not establish real-camera accuracy.
- **Results are 10-second chunks**, grouped into windows. They're good for finding a moment, not
  frame-accurate.
- **Search needs internet and a Gemini key,** and AI preparation sends video to Google.
- **Image checking is experimental.** It looks only at sampled frames and can be wrong.
- **No alarms.** There are no automatic alarms, identity recognition or decisions about people.

## Latest offline rehearsal — 21 October 2026

A fresh isolated workspace was generated with two H.264 synthetic videos (60 s and 40 s).
All four fixed replay searches completed. Local video byte-range playback returned HTTP
206; creating an investigation, saving a search, adding evidence, recording an unsure
decision, and exporting JSON/HTML succeeded. The exported report had zero human-confirmed
incidents: this was an automated workflow rehearsal, not human validation. Live indexing
and visual-check endpoints returned HTTP 403 in offline mode. No Google call was made.

The local rehearsal summary and exports are under ignored
`data/cctv_validation/demo-rehearsal-2d4b8a94/`; they are not part of Git. The normal
website and owner library were left running and unchanged. This validates the local
workflow with fresh playable assets, not new AI output or a browser UI walkthrough.

The independent CAVIAR review page is separate: http://127.0.0.1:5003/ while its local
server runs. A human must perform that review and export their own CSV; an automated
demo decision cannot substitute for the second reviewer.
