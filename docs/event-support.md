# Which events can TanyaCCTV search for?

Status as of 19 October 2026. **"Measured"** means real Gemini search results were scored against
known event times. It does **not** mean the event is detected reliably: every measurement here
uses one query on simple cartoon footage. Real CCTV has not been validated for any event type.

| Event type | Example query | Status | Evidence |
|---|---|---|---|
| Person moving | "a person walking" | **Measured (synthetic, 1 query)** | Right clip first; merged window 16–42 s for an event at 20–40 s (IoU 0.77) |
| Person lying down | "a person lying on the floor" | **Measured (synthetic, 1 query)** | Right clip first; window 40–60 s exactly (IoU 1.0) |
| Vehicle present | "a red car" | **Measured (synthetic, 1 query)** | Right clip first; window 16–40 s for 20–40 s (IoU 0.83) |
| Entering | "a person entering through a door" | Defined, **unmeasured** | Clip and ground truth ready (`cam3_entrance.mp4`, 10–20 s) |
| Leaving | "a person leaving through a door" | Defined, **unmeasured** | `cam3_entrance.mp4`, 45–55 s |
| Loitering | "a person standing still for a long time" | Defined, **unmeasured** | `cam3_entrance.mp4`, 20–45 s |
| Fall | "a person falling down" | Defined, **unmeasured** | `cam5_corridor.mp4`, 20–23 s (shorter than one 10 s chunk) |
| Vehicle arriving / parked / leaving | "a car arriving and parking", "a parked car", "a car driving away" | Defined, **unmeasured** | `cam4_driveway.mp4`, 10–20 / 20–35 / 35–45 s |
| Any vehicle | "a car" | Defined, **unmeasured** | `cam2_carpark.mp4` 20–40 s and `cam4_driveway.mp4` 10–45 s |
| Negative queries | "fire and smoke" | **Measured (1 query)** | Always returns the nearest clips (the person and car scenes); never evidence of absence |
| Other negatives | "a dog running", "a bicycle", "a crowd of people", "a person riding a motorcycle" | Defined, **unmeasured** | No matching content in any clip |
| Identity / same person across cameras | — | **Not supported, by design** | No re-identification; reports never claim two clips show the same person |
| Counting, licence plates, faces, audio | — | **Not supported** | Not part of the search engine |

## What the measured results show

From the error analysis in `evaluate_search.py`:

- **Confusion between neighbouring events in the same scene.** For "a person walking", the 3rd
  window was the lobby at 40–50 s, where the person is lying. For "lying", a walking window ranked
  3rd. Same camera and background, adjacent moments.
- **Background windows rank in the top results** (an empty car park was 2nd for "a red car").
  Search always returns its nearest clips, which is why every result needs review.
- **The negative query returned whatever scenes have something in them** (a person, the car).
  Ranking scores alone can't tell a weak match from an absent event.

## Expected difficulties (hypotheses to test, not results)

- **Falls last about 3 seconds**, much shorter than the 10 s search chunks, so the window will be
  coarse and the fall may be diluted by the walking before and the lying after it.
- **Entering vs leaving** differ only in direction. A single chunk embedding may not distinguish them.
- **Loitering and parked vehicles** are mostly static, so they may look similar to the empty scene.

These are reasons to measure, not conclusions. No ranking or threshold change has been made for them.

## How to measure the unmeasured event types (needs approval)

Proposed operation (**not run**):

1. Generate the event clips locally (free):
   `python backend/scripts/make_demo_footage.py --set events --out <folder in data\videos>`
2. Index them locally (free), then prepare them for AI search through the dashboard plan. This
   sends **3 synthetic clips, 150 s of cartoon video, about 182 billed frames** to Google:
   **about US$0.14** on the paid tier (an estimate, not a cap). The clips contain no real people.
3. Run the 16 annotated queries live (query text only, no footage):
   ```
   python backend/scripts/evaluate_search.py --ground-truth evaluation/synthetic_events_v2.json --live --approve-api-calls --save evaluation/recordings/<date>-events.json
   ```
   That costs about US$0.00004.
4. Re-score offline (free), and add `"indexed_videos"` to the saved recording listing all five clips.

Total: about **US$0.15**. Results would still be synthetic. Real CCTV validation stays a separate,
pending step (see `cctv-accuracy-checklist.md`).
