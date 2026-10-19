# Public real-camera research set — acquired 19 October 2026

Source: [University of Edinburgh CAVIAR](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/).
The publisher states Creative Commons BY-SA and requests attribution to the EC Funded CAVIAR
project/IST 2001 37540. The page does not specify a licence version; none is assumed here.
These are **staged real-camera recordings of people**, not the cartoon synthetic clips.
They are a research test input, not evidence of real incidents or a deployment benchmark.

## Acquired locally

Five original MPEG clips and matching publisher XML labels, about **38 MB** total download.
Source/annotation hashes and download URLs are pinned in `evaluation/datasets/caviar-small.json`.
No videos, labels, frames or local databases are committed to Git.

| Review copy | Duration | Decoded frames | Publisher label frames |
|---|---:|---:|---:|
| Walk1.mp4 | 24.48 s | 612 | 611 |
| Browse2.mp4 | 35.04 s | 876 | 875 |
| Rest_FallOnFloor.mp4 | 40.32 s | 1008 | 1007 |
| EnterExitCrossingPaths1cor.mp4 | 15.32 s | 383 | 383 |
| EnterExitCrossingPaths1front.mp4 | 15.32 s | 383 | 383 |

Total MP4 duration: **130.48 seconds**. Copies are H.264, 384×288, normalized to 25 fps in decoded
frame order. They cover walking, browsing/standing, a staged fall, and entry/exit views.
The two sites and camera views provide some variation; nighttime, outdoor weather, vehicle
scenes and modern high-resolution conditions are not covered by this subset.

## Local data and provenance

Everything is under ignored `data/cctv_validation/caviar/`:

- `originals/`: unchanged publisher MPEG files
- `annotations/`: unchanged publisher XML
- `videos/`: normalized MP4 review copies
- `frames/`, `videos.db`: separate local index, not the owner's four-video library
- `download-manifest.json`, `media-manifest.json`: local hashes and measured metadata
- `videos-source-pts/`: first conversion attempt retained locally for diagnosis; not evaluation input

The old MPEG header durations were misleading, especially for the two shop-camera clips.
Full decoding established their true frame counts. Review copies reset timestamps to frame
index / 25 without changing decoded-frame order or overwriting the source files. First-set XML
labels omit one trailing decoded frame, so do not assume every frame is annotated. Frame-label
alignment and exact event intervals still need visual confirmation before an AI accuracy run.
The viewer's "Download original" means its imported MP4 review recording; the actual publisher
original is the separate MPEG in `originals/`. Reports reference the MP4 content hash.

## Reproduce

From a configured checkout:

```bash
.venv/sentry/bin/python backend/scripts/download_caviar.py --download
.venv/bin/python backend/scripts/download_caviar.py --prepare
.venv/bin/python backend/scripts/download_caviar.py --serve
```

Windows: replace the interpreter paths with `.\.venv\sentry\Scripts\python.exe` and
`.\.venv\Scripts\python.exe`. The search environment supplies a trusted CA bundle on this Mac;
TLS verification was kept enabled. Local FFmpeg is discovered from PATH or `.venv/sentry`.
Without flags the script only prints a plan. `--prepare` and `--serve` perform no downloads.
Existing publisher files are hash-checked and never overwritten; size limits and partial-file
cleanup apply. Stop another website before `--serve` (same port 5001).

Open **http://localhost:5001/#library**. This viewer blocks all AI/search endpoints server-side,
even with a key in the environment. It shows licence/provenance context. A browser check loaded
the front-view clip (15.32 s, media ready, no player error) and sought to 8 s. Original files,
source hashes, local indexing and supplied XML parsing were checked. No Google calls were made.

## Next, not completed

1. Watch the clips and verify frame-label alignment. Derive query/event start/end labels in a
   separate private/local ground-truth file; do not infer event times from filenames alone.
2. Define positive/negative queries and stricter timing acceptance before measuring.
3. Present the exact real-camera video/frame/query upload and cost plan for approval. Public
   download permission does not mean the user has approved Google processing.
4. Then measure retrieval/image review and timing, including misses and irrelevant matches.
5. Obtain broader independently labelled recordings for lighting/weather/vehicle coverage.

The acquisition step is complete. Real-camera AI accuracy has **not** been tested yet.
