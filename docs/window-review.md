# Reviewing broad search windows — 19 October 2026

The five-clip evaluation showed broad merged windows and weak rankings for loitering and
parked cars. We compared existing merge ratios offline using the saved responses. No new API
calls, model changes or query-specific rules were used.

| Recorded dataset | Merge ratio | P@5 | R@5 | Mean first-relevant IoU | hit@1 |
|---|---:|---:|---:|---:|---:|
| Earlier 2 clips, 3 positive queries | 0 | 0.833 | 1.000 | 0.548 | 1.000 |
| Earlier 2 clips, 3 positive queries | 0.5 (default) | 0.500 | 1.000 | 0.867 | 1.000 |
| Earlier 2 clips, 3 positive queries | 0.75 | 0.500 | 1.000 | 0.867 | 1.000 |
| Earlier 2 clips, 3 positive queries | 1 | 0.667 | 1.000 | 0.417 | 1.000 |
| Extended 5 clips, 11 positive queries | 0 | 0.579 | 1.000 | 0.375 | 0.818 |
| Extended 5 clips, 11 positive queries | 0.5 (default) | 0.508 | 1.000 | 0.453 | 0.818 |
| Extended 5 clips, 11 positive queries | 0.75 | 0.426 | 0.909 | 0.505 | 0.727 |
| Extended 5 clips, 11 positive queries | 1 | 0.509 | 0.841 | 0.510 | 0.727 |

Narrow grouping improves IoU on the extended set but reduces recall and first-result success.
The earlier set favours the existing default for timing. Broad grouping inflates overlap-based
recall. These are two small recorded datasets, not independent real-world validation, so the
default ratio and ranking remain unchanged. We did not select a new threshold from these results.

## Implemented improvement: inspect the strongest source chunk

A merged result now exposes `review_focus`, the strongest-scoring original chunk intersected
with the result bounds. Equal scores use the earliest retrieval rank. No chunk yields no focus.
It is derived from existing results and sends no requests to Google.

The result card keeps **Play from…** for the full context and adds **Inspect strongest chunk…**
when the focus is narrower. It explains that chunk times are not event boundaries. This helps
an operator start with a shorter relevant portion, without claiming to locate a precise action
or hiding the surrounding footage. Underlying rankings, scores, full window, review status and
investigation/feedback references are unchanged. Existing image-evidence buttons remain available.

The recorded car example keeps 16–40 s as full context and offers 24–34 s as focus. Browser
verification opened focus at 24 s and showed its 24–34 s window. Full-context control retained
16–40 s. No browser console warnings/errors were observed. Regression checks cover bounds,
tie-breaking, missing chunks and unchanged ranking/status.

Reproduce the table by re-scoring each recording with `evaluate_search.py --merge-ratio`
set to 0, 0.5, 0.75 and 1. Use the corresponding ground truth and `--recorded` paths from
`docs/search-evaluation.md`. No `--live` flag is needed.

Still pending: independent labels and authorised real footage, additional approved validation
for query-ranking improvements, and teammate PR review. Loitering and parked-car ranking are
not fixed by this navigation aid. No additional CCTV footage has been supplied.
