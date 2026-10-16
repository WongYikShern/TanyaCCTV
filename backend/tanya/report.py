"""Self-contained HTML review page for search results (demo / human review).

No server and no external resources: the page links to the local video files and extracted
frames with file:// URLs. Every value is HTML-escaped. The page never contains configuration or
secrets; it only shows what is in the SearchResponse (or an already-redacted error message).
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from .config import Settings
from .search import SearchResponse

CSS = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#5b6475; --line:#d9dde5;
        --warn-bg:#fff4d6; --warn-line:#e0b03a; --err-bg:#fde8e8; --err-line:#d64545; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14171d; --card:#1d222b; --text:#e6e9ef; --muted:#9aa3b5; --line:#2e3542;
          --warn-bg:#3a3014; --warn-line:#b8902e; --err-bg:#3b1d1d; --err-line:#c95b5b; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--text);
       font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.meta { color: var(--muted); margin: 0 0 16px; }
.banner { background: var(--warn-bg); border: 1px solid var(--warn-line); border-radius: 8px;
          padding: 12px 14px; margin-bottom: 16px; }
.error { background: var(--err-bg); border-color: var(--err-line); }
.hit { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px;
       margin-bottom: 14px; display: grid; grid-template-columns: 320px 1fr; gap: 14px; }
@media (max-width: 720px) { .hit { grid-template-columns: 1fr; } }
.hit video, .hit img { width: 100%; border-radius: 6px; background: #000; aspect-ratio: 16/9; object-fit: contain; }
.noimg { display:flex; align-items:center; justify-content:center; aspect-ratio:16/9; border-radius:6px;
         border:1px dashed var(--line); color: var(--muted); }
.title { font-weight: 600; margin: 0 0 4px; word-break: break-all; }
.badge { display:inline-block; font-size:12px; font-weight:600; padding:2px 8px; border-radius:999px;
         background: var(--warn-bg); border:1px solid var(--warn-line); }
.small { color: var(--muted); font-size: 13px; }
ul { margin: 6px 0 0; padding-left: 18px; }
a { color: inherit; }
"""


def _fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def _uri(path: Path) -> str:
    return path.resolve().as_uri()


def render_html(settings: Settings, query: str, response: SearchResponse | None = None,
                error: str | None = None, generated: datetime | None = None) -> str:
    """Render the review page for a response, or an error page if `error` is given."""
    generated = generated or datetime.now()
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>TanyaCCTV search: {escape(query)}</title><style>{CSS}</style></head><body><main>",
        "<h1>TanyaCCTV search results</h1>",
        f"<p class='meta'>Query: <strong>{escape(query)}</strong> &middot; generated "
        f"{escape(generated.strftime('%Y-%m-%d %H:%M'))}</p>",
        "<div class='banner'><strong>Unverified results &mdash; human review required.</strong> "
        "These clips are ranked by visual similarity to the query. They are not detected or "
        "confirmed incidents and stay unverified until a person independently confirms them. "
        "Similarity scores only order the results: they are not calibrated probabilities, and a "
        "missing or low-ranked result does not prove that nothing happened.</div>",
    ]
    if error is not None:
        parts.append(f"<div class='banner error'><strong>Search failed.</strong> {escape(error)}</div>")
    elif response is not None:
        if not response.hits:
            parts.append("<div class='banner'>No matching clips were found in the indexed TanyaCCTV videos. "
                         "Check that the videos have been indexed for search "
                         "(<code>sync_search_index.py</code>) and try different wording.</div>")
        for i, h in enumerate(response.hits, start=1):
            video = settings.video_dir / h.rel_path
            src = f"{_uri(video)}#t={h.start_sec:g},{h.end_sec:g}"
            poster = settings.frames_dir / h.thumbnail if h.thumbnail else None
            poster_attr = f" poster='{escape(_uri(poster))}'" if poster else ""
            thumb = (f"<a href='{escape(_uri(poster))}'>open frame at {_fmt(h.thumbnail_timestamp_sec or 0)}</a>"
                     if poster else "no extracted frame available")
            chunks = ", ".join(f"{_fmt(c.start_sec)}&ndash;{_fmt(c.end_sec)} ({c.score:.3f})" for c in h.chunks)
            parts.append(
                "<section class='hit'><div>"
                f"<video controls preload='metadata' src='{escape(src)}'{poster_attr}></video>"
                + ("" if poster else "<div class='noimg'>no thumbnail</div>")
                + "</div><div>"
                f"<p class='title'>#{i} {escape(h.rel_path)}</p>"
                f"<p><strong>{_fmt(h.start_sec)} &ndash; {_fmt(h.end_sec)}</strong> &nbsp;"
                f"<span class='badge'>{escape(h.status)} &middot; needs review</span></p>"
                f"<p class='small'>Best similarity {h.best_score:.3f} ({h.best_score_above_median:+.3f} vs. this "
                f"query's median). A ranking signal only, not a probability or confidence.</p>"
                f"<p class='small'>Chunks: {chunks}</p>"
                f"<p class='small'><a href='{escape(_uri(video))}'>open video file</a> &middot; {thumb}</p>"
                "<p class='small'>If the clip does not play, the video codec may not be supported by the "
                "browser; open the video file and seek to the time shown.</p>"
                "</div></section>")
        if response.warnings:
            items = "".join(f"<li>{escape(w)}</li>" for w in response.warnings)
            parts.append(f"<div class='banner'><strong>Warnings</strong><ul>{items}</ul></div>")
    parts.append("</main></body></html>")
    return "\n".join(parts)
