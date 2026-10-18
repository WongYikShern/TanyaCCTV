# TanyaCCTV

AI-powered CCTV search and incident-response prototype (university hackathon).

**Milestone 1 — video ingestion and indexing.** The indexer scans a folder of authorised
sample videos, extracts one JPEG every 1–2 seconds, and stores video metadata and frame
timestamps in SQLite.

**Milestone 2 — natural-language search** (command line, optional). Uses
[SentrySearch](https://github.com/ssrajadh/sentrysearch) (Apache-2.0, pinned to commit `d3efd6a`)
with Google's Gemini Embedding 2, in a separate Python 3.12 environment. See
[Natural-language search](#natural-language-search-milestone-2).

A local Flask website and API now provide video upload, frame browsing, and semantic-search
review. Telegram alerts and monitoring rules remain future work.

## Local website (macOS / Linux)

Run these commands from the project folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pytest backend -q
.venv/bin/python backend/scripts/run_web.py
```

Open **http://localhost:5001/**. Keep the Terminal running; Ctrl+C stops the server.
To start again, run only the last command. On Windows, use `.venv\Scripts\python.exe`
instead of `.venv/bin/python`.

The dashboard offers:

- Upload authorised footage (up to 512 MB per file), then extract frames locally.
- Index videos copied directly into `data/videos` with **Index local videos**.
- Browse the video library; select a video to play it and review its frame timeline.
- Search prepared footage with natural language and open matching time windows for review.
- Review an AI indexing plan before explicitly approving the Google transfer and API charges.

Each video has separate labels for **Frames ready** and **AI prepared**. Uploading/extracting
frames does not prepare a video for semantic search. The search panel lists videos still
needing preparation; results also warn when those uploads are not covered. AVI/MKV/M4V videos
can have local frames but require conversion to MP4/MOV for this search engine. A prepared
label reflects the recorded content hash; if the shared SentrySearch index is changed outside
TanyaCCTV, review the indexing plan to verify it again.

H.264 MP4 is recommended for playback. Some video codecs (including the default synthetic
`mp4v` sample) will not play in a browser; extracted images still work, and the original video
can be downloaded. Original videos are never overwritten by uploads.

This server binds only to `127.0.0.1:5001`. It is a local development workspace, with no user
accounts; do not expose it publicly. Run only one website process and avoid running the CLI
indexer/sync simultaneously. Long indexing operations keep the browser waiting; do not close
the page while they run. The website does not alter the existing command-line workflows.

### Enable semantic search on macOS / Linux

Search needs a separate Python 3.12 environment with the pinned SentrySearch version, plus
your own Gemini key. The basic website and local frame extraction work without these.

With `uv` installed, create the separate environment inside the ignored `.venv` folder:

```bash
uv venv --python 3.12 .venv/sentry
uv pip install --python .venv/sentry/bin/python 'git+https://github.com/ssrajadh/sentrysearch@d3efd6a4351251084dc101a24970e40a38e1426d'
export TANYA_SENTRY_PYTHON="$PWD/.venv/sentry/bin/python"
```

`run_web.py` automatically discovers `.venv/sentry` when no explicit search interpreter is
configured. The export above is still needed for the existing command-line search tools.

Set `GEMINI_API_KEY` privately in your terminal or your ignored `.env` file, then start the
website from that terminal. Never put the key in source code or commit it. See the existing
“Natural-language search” section for privacy, indexing behaviour, and Windows setup.

In the website, select **Review AI indexing plan**. Review its video list, removals and estimated
cost before approving **Prepare AI search**. Search preparation sends video to Google; local
upload and frame extraction do not. The estimate is not a billing cap. Scores are ranking
signals, not calibrated probabilities, and every result requires human review. Real authorised
CCTV validation is still pending.

The existing CLI-generated HTML review pages use local file links and should be opened
directly from disk. The new dashboard serves its own media URLs with video byte-range support.

### Check visual evidence after search

**Experimental; representative CCTV accuracy is not established.** Provider/model compatibility
errors have been corrected. The default multi-frame website checks distinguish visible black
outer clothing from an unseen shirt in the existing short sample collection. These are limited
workflow checks, not general CCTV accuracy measurements.
See [current handoff](docs/continue-work.md) for results and limitations.

The website defaults to **Search & check matches**. This first retrieves ranked windows, then
uses Gemini 3.8 Flash to review up to six extracted images from each of the first five windows.
For each search, tick the approval box to send those images and your query to Google. This
adds API usage and may incur charges; free-tier data use follows Google's applicable terms.
Changing the query or finishing a search resets approval. No visual request is sent without it.

- **AI-supported candidate:** sampled images support the visible description; still requires
  human review and keeps the underlying `uncertain` status.
- **Unclear:** an attribute is hidden/ambiguous, frames are unavailable, or a window is beyond
  the first five checked candidates. These remain available in a separate review section.
- **Not supported:** the sampled images do not support the description. These are separated
  from the candidate matches and can be inspected with the model's explanation.

Evidence buttons open the video at a sampled timestamp. A black hoodie/jacket is not silently
treated as evidence of a black shirt hidden underneath. If no candidate is supported, the page
says no visually supported match was found **in the samples**, not that the event is absent.
Checker failures return an error instead of silently displaying rankings as checked matches.

Uncheck image checking for **Search ranked clips** (the original behaviour, also retained by
the CLI). Rankings alone can include unrelated footage. This feature is a sampled-image
review aid, not a trained clothing detector, continuous video analysis, or a bounding-box
tracker. Model errors and missed events remain possible. The separate search environment
already provides `google-genai`; no extra backend dependency is required.

The model can be set with `TANYA_VERIFY_MODEL` (default `gemini-3.8-flash`). The default was
checked for API availability; other models need separate compatibility and cost validation.

## Project layout

```
TanyaCCTV/
├── backend/
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── tanya/                  # indexing/search package plus Flask dashboard
│   │   ├── config.py           # settings from env vars / .env, validation
│   │   ├── db.py               # SQLite schema
│   │   ├── frames.py           # OpenCV frame extraction
│   │   ├── indexer.py          # repeatable indexing logic
│   │   ├── sentry_client.py    # runs the search bridge as a subprocess, checks its JSON
│   │   ├── search.py           # maps results to videos, merges chunks, thumbnails
│   │   ├── search_sync.py      # opt-in sync of the search index (plan, then apply)
│   │   ├── report.py           # HTML review page for search results
│   │   ├── web.py              # local Flask website and API
│   │   ├── templates/          # dashboard HTML
│   │   └── static/             # dashboard CSS and JavaScript
│   ├── scripts/
│   │   ├── run_web.py          # local website at http://localhost:5001
│   │   ├── index_videos.py     # run the indexer
│   │   ├── show_index.py       # read-only view of the database
│   │   ├── make_test_video.py  # create a synthetic test video
│   │   ├── search_videos.py    # natural-language search
│   │   └── sync_search_index.py # update the search index (dry run unless --yes)
│   └── tests/                  # pytest, synthetic videos + fake search bridge
├── search_engine/
│   ├── tanya_bridge.py         # runs INSIDE the SentrySearch env; prints one JSON line
│   └── tests/                  # bridge tests (run with the SentrySearch env)
├── data/
│   ├── videos/                 # put authorised sample footage here (git-ignored)
│   ├── frames/                 # generated JPEG frames (git-ignored)
│   └── tanya.db                # generated database (git-ignored)
├── .env.example
└── .gitignore
```

## How indexing works

1. Every supported file (`.mp4 .avi .mov .mkv .m4v`) under `data/videos/` is hashed (SHA-256).
   Hidden files are ignored; other file types are reported as unsupported; anything resolving
   outside the video folder (e.g. a symlink) is refused.
2. A video is **skipped** if the same content was already indexed successfully with the same
   frame interval and its frames are still on disk. Otherwise it is (re)processed:
   - **new video**, **`--force`**, **changed interval**, **previous failure** or
     **interrupted run** → re-extract.
   - **renamed video** → same hash, so only the stored path is updated (no re-extraction).
   - **modified video** (same name, new content) → indexed as new; old index data removed.
   - **deleted video** → its database rows and extracted frames are removed.
3. Frames are written to `data/frames/.tmp/` first and moved to `data/frames/<sha256>/` only
   after extraction succeeds; the frame rows are then written in one database transaction.
   A crash or Ctrl+C leaves the video marked `processing`, and the next run redoes it.
4. Corrupt, empty or unreadable videos are marked `failed` with the reason and the run continues.

**Original video files are never modified, moved or deleted.** Only generated data
(`data/frames/`, `data/tanya.db`) is ever cleaned up.

## Setup (Windows PowerShell, VS Code)

Open the `TanyaCCTV` folder in VS Code, then open a terminal (**Terminal → New Terminal**,
make sure it is PowerShell). Run every command from the project root.

### 1. Create and activate a virtual environment

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`. If activation is blocked with
*"running scripts is disabled on this system"*, allow scripts for this terminal only and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

In VS Code, also pick the interpreter: **Ctrl+Shift+P → Python: Select Interpreter →
`.venv\Scripts\python.exe`**.

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
python -c "import cv2, dotenv; print('OpenCV', cv2.__version__)"
```

Verified on Python **3.14.5** (opencv-python-headless 5.0.0, numpy 2.5.4, pytest 9.1.1).
FFmpeg does **not** need to be installed: OpenCV's wheel bundles its own decoders.

### 3. Run the automated tests

```powershell
python -m pytest backend -v
```

Expected: all tests pass. One symlink test is skipped on Windows unless Developer Mode
is enabled (creating symlinks needs that permission). Tests use temporary folders and
synthetic videos; they never touch `data/`.

### 4. Add sample videos

Copy **authorised footage only** (your own recordings, footage with written permission, or
openly licensed sample clips) into `data\videos\` (subfolders are fine):

```powershell
Copy-Item "C:\path\to\your\sample_clip.mp4" data\videos\
```

No footage yet? Generate synthetic test videos:

```powershell
python backend\scripts\make_test_video.py data\videos\synthetic_cam1.mp4 --seconds 10
python backend\scripts\make_test_video.py data\videos\synthetic_cam2.avi --seconds 6 --seed 2
```

### 5. Run the indexer

```powershell
python backend\scripts\index_videos.py
```

It prints one line per video and a summary of **Indexed / Skipped / Failed / Ignored /
Removed**. Exit code: `0` = OK, `1` = at least one video failed, `2` = configuration error.
Run it again: everything should now be **Skipped**.

### 6. `--interval` and `--force`

```powershell
# one frame every 1.5 s (allowed: 1.0 to 2.0; default 1.0)
python backend\scripts\index_videos.py --interval 1.5

# re-extract everything, even if already indexed
python backend\scripts\index_videos.py --force

# both
python backend\scripts\index_videos.py --force --interval 2
```

Changing the interval automatically re-indexes affected videos (no `--force` needed).
To make a different interval the default, copy `.env.example` to `.env` and set
`TANYA_FRAME_INTERVAL_SEC`:

```powershell
Copy-Item .env.example .env
```

### 7. Verify the results in SQLite

Read-only summary of all videos (status, frame count, interval, duration, fps, resolution):

```powershell
python backend\scripts\show_index.py
```

Frames and timestamps of one video (use an `id` from the list above); `[ok]` means the
JPEG exists on disk:

```powershell
python backend\scripts\show_index.py --frames 1
```

Run your own SQL with Python (no extra tools needed):

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/tanya.db'); [print(tuple(r)) for r in c.execute('SELECT id, rel_path, status, frame_count, frame_interval_sec, duration_sec FROM videos')]"
python -c "import sqlite3; c=sqlite3.connect('data/tanya.db'); [print(tuple(r)) for r in c.execute('SELECT video_id, COUNT(*), MIN(timestamp_sec), MAX(timestamp_sec) FROM frames GROUP BY video_id')]"
```

Look at the frames themselves:

```powershell
explorer data\frames
```

A 10-second video at a 1-second interval should give 10 frames with timestamps
0, 1, 2, … 9; with `--interval 2` it gives 5 frames (0, 2, 4, 6, 8).

Manual checks worth trying:

| Action | Expected on next run |
|---|---|
| Run twice | second run: all **Skipped**, same row counts |
| Rename a video | **Skipped**, message "renamed from …", path updated |
| Replace a video with different content (same name) | **Indexed**, old entry listed under **Removed** |
| Delete a video | listed under **Removed**; its frames folder disappears |
| Add a `.txt` file / a corrupt `.mp4` | **Ignored** / **Failed**, other videos still indexed |
| Press Ctrl+C during indexing, then run again | interrupted video is redone cleanly |

### Starting over

Generated data can always be rebuilt from your videos:

```powershell
Remove-Item data\tanya.db
Get-ChildItem data\frames -Exclude .gitkeep | Remove-Item -Recurse -Force
```

## Configuration

All optional, via environment variables or a `.env` file in the project root
(see `.env.example`). Relative paths are resolved from the project root.

| Variable | Default | Meaning |
|---|---|---|
| `TANYA_VIDEO_DIR` | `data/videos` | folder scanned for videos |
| `TANYA_FRAMES_DIR` | `data/frames` | where JPEG frames are stored (must not be inside the video folder) |
| `TANYA_DB_PATH` | `data/tanya.db` | SQLite database |
| `TANYA_FRAME_INTERVAL_SEC` | `1.0` | seconds between frames, 1.0–2.0 |
| `TANYA_JPEG_QUALITY` | `90` | JPEG quality, 1–100 |

No secrets are needed for this milestone. `.env` is git-ignored; never commit secrets.

> ⚠️ If `TANYA_VIDEO_DIR` points to the wrong (but existing) folder, the indexer treats the
> previously indexed videos as deleted and removes their *generated* index data. Your video
> files are unaffected; point it back and re-run to rebuild.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again |
| `ModuleNotFoundError: No module named 'cv2'` / `'dotenv'` | venv not active or deps not installed: activate `.venv`, then `python -m pip install -r backend\requirements.txt` |
| `pip install` fails building numpy/opencv on a newer Python | see **Using Python 3.12** below |
| `Configuration error: Video directory does not exist` | create `data\videos` or fix `TANYA_VIDEO_DIR` |
| `Configuration error: Frame interval must be between 1.0 and 2.0` | use a value from 1.0 to 2.0 |
| A video shows **Failed: OpenCV could not open the file** | file is corrupt, still downloading/copying, or uses an unusual codec. Try re-exporting it as H.264 `.mp4` |
| Lines like `moov atom not found` appear | harmless FFmpeg messages printed for corrupt files; the summary has the real result |
| `PermissionError` / `[WinError 5]` / `[WinError 32]` on frames | another program (often **OneDrive** sync, antivirus or Explorer preview) is holding the files. Re-run the indexer (failed videos are retried). Because this project is in a OneDrive folder, consider pausing OneDrive while indexing or setting `TANYA_FRAMES_DIR` to a folder outside OneDrive |
| `database is locked` | close DB Browser / other scripts using `data\tanya.db`, and don't run two indexers at once |

### Using Python 3.12 (only if dependencies fail on your Python)

Everything was verified on Python 3.14.5, so this should not be needed. If installation
fails on a future Python, install Python 3.12 from python.org (keep your current Python;
the `py` launcher lets both coexist), then recreate the venv with it:

```powershell
py -0                                   # list installed Python versions
Remove-Item -Recurse -Force .venv       # deletes only the virtual environment
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

## Natural-language search (Milestone 2)

Search finds **10-second clips** that match a description such as "a person lying on the floor".
It is optional: indexing and everything above work without it.

> **Every result is `uncertain`.** Results are a ranked list of clips for a person to review,
> not detected incidents. Scores are not comparable between queries, and **a low score does not
> prove that something did not happen.** In testing, a correct "red car" clip scored 0.36 while an
> irrelevant "fire and smoke" clip scored 0.34, so there is deliberately no score cutoff.

### How it fits together

```
search_videos.py ─► tanya/search.py ─► tanya/sentry_client.py ──subprocess──► search_engine/tanya_bridge.py
   (Python 3.14, this .venv)          (JSON only, timeout, key redaction)     (SentrySearch env, Python 3.12)
```

- SentrySearch splits each video into 10 s chunks (2 s overlap), embeds them with Gemini, and
  stores them in its own index at `%USERPROFILE%\.sentrysearch\db`. That index is shared by
  everything that uses SentrySearch on this computer.
- Results are mapped back to TanyaCCTV videos. Only files inside `data/videos` that
  `index_videos.py` has indexed count.
- Neighbouring matching chunks are grouped into one time window, and the nearest extracted
  frame is attached as a thumbnail.
- SentrySearch indexes **only `.mp4` and `.mov`**. Other formats are listed as "not searchable".

### Cost and privacy

- Indexing uses the Gemini API: about **US$0.00079 per second of video** on the paid tier
  (about US$2.84 per hour; Google pricing checked 2026-10-16). Searching costs a negligible amount.
- The free tier costs nothing, but **Google may use free-tier content to improve its products**.
  Only index footage whose licence or consent allows sending it to Google.
- Search and indexing need internet access.

### One-time setup (outside this project)

1. Install [uv](https://docs.astral.sh/uv/), then install SentrySearch pinned to one commit, in
   its own folder:

   ```powershell
   $T = "$HOME\sentrysearch-trial"
   $env:UV_PYTHON_INSTALL_DIR = "$T\python"; $env:UV_TOOL_DIR = "$T\tools"; $env:UV_TOOL_BIN_DIR = "$T\tool-bin"
   $env:UV_CACHE_DIR = "$T\cache"; $env:UV_PYTHON_BIN_DIR = "$T\python-bin"; $env:UV_PYTHON_PREFERENCE = "only-managed"
   uv python install 3.12
   uv tool install --python 3.12 "git+https://github.com/ssrajadh/sentrysearch@d3efd6a4351251084dc101a24970e40a38e1426d"
   ```

2. Point TanyaCCTV at that environment, either in your terminal or in your own git-ignored `.env`:

   ```powershell
   $env:TANYA_SENTRY_PYTHON = "$HOME\sentrysearch-trial\tools\sentrysearch\Scripts\python.exe"
   ```

3. Provide your Gemini API key **only** through the environment. Never put it in code,
   `.env.example`, logs or Git. This sets it for the current terminal only, with typing hidden:

   ```powershell
   $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host 'Gemini API key' -AsSecureString)))
   ```

### Index videos for search (opt-in, costs money)

Run `index_videos.py` first. Then review the plan. This step is free and changes nothing:

```powershell
python backend\scripts\sync_search_index.py
```

The plan lists:

- videos to index
- index entries to remove (deleted, renamed or changed videos)
- estimated frames and estimated cost

Entries outside `data/videos`, such as other projects in the shared index, are never touched.

To apply the plan:

```powershell
python backend\scripts\sync_search_index.py --yes
```

- Removals use exact path matching only. Don't use `sentrysearch remove`: it matches substrings
  and could delete unrelated entries.
- The script records what it indexed in `data/search_index_manifest.json` (git-ignored).
- Searching never indexes or removes anything.

### Search

```powershell
python backend\scripts\search_videos.py "a person lying on the floor"
python backend\scripts\search_videos.py "a red car" --n 20 --json
python backend\scripts\search_videos.py "a red car" --html data\search_results.html --open
```

`--html FILE` (must end in `.html` or `.htm`) writes a self-contained **review page**, and `--open` opens it in your browser. The
page has an "unverified, human review required" banner, and for each result:

- the matched clip in a video player that starts at the matched time
- the thumbnail, with a link to the extracted frame
- the time window and scores

If a search fails, the page shows the error instead. Pages under `data\` are git-ignored.
Clips play in the browser only if the video codec is supported (H.264 MP4 is; OpenCV's `mp4v`
test videos are not). Otherwise, use the "open video file" link.

Each result shows:

- the video and the time window
- the best chunk's score, and its margin over the query's median score (for ordering only)
- the individual chunks
- a thumbnail path

Warnings explain:

- results that were ignored (outside `data/videos`, or not indexed by TanyaCCTV)
- videos that aren't searchable
- timestamps that may be stale (run the sync plan to review)

`TANYA_MERGE_RATIO` (default 0.5) and `TANYA_MERGE_GAP_SEC` (default 0) only control how chunks
are grouped into windows. They never change a result's status. See `.env.example`.

### Testing search

- **Main tests:** `python -m pytest backend -v` includes the search tests. They use a **fake
  bridge** that replays real recorded scores, so no SentrySearch, network or API key is needed.
- **End-to-end test without a key:** with `$env:TANYA_SENTRY_PYTHON` set (step 2), the same
  command also runs `test_e2e_real_bridge.py`. It goes through the real SentrySearch environment,
  bridge and index, replacing only Gemini's query embedding with a stored chunk vector (via the
  test-only `search_engine/tests/e2e_shim_bridge.py`). It needs the synthetic trial index and
  is skipped otherwise.
- **Bridge tests:** run these with the SentrySearch environment. The live tests run only if
  `GEMINI_API_KEY` is set.

  ```powershell
  $env:TANYA_SENTRY_PYTHON = "$HOME\sentrysearch-trial\tools\sentrysearch\Scripts\python.exe"
  cd search_engine\tests
  & "$HOME\sentrysearch-trial\src\.venv\Scripts\python.exe" -m pytest -v
  ```

  `src\.venv` is a checkout of SentrySearch at the same commit, with pytest installed. To create it:
  `git clone https://github.com/ssrajadh/sentrysearch src; cd src; git checkout d3efd6a; uv sync --python 3.12 --group test`

### Search troubleshooting

| Problem | Fix |
|---|---|
| `Configuration error: Search is not configured` | Set `TANYA_SENTRY_PYTHON` (step 2 above). |
| `GeminiAPIKeyError: GEMINI_API_KEY is not set` | Set the key in **this** terminal (step 3). Claude Desktop and other apps can't see variables set in a different window. |
| Every result is ignored as "outside the video folder" | The shared SentrySearch index only holds other footage. Run the sync plan. |
| "Timestamps may be stale" warning | Review `sync_search_index.py` (dry run), then apply it with `--yes` if the plan is right. |
| `search engine timed out` | Check your internet connection, or raise `TANYA_SEARCH_TIMEOUT_SEC`. |
| Clip on the review page is black or doesn't play | The video isn't H.264. Use "open video file" or re-encode it to H.264 MP4. |
| "is in the database but the video file is missing" | The video was deleted or moved. Run `index_videos.py`, then the sync plan. |
| "Timestamps may be stale" on footage you indexed by hand | Expected: the video wasn't indexed through `sync_search_index.py`, so its content can't be verified. Run the sync plan. |

## Hackathon demo (command line)

The command-line demo below remains available alongside the local website. Allow about
5 minutes.

**Before the demo (once, needs internet and your key):**

1. Put 2–4 short **authorised** clips in `data\videos\`, as H.264 MP4 so they play in the browser.
2. Run the free local indexer: `python backend\scripts\index_videos.py`
3. Review the search-index plan (free, changes nothing):
   `python backend\scripts\sync_search_index.py`
4. Apply it. This costs about US$0.00079 per second of video on the paid tier:
   `python backend\scripts\sync_search_index.py --yes`

**During the demo:**

```powershell
.\.venv\Scripts\Activate.ps1
$env:TANYA_SENTRY_PYTHON = "$HOME\sentrysearch-trial\tools\sentrysearch\Scripts\python.exe"
# GEMINI_API_KEY must already be set in this window (see step 3 of the one-time setup)
python backend\scripts\show_index.py
python backend\scripts\search_videos.py "a person lying on the floor" --html data\demo_lying.html --open
python backend\scripts\search_videos.py "a red car" --html data\demo_car.html --open
python backend\scripts\search_videos.py "fire and smoke" --html data\demo_fire.html --open
```

Talking points:

- Results are **ranked clips for a human to check**, not alarms.
- "fire and smoke" still returns clips. That shows why there is no automatic incident
  confirmation: scores rank results, they don't prove anything.

**Fallback if the network fails:** keep `data\demo*.html` pages from a rehearsal. They're static
files and open without internet (the videos are local).

## Search quality: what has been verified

| Check | Footage | Result |
|---|---|---|
| Ranking, real Gemini (bridge live tests, 2026-10-17) | synthetic lobby/car-park clips | top 3 chunks inside the event for walking, lying and red car; "fire and smoke" only weak matches; all `uncertain` |
| TanyaCCTV CLI end to end with real Gemini (`search_videos.py`, 2026-10-17) | same | 4/4 ground-truth checks passed. Top windows: walking 16–42 s, lying 40–60 s, red car 16–40 s (events 20–40, 40–60, 20–40). "fire and smoke" got weak matches only. All `uncertain`, all with thumbnails. |
| End-to-end through the real bridge and index, no key | same | correct video IDs, windows inside videos, thumbnails, read-only |
| Uploaded-clip spot checks, real Gemini (2026-10-18) | short boat and room clips, plus synthetic controls | 6/6 positive queries ranked the expected video first; hand-raising window overlapped the observed later action. Negative query still returned uncertain rankings. See [validation report](docs/search-validation.md). |
| **Representative real-world CCTV footage** | **not established by the short uploaded samples** | **not validated broadly**; see limitations |

## Known limitations

- **Not broadly validated on representative CCTV footage.** Quality checks cover synthetic
  scenes and two short uploaded clips. Lighting, camera angle, resolution and crowded scenes
  may rank very differently. The uploaded-clip checks are not an accuracy benchmark.
- **No automatic incident detection.** Every result is `uncertain`. In testing, an irrelevant
  "fire and smoke" clip (0.34) scored close to a correct "red car" clip (0.36), so no score cutoff
  is safe.
- **Timestamps are 10 s chunks** (2 s overlap). Merged windows can include a few seconds without
  the event.
- The merge ratio (0.5) was tuned on 4 synthetic queries. It affects grouping only.
- SentrySearch indexes only `.mp4` and `.mov`, identifies videos by path (a rename means
  re-indexing, which costs money), and keeps one index per Windows user, shared with other uses.
- Search and indexing need internet and a Gemini key. On the free tier, Google may use the content.
- The local Flask website/API is a development prototype, without accounts or production hosting.
- In the browser, clips play only for browser-supported codecs (H.264).

## Footage policy

Use authorised sample footage only. Do not commit videos, extracted frames or databases:
they are excluded by `.gitignore`.
