# Real-camera footage acquisition handoff — 19 October 2026

The initial varied-footage collection is complete: **11 licensed real-camera clips** are
available locally, including staged indoor human actions and naturally occurring outdoor
traffic. Total duration is **1,930.18 seconds (32 minutes 10.18 seconds)**. This completes
acquisition of a bounded starting collection, not accuracy evaluation or exhaustive coverage.
No real-camera clips, images or queries have been sent to Google. No paid calls were made.

## Sources and permission

- **CAVIAR:** five staged recordings and publisher XML labels, 130.48 seconds.
  [Publisher](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/) states CC BY-SA, with no version
  specified. Attribute EC Funded CAVIAR project/IST 2001 37540. See `caviar-research-set.md`.
- **AAU RainSnow:** six RGB traffic recordings, 1,799.70 seconds. Publisher's
  [Kaggle dataset](https://www.kaggle.com/datasets/aalborguniversity/aau-rainsnow) and public
  metadata API identify **CC BY 4.0**, dataset version 1. The [Aalborg University record](https://vbn.aau.dk/en/datasets/aau-rainsnow-traffic-surveillance-dataset/)
  establishes the original creators/source. Attribute Chris Holmberg Bahnsen and Thomas B.
  Moeslund, *AAU RainSnow Traffic Surveillance Dataset*, Aalborg University, 2018,
  doi:10.34740/kaggle/dsv/105294. Cite their *Rain Removal in Traffic Surveillance: Does it
  Matter?*, IEEE TITS 20(8), 2802–2819, 2019, doi:10.1109/TITS.2018.2872502.

Use is based on the publishers' public licences. This does not establish consent for private
premises, unrestricted personal-data processing, or approval to send these files to Google.
Keep attribution with review copies; apply each source licence if redistributing adapted media.
Videos and derived frames/indexes remain ignored by Git. No footage is in PR #5.

## Coverage actually obtained

| RainSnow RGB recording | Lighting observed in a 30-second local sample | Publisher weather (Table X) | Source frames / duration |
|---|---|---|---|
| Egensevej-1 | Dark, strong glare and lens droplets | Light rain, 18:00 | 5,998 / 299.90 s |
| Egensevej-5 | Night, headlights and wet road | Rain, 03:00 | 5,998 / 299.90 s |
| Egensevej-4 | Dark, visible falling snow and snowy ground | Snow, 18:00 | 5,998 / 299.90 s |
| Hadsundvej-2 | Daylight, wet intersection and parked cars | Rain, light thunderstorm, 15:23 | 6,000 / 300.00 s |
| Hjorringvej-3 | Dark, bright streetlights and reflections | Rain, 19:12 | 6,000 / 300.00 s |
| Hasserisvej-1 | Daylight, wet road and roadside vegetation | Rain, 13:12 | 6,000 / 300.00 s |

Weather/time metadata comes from the publisher paper's Table X; weather-station estimates
are not exact per-frame weather labels. Lightning was not verified. Times alone are not
used to assert twilight: the sampled evening scenes are dark. This subset has day/night
variation; a distinct twilight class has not been established.

Four outdoor intersection views complement CAVIAR's corridor/front views and staged walking,
browsing, entry/exit and fall. Local traffic samples show moving/turning vehicles, parked
vehicles, pedestrians, glare, wet roads and snow. These observations are acquisition checks,
not exhaustive event annotations. Exact action intervals and positive/negative queries are
left for the evaluation task. No natural fall, fire, violence or emergency is claimed.

## Local verification and provenance

`evaluation/datasets/rainsnow-small.json` pins every selected publisher path, download URL,
archive/video SHA256, decoded frame count, frame rate and duration. All six originals fully
decoded at **640×480, 20 fps**. Three Egensevej files contain 5,998 frames rather than an assumed
6,000, so their measured duration is 299.90 seconds. Full-source frame counts were used for
review-copy verification. The six ZIPs total **193,494,943 bytes** (193.5 MB); CAVIAR downloads
add about 38 MB. Raw videos are unchanged and retained separately from H.264 MP4 review copies.

Ignored folder `data/cctv_validation/rainsnow/` contains publisher ZIPs, `originals/`, `videos/`,
`frames/`, separate `videos.db`, publisher metadata and download/media manifests.
The six selected RGB videos are downloaded; thermal streams and sparse pixel annotations
were not collected in this step. CAVIAR XML labels are already available. RainSnow's original
annotations cover sampled frames and are not complete temporal event boundaries; do not
invent timing labels from them or from the table above.

Acquisition regression checks: 11 passed (CAVIAR/RainSnow). The full backend run had
319 passed, 6 skipped and one sandbox-blocked localhost-port test; that test passed when
rerun with socket access. No code fix was needed for that environment restriction.

## Reproduce on your friend's computer

From the configured feature branch, with FFmpeg available through PATH or the search environment:

```bash
.venv/sentry/bin/python backend/scripts/download_rainsnow.py --download
.venv/bin/python backend/scripts/download_rainsnow.py --prepare
.venv/bin/python backend/scripts/download_rainsnow.py --serve
```

Open **http://localhost:5001/#library** for RainSnow. Stop the current viewer before switching datasets. CAVIAR is available via
`download_caviar.py --serve` at **http://localhost:5001/#library**. Both viewers block every
`/api/search*` route, even with an API key configured. Reproduction does not require a Gemini key.
Without flags the RainSnow script prints a plan and performs no network operations.
`--prepare` and `--serve` are local only. Downloads are bounded, pinned by hashes, preserve
existing files, clean failed partial downloads and extract only the expected archive member.

Windows: replace Python paths with `.\.venv\sentry\Scripts\python.exe` and
`.\.venv\Scripts\python.exe`. Downloads use trusted TLS verification; no certificate bypass.
Files are excluded from Git, so your friend must run these commands to obtain their own copy.

## Remaining work for your friend

1. Review PR #5; use the current feature branch and `docs/teammate-handoff.md`.
2. Watch full clips, independently annotate events and exact boundaries, and select held-out
   positive/negative queries before evaluation. Sample viewing is not full manual labelling.
3. Request a separate, bounded Google upload/query/image/cost approval before live AI testing.
   Earlier synthetic-data approvals do not cover this collection.
4. Measure retrieval, image review and timing, record failures, then improve the system.
5. Expand footage only if the evaluation requires more lighting/camera/event categories.
   This initial collection is diverse but does not represent every CCTV setting.
