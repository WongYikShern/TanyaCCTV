# TanyaCCTV

AI-powered CCTV search and incident-response prototype (university hackathon).

**Milestone 1 — video ingestion and indexing.** The indexer scans a folder of authorised
sample videos, extracts one JPEG every 1–2 seconds, and stores video metadata and frame
timestamps in SQLite.

**Milestone 2 — natural-language search** (command line, optional). Uses
[SentrySearch](https://github.com/ssrajadh/sentrysearch) (Apache-2.0, pinned to commit `d3efd6a`)
with Google's Gemini Embedding 2, in a separate Python 3.12 environment. See
[Natural-language search](#natural-language-search-milestone-2).

Flask API, React frontend, Telegram alerts and monitoring rules come in later milestones.

## Project layout

```
TanyaCCTV/
├── backend/
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── tanya/                  # plain Python package (no Flask)
│   │   ├── config.py           # settings from env vars / .env, validation
│   │   ├── db.py               # SQLite schema
│   │   ├── frames.py           # OpenCV frame extraction
│   │   ├── indexer.py          # repeatable indexing logic
│   │   ├── sentry_client.py    # runs the search bridge as a subprocess, checks its JSON
│   │   ├── search.py           # maps results to videos, merges chunks, thumbnails
│   │   └── search_sync.py      # opt-in sync of the search index (plan, then apply)
│   ├── scripts/
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
```

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

## Footage policy

Use authorised sample footage only. Do not commit videos, extracted frames or databases:
they are excluded by `.gitignore`.
