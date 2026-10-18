# TanyaCCTV demo guide

An honest 8-step demo of the local investigation workspace on synthetic footage. Allow about
10 minutes, plus one-time preparation. Commands are for Windows PowerShell, run in the project
folder. On macOS/Linux, use `.venv/bin/python` instead.

> **What to say up front:** TanyaCCTV helps a person *find* footage worth checking. Search results
> are ranked by similarity, not detected incidents. Every result stays unverified until a person
> reviews it, and a low or missing result does not prove that something did not happen.

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

4. **Prepare AI search (needs approval, costs money).** Select **Review AI indexing plan**. For
   the two demo clips it should list 2 videos and about 122 frames, which is about **US$0.10** on
   the paid tier (an estimate, not a spending cap). This sends the video to Google. Tick the
   approval box and select **Prepare AI search** only if you accept that. Do it once, well
   before the demo.

5. **Rehearse** steps 3–8 below once. If the network may be unreliable, keep the browser tab open
   afterwards, and also save review pages from the command line:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\search_videos.py "a red car" --html data\demo_car.html
   ```

## The demo (8 steps)

| Step | Do | Point out |
|---|---|---|
| 1. Import a recording | Show the two clips in **Video library**. Optionally upload a short authorised clip with the permission box ticked. | Uploads stay local. Duplicate content is detected ("already in your library"). Non-Latin file names are accepted. |
| 2. Check readiness | Show the badges **Frames ready** and **AI prepared**, and the search panel's coverage line. | Extracting frames and preparing AI search are separate, explicit steps. |
| 3. Search | Untick image checking, then search **a red car**. | Ranked mode sends only the query text to Google. |
| 4. Ranked results | Point at **cam2_carpark.mp4, 0:16–0:40**, the "Ranked candidate · not visually checked" and "Not yet reviewed by a person" badges, and "Ranking score … (not a probability)". | Lower cards (for example the empty car park at 0:00–0:18) show that nearest neighbours always appear. That's why nothing is auto-confirmed. |
| 5. Open the footage | **Review clip →** opens the player at 0:16. | It plays the original recording, not a copy. |
| 6. Inspect frames | Scroll the **Frame timeline** and select a frame to jump to it. | The extracted frames are the evidence a person checks. |
| 7. Record a review | Select **Correct** on the car clip and **Wrong** on the empty car park. Run the same search again: the badges now read "Your earlier review: …". | Reviews are stored locally, don't retrain anything, and don't change ranking. |
| 8. Export | **Export my search reviews (CSV)**. | Spreadsheet formulas in exported text are neutralised. Check the file before sharing it. |

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
| "Setup needed" in the search panel | The key or search environment isn't visible to the website. Stop it, set both in the same PowerShell window, and start it again. Run `check_setup.py`. |
| "Cannot start: 127.0.0.1:5001 is already in use" | A website is already running: open http://localhost:5001/, or close the other window. |
| Search fails or times out (network) | Local features still work: library, frames, playback, reviews and export. Show the saved `data\demo_*.html` pages and `docs/search-evaluation.md` instead. |
| The clip shows black / doesn't play | The video isn't H.264. Use the frame timeline, or regenerate the footage with FFmpeg available. |
| A video is listed as "AI preparation needed" | Review and approve the AI indexing plan (costs money), or demo only the prepared clips. |

## Honest limitations to state

- **Not validated on real CCTV.** Ranking was measured on 3 positive queries with cartoon footage.
- **Results are 10-second chunks**, grouped into windows. They're good for finding a moment, not
  frame-accurate.
- **Search needs internet and a Gemini key,** and AI preparation sends video to Google.
- **Image checking is experimental.** It looks only at sampled frames and can be wrong.
- **No alarms.** There are no automatic alarms, identity recognition or decisions about people.
