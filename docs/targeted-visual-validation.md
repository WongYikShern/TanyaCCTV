# Targeted visual review — 19 October 2026

The owner approved sending **66 sampled images from the five synthetic cartoon clips** to
Google Gemini 3.8 Flash for three queries. This run reused the saved retrieval responses;
there was no video re-indexing or additional text embedding. All three requests succeeded,
with no automatic retries. The estimate was about US$0.20; actual billing was not inspected.

The existing production pipeline checked up to the first five retrieved windows, with up to
six samples per window. It validates candidate IDs and evidence timestamps, separates supported,
unclear and not-supported results, and preserves underlying `uncertain` status.

| Query | Images / checked windows | Outcome |
|---|---|---|
| a person standing still for a long time | 30 / 5 | Correct entrance window at retrieval rank 5 became the first supported candidate. Four higher-ranked windows were not supported. A sixth unreviewed window remained unclear. |
| a parked car | 12 / 2 | Moving red car at rank 1 was not supported. Stationary blue car at rank 2 was supported, citing 25 and 33 s (inside the labelled 20–35 s interval). |
| a person falling down | 24 / 4 | Correct corridor window supported, citing 21 s falling and 26 s lying down. Lobby clip unclear: sampled frames show upright then lying, but not the fall. Two walking clips were not supported. |

Across 11 checked windows: **3 supported, 7 not supported, 1 unclear**. Each supported candidate
matches its query's labelled video/window. One additional retrieved window was not checked.
These denominators describe this selected sample, not precision/recall for arbitrary CCTV.

The corridor samples at 16, 21 and 26 s were also inspected locally: upright walking, a tilted
falling pose, then lying down. The fall annotation is 20–23 s. The result still retains its
broad 16–40 s context; the model's evidence times are sample positions, not estimated onset/end.
Likewise, supported sustained standing in a cartoon is not a reliable real-world loitering alarm.

## What changed

- The existing opt-in visual review was verified on these weak retrieval cases. It promoted
  supported candidates by separating higher-ranked unrelated windows, without changing raw
  embedding scores or merge defaults.
- The SDK is now configured for **one attempt** per visual request. A transient failure returns
  an error; resending needs a fresh reviewed image-upload approval. This keeps an approved
  bounded frame send from being silently duplicated by transport retries.
- Saved decisions and reasons are in
  `evaluation/recordings/2026-10-19-targeted-visual.json`. No image payloads, credentials, local
  file paths or footage are committed. Offline regression tests protect the observed scope,
  evidence timestamps and explicit ambiguity of the lobby fall case.

## How to use this in the real website

For prepared recordings, leave **Also check the actual images** selected, review its upload/cost
notice and approve that search. Without the check, rankings still include the weak results
reported in `event-support.md`. The free offline replay launcher intentionally blocks new
image calls and does not replay these three visual queries; this recording is separate.

## Remaining limitations

- No ranking/model threshold was tuned or claimed fixed. This demonstrates filtering on three
  selected positive synthetic queries, not a general improvement in retrieval accuracy.
- Negative-query visual rejection was not tested in this 66-image run. Earlier fire/smoke
  sample checks remain a separate small validation.
- Short actions may occur between samples; a missing or unclear match is not proof of absence.
  Exact timing, reliable loitering definitions and broad real-world accuracy remain unverified.
- Real CCTV testing requires authorised footage, independent labels and separate permission
  before any Google processing. No additional real footage is available.
- Teammate review/merge remains their decision. The 66-image allowance is fully consumed;
  additional live requests need a new plan/approval.
