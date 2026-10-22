# TanyaCCTV demo guide

An honest demo of the local investigation workspace on synthetic footage, in two parts: searching
and reviewing (steps 1–8), then an investigation with an evidence timeline and a report
(steps 9–14). Allow about 15 minutes, plus one-time preparation. Commands are for Windows PowerShell, run in the project
folder. On macOS/Linux, use `.venv/bin/python` instead.

> **What to say up front:** TanyaCCTV helps a person *find* footage worth checking. Search results
> are ranked by similarity, not detected incidents. Every result stays unverified until a person
> reviews it, and a low or missing result does not prove that something did not happen.

## Command-centre walkthrough (about 4 minutes, live AI)

The dark command-centre view on real public CCTV footage: camera wall, camera map, a search you can
watch, boxes from the AI, following a person across cameras, watch-mode alerts and an AI case summary.
Uses the normal website (`run_web.py`) with a Gemini key. Run each step once beforehand; if Google is
busy the app retries "busy" replies up to 3 times, and the offline demo below needs no internet.

**Footage.** The library holds 4 CAVIAR mall clips (lobby, atrium, corridor, shop front; the corridor
and shop front are the same moment from two cameras) and three 30-second RainSnow traffic cuts (rain,
night, snow). Older test clips are *hidden* (Cameras → Hide), so they stay out of the wall, map and
"All recordings". Names, places and map positions are a demo layout typed in by hand and kept in
`data/cameras.json` (not in Git). The footer credits CAVIAR (CC BY-SA) and AAU RainSnow (CC BY 4.0).

In front of the judges:

1. **Dashboard.** The camera wall loops each recording, labelled RECORDED with its position in the
   recording. "These are recordings; the same pipeline takes footage as it arrives (step 6)."
2. **Search.** Type, or press the mic and say, "a person walking along the corridor". Approve the plan
   (it shows how many images are sent). Up to three requests run at once: frames flip in the viewer,
   cameras light up in the sweep row and on the mini map, and when the AI finds something it locks on
   to the frame with the AI's box around the person.
3. **Results.** Search time, footage searched, likely moments, "% less to watch". Each match shows the
   AI's box and reason; press **Play key moment**.
4. **Follow this person.** Search "a man in a white jumper walking along the corridor" on the
   **Corridor** camera, then press **Follow this person** on the match. It searches only the cameras
   within 150 m on the map (the mall cameras), using the AI's description of him. In this CAVIAR
   recording the same man is filmed by two cameras: he leaves the shop (**Shop front, 10:35:17** on the
   camera's burned-in clock) and walks down the corridor (**Corridor, 10:35:20**). With each camera's
   "Recording started at" time set (Cameras → Rename / place), the route uses those clock times.
   **Show route on map**: an animated path with time chips. Say "possibly the same person": the app
   never identifies anyone.
5. **Investigation.** Add the clips, mark them Relevant, then **AI incident summary → Draft with AI**
   (text only, no images). Read it and **Save as case summary**; it goes into the report.
6. **Watch mode.** On the dashboard, "Alert me when… a person lying on the floor", approve, **Start
   watching**. Then **Cameras → Add footage** and upload `data/demo-upload/new_lobby_recording.mp4`
   (a fresh encode of the CAVIAR fall scene; an identical copy would be refused as a duplicate). It is
   added, checked automatically, and an alert pops up with a sound, the AI's box and **Play clip**.
   Uploading it a second time is refused as a duplicate, so re-encode another copy for a rehearsal.

**Live monitor: early warnings (no Google needed).** *Live monitor* plays each camera as a live feed and
raises alerts on warning signs found on this computer (fixed-camera motion analysis, about a second per
clip): movement in a watched zone (optionally only during watch hours), someone lingering, someone at a
protected item, a protected item moving (alarm), an item left unattended, someone not moving. A threat
bar shows the highest level in the last 20 s; alerts sound and offer **Watch clip** with the square
following. Draw rules with **Set up warnings** on a feed. Rehearsed: *Parking bay* notice 0:07, warnings
0:12 and 0:17, alarm 0:51 when the motorbike leaves; *Garage* notice at 04:02:51 during watch hours,
lingering warning; *Departure hall* bag unattended at 0:06; *Lobby* "has not moved, may need help" at 0:30
(fall at 0:26). It sees movement, not people or intent: shadows and headlights can trigger it, and
someone who stays still blends into the background after a while.

**Pre-analysed footage (no Google needed).** `data/footage_notes.json` (local, not in Git) holds moments
described by watching each demo recording, with a box on the person or object. A search first checks
these notes, instantly and offline; results are labelled **Pre-analysed match** and the player then tracks
the box. Live AI runs only if no note matches, or via **Also search live with AI**. Try: "a man stealing
a motorbike" (garage 0:27-0:42, parking bay 0:21-0:48 and 0:48-1:00), "bag left behind" (departure hall),
"a person falling" (lobby 0:26-0:38), "man in white jumper" (corridor). Say "these recordings were
analysed in advance"; it is not a live AI result.

**Follow a target in the player.** Opening a match that has the AI's box (**Play key moment**) tracks
that person or object on this computer: a green square follows them during playback, turns grey "not
visible" while they are hidden, and green again when they reappear. Without the AI (for example when
the Google limit is used up), pause any video, press **Follow someone** and drag a square around a
person. Rehearsed on the theft clips: *Garage driveway* (box the man at 0:09; he is not visible inside
the garage 0:12-0:24 and is followed again at 0:28 with the motorbike) and *Parking bay* (box the man in
the helmet at 0:20; followed to the motorbike). Tracking takes about 10 seconds and covers 4 s before to
20 s after the boxed moment. It can drift in dark or crowded footage.

**Map.** Map / Satellite / Hybrid styles, camera view cones (↺ ↻ to turn), a labelled site zone for
cameras sharing a place prefix ("Mall · …"), hover a pin to play its footage.

**Google quota.** A free-tier Gemini key allows only about 20 AI requests per day; a search across all
cameras uses about 6. Enable billing on the key before presenting, or searches will stop with a
"usage limit … used up" message.

Honest points: boxes, reasons and verdicts are AI suggestions; matches are unconfirmed until a person
marks them. Follow-routes are ordered by time within each recording, which assumes the recordings
cover the same period. Watch mode works while the page is open and skips recordings needing more than
60 images. Camera locations are set by a person. The map and voice search need internet.

## Hackathon demo: preset event index, fully offline (default launcher mode)

No Gemini key, no network and no paid call. Searches match your words (explicit synonym rules,
no AI) to events that were annotated in advance, then open the real footage at that time.

```powershell
$env:TANYA_SENTRY_PYTHON = "$HOME\sentrysearch-trial\tools\sentrysearch\Scripts\python.exe"   # FFmpeg for H.264 demo clips
$env:TANYA_YOLO_HOME = "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\TanyaCCTV-YOLO"   # optional: this laptop's YOLO env
.\.venv\Scripts\python.exe backend\scripts\run_offline_demo.py
```

Open http://localhost:5001/ (stop the normal website first; both use port 5001). The launcher
makes a new workspace with:

- the five generated synthetic clips and their scripted events (`make_demo_footage.py`:
  walking, falling, lying, entering/leaving through a door, standing still, red and blue cars);
- the five CAVIAR clips, copied only if `data/cctv_validation/caviar/videos/` holds files whose
  SHA-256 matches the labelled video; labels are the local single-reviewer provisional file when
  present, otherwise the publisher-derived labels;
- the saved YOLO GPU 384 run's person detections for those CAVIAR clips, if found.

Every result shows its source: **Annotated · reviewed by one person** (provisional, not
independently verified), **Annotated (publisher)**, **Scripted demo event** (known by
construction, cartoon footage) or **Person detected (YOLO) · needs review**. Results play from
2 s before to 2 s after the labelled interval; the exact label times are under Details.
Camera words (corridor, front, overhead, lobby, car park, entrance, driveway), colours and
"after/before/between N s" filter results. Unknown or unsupported requests (fights, fire, weapons,
theft, running) return an explicit no-match. YOLO detections appear only for plain person
queries, never for falls or other actions. A video's player page can run YOLO on that one video
when the YOLO environment is set up (about 0.5 s per second of footage on the RTX 3050 Ti).

Suggested script: `a person falling` (CAVIAR staged fall + scripted falls) → open the first
result → `someone entering a shop` (two CAVIAR views + a scripted door entry) → `a person`
(annotated presence plus unreviewed YOLO candidates) → `two people fighting` (honest no-match).
Investigations and reports work as before; index results are saved as ranked-mode clips with no
score (the report does not yet name the index source; see the evaluation notes).

`--dataset synthetic|caviar` limits the footage; `--search replay` starts the older recorded-search demo below.

### Investigation features in the offline demo (22 October 2026 build)

1. **Event timeline (player page).** Below the player, every indexed label for that exact video
   (matched by content hash) is drawn on a bar: provisional single-reviewer CAVIAR labels (solid
   orange), publisher labels (slate), scripted demo events (grey stripes). Overlapping events go to
   separate rows; very dense recordings keep a scrollable list. Select an event (bar or list) to
   jump to its start, or click anywhere on the bar to seek there; a red line follows playback.
   The frame timeline and video controls are unchanged. Outside the demo there is no label index,
   and the card says so.
2. **YOLO person-presence lane.** Cached detections appear in their own dashed amber lane, never
   mixed with labels, with detector confidence, frame count, the largest number of people boxed in
   one frame and the strongest box (time, frame, pixel coordinates; "Strongest box" jumps there).
   The status line says whether results are newly generated, cached for this video and model,
   cached with an unverifiable model (the saved experiment run did not record its weights hash),
   or stale (made with other weights; then not shown). "Find people" beside the player runs YOLO
   on that one video only (GPU if available, otherwise the existing CPU fallback; ~50 MB GPU).
3. **Evidence review.** Decisions read Relevant / Not relevant / Uncertain (stored as
   correct / wrong / unsure, so older data and reports stay valid). Each item shows how it was
   found; event-index clips also show their label, source and status, recorded by the server from
   its own index or detection cache when the clip is added (a client cannot assert provenance).
   The card lists the decision history (earlier decisions are never overwritten: they stay in the
   append-only change history) and how often the note changed.
4. **Reports.** The HTML report is branded, printable and shows summary cards (including
   unresolved = uncertain + unreviewed), label caveats (provisional single-reviewer labels; YOLO
   is not action recognition; synthetic footage), per-item event provenance and detector details,
   decision history, saved searches with their filters, missing/changed source warnings and the
   change log. Frame images are footage, so they are **not** embedded unless "Include frame images"
   is ticked. JSON is `report_version` 2: every version-1 field is kept; new fields are added.
5. **Search filters.** "Filters" under the search box (event-index demo only): event type,
   result source, label status, recording, time range and a minimum YOLO confidence that applies
   to person detections only. Options list only values that exist in the loaded library. Filters
   combine with the words typed (leave the box empty, or type "all", to list everything that
   passes the filters); active filters are shown above the results with a Clear button; saved
   searches remember their filters and "Run again" restores them. Unsupported requests (fights,
   fire...) still return an honest no-match, whatever the filters.

Suggested demo: `a person falling` → open the CAVIAR result → point at the event timeline and its
provisional status → open `EnterExitCrossingPaths1cor.mp4` to show the separate YOLO lane and
"Strongest box" → Filters: Result source = Scripted, search `a person falling` → add a clip to an
investigation, mark it Relevant then Uncertain, add a note → export the HTML report (frames off)
and point at the caveats, history and provenance.

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
