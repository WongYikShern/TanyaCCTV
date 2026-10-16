"""Tests for the HTML review page and the search CLI's --html / --open options (fake bridge)."""

from __future__ import annotations

from pathlib import Path

import pytest

import search_videos as search_cli
from tanya.report import render_html
from tanya.search import Chunk, SearchHit, SearchResponse, search_videos
from tests.search_fixtures import FAKE_KEY, cli_env, search_env  # noqa: F401


def hit(**kw) -> SearchHit:
    base = dict(video_id=1, rel_path="cam1_lobby.mp4", filename="cam1_lobby.mp4", start_sec=16.0, end_sec=42.0,
                best_score=0.401, best_score_above_median=0.057,
                chunks=[Chunk(1, 16.0, 26.0, 0.401, 0.057), Chunk(2, 24.0, 34.0, 0.396, 0.052)],
                thumbnail="abc/frame_000029_000029000ms.jpg", thumbnail_timestamp_sec=29.0)
    base.update(kw)
    return SearchHit(**base)


def page(workspace, **kw) -> str:
    return render_html(workspace.settings(), kw.pop("query", "a person walking"), **kw)


def test_page_shows_unverified_banner_and_status(workspace):
    html = page(workspace, response=SearchResponse("a person walking", [hit()]))
    assert "Unverified results" in html and "human review required" in html
    assert "uncertain &middot; needs review" in html
    assert "confirmed" not in html.replace("not detected or confirmed", "")


def test_clip_starts_at_the_matched_window_and_uses_the_thumbnail(workspace):
    html = page(workspace, response=SearchResponse("q", [hit()]))
    video_uri = (workspace.video_dir / "cam1_lobby.mp4").resolve().as_uri()
    assert f"src='{video_uri}#t=16,42'" in html
    assert "00:16 &ndash; 00:42" in html
    assert (workspace.frames_dir / "abc" / "frame_000029_000029000ms.jpg").resolve().as_uri() in html
    assert "open frame at 00:29" in html


def test_missing_thumbnail_shows_placeholder(workspace):
    html = page(workspace, response=SearchResponse("q", [hit(thumbnail=None, thumbnail_timestamp_sec=None)]))
    assert "no thumbnail" in html and "poster=" not in html


def test_everything_is_escaped(workspace):
    evil = "<script>alert('x')</script>"
    html = page(workspace, query=evil, response=SearchResponse(evil, [hit(rel_path=f"a{evil}.mp4")],
                                                                   warnings=[evil]))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_and_error_states(workspace):
    assert "No matching clips were found" in page(workspace, response=SearchResponse("q", []))
    html = page(workspace, error="search engine timed out after 60s")
    assert "Search failed." in html and "timed out after 60s" in html


def test_page_never_contains_the_key(workspace, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert FAKE_KEY not in page(workspace, response=SearchResponse("q", [hit()]))


# --------------------------------------------------------------------------- CLI


def test_cli_writes_review_page(cli_env, tmp_path, capsys):
    out = tmp_path / "results.html"
    assert search_cli.main(["a red car", "--n", "5", "--html", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "cam2_carpark.mp4" in html and "#t=16,40" in html and "Unverified results" in html
    err = capsys.readouterr().err
    assert "Searching for" in err and "Review page written" in err


def test_cli_writes_error_page_without_the_key(cli_env, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_BRIDGE_MODE", "error")
    out = tmp_path / "results.html"
    assert search_cli.main(["x", "--html", str(out)]) == 3
    html = out.read_text(encoding="utf-8")
    assert "Search failed." in html and FAKE_KEY not in html and "***REDACTED***" in html


def test_cli_open_requires_html(cli_env):
    with pytest.raises(SystemExit) as exc:
        search_cli.main(["x", "--open"])
    assert exc.value.code == 2


def test_cli_open_launches_browser_with_file_uri(cli_env, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(search_cli.webbrowser, "open", opened.append)
    out = tmp_path / "r.html"
    assert search_cli.main(["a red car", "--html", str(out), "--open"]) == 0
    assert opened == [out.resolve().as_uri()]


def test_real_search_response_renders(search_env):
    response = search_videos("a person lying on the floor", search_env.settings, search_env.search_settings, n=5)
    html = render_html(search_env.settings, response.query, response)
    thumb = Path(search_env.settings.frames_dir / response.hits[0].thumbnail).resolve().as_uri()
    assert thumb in html and "#t=40,60" in html


@pytest.mark.parametrize("name", ["tanya.db", "README.md", "results", "page.html.bak"])
def test_cli_refuses_non_html_output_path_before_searching(cli_env, tmp_path, name):
    """Regression: --html data\tanya.db overwrote the database with an HTML page."""
    target = tmp_path / name
    target.write_bytes(b"precious data")
    with pytest.raises(SystemExit) as exc:
        search_cli.main(["a red car", "--html", str(target)])
    assert exc.value.code == 2
    assert target.read_bytes() == b"precious data"
    assert cli_env.calls() == []          # the search engine was never started


@pytest.mark.parametrize("name", ["r.html", "R.HTM"])
def test_cli_accepts_html_suffixes(cli_env, tmp_path, name):
    assert search_cli.main(["a red car", "--html", str(tmp_path / name)]) == 0


def test_scores_are_described_as_ranking_signals_not_probabilities(search_env):
    """Regression: the wording said 'not confidence' but never 'not probabilities' (a 1.000 reads as 100%)."""
    response = search_videos("a red car", search_env.settings, search_env.search_settings, n=5)
    assert "not calibrated probabilities" in response.note and "unverified" in response.note
    html = render_html(search_env.settings, response.query, response)
    assert "not calibrated probabilities" in html
    assert "independently confirms" in html
    assert html.count("A ranking signal only, not a probability or confidence.") == len(response.hits)
