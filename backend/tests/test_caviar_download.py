"""Dataset download safeguards; no network, footage or Google calls in these tests."""
import hashlib
import io
import sys
import pytest
import download_caviar

URL = 'https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/Walk1/Walk1.mpg'


class Response(io.BytesIO):
    def geturl(self):
        return URL


def test_download_verifies_hash_and_reuses_existing_file(tmp_path, monkeypatch):
    raw = b'public-video-test-bytes'
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(download_caviar.urllib.request, 'urlopen', lambda *a, **kw: Response(raw))
    target = tmp_path/'clip.mpg'
    result = download_caviar.download(URL, target, 100, digest)
    assert result == dict(bytes=len(raw), sha256=digest)
    monkeypatch.setattr(download_caviar.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('must reuse local file'))
    assert download_caviar.download(URL, target, 100, digest) == result
    with pytest.raises(ValueError):
        download_caviar.download(URL, target, 100, 'wrong-hash')
    assert target.read_bytes() == raw


@pytest.mark.parametrize('limit,expected', [(3,None), (100,'wrong-hash')])
def test_oversize_or_changed_download_leaves_no_partial_file(tmp_path, monkeypatch, limit, expected):
    monkeypatch.setattr(download_caviar.urllib.request, 'urlopen', lambda *a, **kw: Response(b'video-bytes'))
    target = tmp_path/'clip.mpg'
    with pytest.raises(ValueError):
        download_caviar.download(URL, target, limit, expected)
    assert not target.exists() and not target.with_suffix('.mpg.partial').exists()


def test_default_plan_does_not_download(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['download_caviar.py'])
    monkeypatch.setattr(download_caviar.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('dry run must stay offline'))
    assert download_caviar.main() == 0
    assert 'Nothing downloaded' in capsys.readouterr().out


def test_research_viewer_blocks_cloud_calls_even_with_a_key(workspace, monkeypatch):
    from tests.conftest import make_video
    from pathlib import Path
    def forbidden(*args, **kwargs):
        pytest.fail('Research viewer must never call an AI bridge')
    monkeypatch.setattr('tanya.sentry_client.run_bridge', forbidden)
    monkeypatch.setenv('GEMINI_API_KEY', 'FAKE-local-research-test-key')
    make_video(workspace.video_dir/'camera.mp4')
    workspace.run()
    # The viewer uses its own folder layout, so point its expected filenames at this fixture.
    folder = workspace.db_path.parent
    (folder/'videos.db').write_bytes(workspace.db_path.read_bytes())
    app = download_caviar.review_app(folder)
    client = app.test_client()
    assert b'Google processing disabled' in client.get('/').data
    with client.session_transaction() as session:
        headers = {'X-CSRF-Token': session['csrf']}
    for path in ('/api/search','/api/search/plan','/api/search/sync'):
        assert client.post(path, headers=headers, json={'query':'person','confirmed':True}).status_code == 403
    assert client.get('/api/status').json['search_ready'] is False
    video = client.get('/api/videos').json['videos'][0]
    assert client.get(video['video_url'],headers={'Range':'bytes=0-99'}).status_code == 206
