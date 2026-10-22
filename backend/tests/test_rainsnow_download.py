"""Offline integrity checks for the licensed research acquisition tool."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/download_rainsnow.py'
spec = importlib.util.spec_from_file_location('rainsnow_download', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_archive(tmp_path, monkeypatch, member='cam1.mkv'):
    monkeypatch.setattr(module, 'FOLDER', tmp_path)
    archive = tmp_path/'example.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(member, b'research-video')
    return {'name': 'example', 'archive_sha256': module.sha(archive),
            'video_sha256': hashlib.sha256(b'research-video').hexdigest()}


def test_verified_archive_extracts_only_expected_member(tmp_path, monkeypatch):
    clip = fixture_archive(tmp_path, monkeypatch)
    module.acquire(clip)
    assert (tmp_path/'originals/example.mkv').read_bytes() == b'research-video'
    module.acquire(clip)


def test_modified_existing_source_is_preserved_and_rejected(tmp_path, monkeypatch):
    clip = fixture_archive(tmp_path, monkeypatch)
    module.acquire(clip)
    target = tmp_path/'originals/example.mkv'
    target.write_bytes(b'modified')
    with pytest.raises(ValueError, match='Existing source'):
        module.acquire(clip)
    assert target.read_bytes() == b'modified'


def test_archive_paths_are_never_extracted(tmp_path, monkeypatch):
    clip = fixture_archive(tmp_path, monkeypatch, '../escape.mkv')
    with pytest.raises(ValueError, match='Unexpected archive'):
        module.acquire(clip)
    assert not (tmp_path.parent/'escape.mkv').exists()


def test_changed_archive_is_rejected(tmp_path, monkeypatch):
    clip = fixture_archive(tmp_path, monkeypatch)
    clip['archive_sha256'] = '0'*64
    with pytest.raises(ValueError, match='Existing archive'):
        module.acquire(clip)
    assert not (tmp_path/'originals/example.mkv').exists()


def test_default_is_plan_only_and_manifest_prohibits_cloud():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True)
    assert 'Plan only' in result.stdout
    plan = json.loads(module.MANIFEST.read_text())
    assert plan['google_processing_approved'] is False
    assert plan['license'] == 'CC BY 4.0'


def test_failed_download_cleans_partial_file(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(module, 'FOLDER', tmp_path)
    monkeypatch.setattr(module, 'LIMIT', 3)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(b'too-large'))
    clip = {'name': 'test', 'publisher_path': 'test/test/cam1.mkv', 'archive_sha256': '0'*64}
    with pytest.raises(ValueError, match='size limit'):
        module.acquire(clip)
    assert not (tmp_path/'test.zip').exists()
    assert not (tmp_path/'test.partial').exists()
