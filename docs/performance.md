# Performance measurements

Measured on 18 October 2026, on a Windows 11 laptop:

- AMD Ryzen 7 4800H (8 cores / 16 threads), 23.4 GB RAM
- Python 3.14.5, OpenCV 5.0.0
- an isolated workspace, with no Google calls

These are single-machine measurements on synthetic footage. Real CCTV (1080p, H.264, busy
scenes) decodes more slowly, so measure your own footage before relying on these numbers.

## Local indexing (frame extraction)

One JPEG per second, using the Milestone 1 indexer. Times are from one or two runs, so treat them as rough.

| Footage | Duration | Time | Frames | Frames on disk | Peak memory (process) |
|---|---|---|---|---|---|
| 2 demo clips, 640×360 H.264 | 100 s | 0.4 s | 100 | 1.7 MB | 89 MB |
| 1 synthetic recording, 640×360 mp4v | 10 min | 1.6–1.9 s | 600 | 8.8 MB | 70 MB |

How to read this:

- Python with the project imports already peaks at 39 MB.
- **Memory does not grow with recording length.** Frames are read and written one at a time.
- The 10-minute clip peaked lower than the 100 s clips: peak memory depends on the decoder,
  not on duration.
- Disk use is about 15 KB per extracted frame here, so an hour is about 3,600 frames. Expect
  more for detailed real scenes.

## Search

| Operation | Median | Range |
|---|---|---|
| Bridge subprocess: start Python 3.12, load the Chroma index (13 chunks), rank, return JSON | 2.25 s | 1.94–2.65 s (5 runs) |

This excludes the Gemini text-embedding request, which adds network time and depends on the
connection. Each search starts a fresh subprocess, so most of the time is interpreter and
library start-up. That's acceptable for a demo; a long-running search process would cut it,
but hasn't been needed.

## Dashboard API (10-minute recording, 600 frames)

| Request | Median of 5 |
|---|---|
| `GET /api/videos` | 2.5 ms |
| `GET /api/videos/<id>/frames?page=3` (60 frames) | 3.5 ms |
| One frame JPEG | 7.0 ms |

## Investigations and reports (19 October 2026)

An investigation with 50 clips from the two demo recordings, using an in-process test client.
Median of 5 runs.

| Operation | Time |
|---|---|
| Add one clip (validation, server-side source lookup, audit entry) | 19 ms (mean of 50) |
| Open the investigation (sources resolved, timeline ordered) | 14 ms |
| Export JSON report (sources re-hashed) | 47 ms |
| Export HTML report (with 50 embedded frames) | 68 ms, 1.2 MB (about 24 KB per clip) |
| SHA-256 throughput on this laptop | about 1,000 MB/s |

Export re-hashes each source video once to verify it. At about 1 GB/s, a 2 GB recording adds
about 2 seconds to an export. Reports embed one frame per clip, so a 500-clip report would be
roughly 12 MB.

## Known limits

- **Indexing and AI preparation run inside the web request.** The page shows a progress message
  and disables other actions until they finish. Very long recordings will keep the browser
  waiting, and closing the tab doesn't cancel the work.
- **Uploads** are limited to 512 MB per file and streamed to disk.
- **One operation at a time.** Upload, indexing, search and preparation share one lock, so a
  second request gets a clear "try again" message.
