# Search validation — 18 October 2026

This is a small manual validation run, not a benchmark or a claim of incident-detection
accuracy. Six timestamps from each of two uploaded clips were visually inspected before
writing the queries. The collection also contained two versions of the synthetic square clip.
Existing video embeddings were reused; this run sent only text queries to Gemini.

Original footage, thumbnails, local paths, index files and credentials are excluded from this
report and from Git. The uploaded footage is not distributed with this repository.

| Query | Expected first video | Observed first window | Result |
|---|---|---|---|
| a small boat floating on a lake | boat clip | 0–5.88 s from engine | correct video |
| a white and orange boat moving on water | boat clip | 0–5.88 s from engine | correct video |
| a person wearing black standing inside a living room | room clip | 0–15.56 s | correct video |
| a masked person standing on a black and white tiled floor | room clip | 0–15.56 s | correct video |
| a person raising both hands inside a room | room clip, later part | 8–15.56 s | correct video and overlapping event window |
| a coloured square moving across a dark background | either synthetic clip | 0–10 s | correct video |
| fire and smoke with flames | no visible matching scene in sampled frames | synthetic clip ranked first | expected nearest-neighbour behaviour; not evidence of fire |

All six positive queries ranked the expected video first. All results, including those for the
negative query, retained `uncertain` status. Scores were not treated as probabilities or used
to set a detection threshold. The negative check does not exhaustively establish absence
between sampled frames.

## Issues found and fixed

- The engine rounded the 5.875-second boat clip's end to 5.88 seconds. Search mapping now clamps
  chunk ends to the indexed duration and ignores windows entirely beyond the recording.
  Regression tests cover both cases. The displayed/returned boat end after mapping is 5.875 s.
- Uploading/extracting frames was easy to mistake for preparing AI search. The dashboard now
  shows preparation state per video, lists uploads not covered by AI search, and refreshes
  coverage after indexing and sync. Coverage labels reflect the recorded content hash; the
  free indexing plan checks the actual shared search index.
- Search results now explicitly explain that nearest clips can appear even if the requested
  event is absent. Every clip still requires human review.

## Limits and next validation

The boat clip is about 5.9 seconds and the room clip about 15.6 seconds. Their provenance and
representativeness as deployed CCTV are not established by this run. The room clip has a
visible stock-footage watermark. Only the hand-raising query tested ordering between event
segments; broad scene queries can merge adjacent chunks into the entire room clip.

Ten-second chunks with overlap do not provide frame-accurate event boundaries. Validate next
with a larger authorised collection, independent event annotations, varied lighting/camera
angles, and separately reported retrieval and timing metrics. No automatic alarms or
confirmed-incident labels are justified by these checks.

## Experimental visual review follow-up

After explicit approval to send sampled images to Google, limited smoke tests checked two
retrieved windows with one frame each per query. Production defaults remain five windows and
six frames per window; that complete flow has not passed live validation.

- “people wearing black shirt”: both checked room windows were unclear. Visible zipped black
  outerwear does not establish a black shirt underneath.
- “person wearing black clothing”: the room sample at 0 seconds was supported; the checked
  synthetic square sample was not supported.
- “fire and smoke”: both checked synthetic square samples were not supported. The other
  retrieved windows were not checked, so this does not establish absence across the library.

Provider compatibility failures were corrected by changing the default model to
`gemini-3.8-flash` and removing an unsupported thinking setting. A transient retrieval failure
and an image-request timeout also occurred. The final bounded fire/smoke retry succeeded with
a longer timeout. Provider failures return an error without accepting any visual matches.

These are small smoke checks, not accuracy measurements. Full multi-frame website validation,
representative authorised CCTV testing, and private credential replacement remain pending.
