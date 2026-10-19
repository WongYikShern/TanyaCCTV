"""No network: exhaustive candidate scope, approval, privacy, cancellation and failure rules."""
from pathlib import Path
from copy import deepcopy
import pytest

from tanya import scenario_scan
from tanya.config import SearchSettings
from tanya.sentry_client import SearchError
from tanya.web import create_app
from tests.conftest import make_video


@pytest.fixture
def scans(workspace):
    for i in range(2):
        make_video(workspace.video_dir/f'camera{i}.mp4', seconds=26, seed=i)
    workspace.run()
    return workspace


def decisions(payload, settings):
    return [dict(id=c['id'], verdict='supported', reason='Requested scene visible.',
                 evidence_timestamps=[c['frames'][0]['timestamp_sec']]) for c in payload['candidates']]


def test_plan_covers_all_recordings_and_tail_without_retrieval(scans, monkeypatch):
    monkeypatch.setattr('tanya.sentry_client.search', lambda *a: pytest.fail('must not retrieve'))
    p = scenario_scan.build_library_plan(scans.settings(), 'a person exits carrying a bag')
    assert len(p['videos']) == 2
    assert len(p['hits']) == 8
    for video in p['videos']:
        hits = [h for h in p['hits'] if h['video_id'] == video['id']]
        assert hits[0]['start_sec'] == 0 and hits[-1]['end_sec'] == 26
        assert all(b['start_sec'] <= a['end_sec'] for a,b in zip(hits,hits[1:]))
    assert p['max_calls'] == 2 and p['max_images'] == 48
    public = scenario_scan.public_plan(p)
    assert len(public['recordings']) == 2 and len(public['ranges']) == 2
    assert str(scans.video_dir) not in str(public)


def test_batches_cover_a_low_ranked_tail_and_cannot_be_replayed(scans):
    p = scenario_scan.build_library_plan(scans.settings(), 'a car stops then a person gets out')
    checked = []
    def reviewer(payload, settings):
        assert len(payload['candidates']) <= 5
        assert sum(len(c['frames']) for c in payload['candidates']) <= 30
        checked.extend(payload['candidates'])
        return decisions(payload, settings)
    first = scenario_scan.run_batch(p, 0, scans.settings(), SearchSettings(None,Path('unused')), reviewer)
    assert first['completed_windows'] == 5 and not first['done']
    with pytest.raises(ValueError):
        scenario_scan.run_batch(p, 0, scans.settings(), None, reviewer)
    second = scenario_scan.run_batch(p, 1, scans.settings(), None, reviewer)
    assert second['done'] and second['completed_windows'] == 8
    assert len(checked) == 8 and all(h['best_score'] is None for h in second['hits'])


def test_changed_source_rejected_before_any_model_call(scans):
    p = scenario_scan.build_library_plan(scans.settings(), 'person')
    (scans.video_dir/'camera0.mp4').write_bytes(b'changed')
    with pytest.raises(SearchError, match='changed'):
        scenario_scan.run_batch(p, 0, scans.settings(), None,
                                lambda *a: pytest.fail('must not upload'))


def test_timeout_consumes_attempt_and_needs_new_plan(scans):
    p = scenario_scan.build_library_plan(scans.settings(), 'person')
    def failed(*args):
        raise SearchError('Timeout')
    with pytest.raises(SearchError):
        scenario_scan.run_batch(p, 0, scans.settings(), None, failed)
    assert p['next_batch'] == 1
    with pytest.raises(ValueError):
        scenario_scan.run_batch(p, 0, scans.settings(), None, failed)


@pytest.mark.parametrize('change', [dict(query=''), dict(video_ids=['1']), dict(start=-1),
                                  dict(start=True), dict(end=float('nan')), dict(video_ids=[999])])
def test_bad_scope_cannot_create_upload_plan(scans, change):
    args=dict(query='scene',video_ids=[scans.videos()[0]['id']]);args.update(change)
    with pytest.raises(ValueError):
        scenario_scan.build_library_plan(scans.settings(), **args)


def test_missing_recording_is_explicitly_excluded(scans):
    (scans.video_dir/'camera1.mp4').unlink()
    p = scenario_scan.build_library_plan(scans.settings(), 'person')
    assert len(p['videos']) == 1
    assert p['excluded'][0]['filename'] == 'camera1.mp4'


def test_api_requires_reviewed_plan_owner_and_approval(scans, monkeypatch):
    calls=[]
    monkeypatch.setattr('tanya.visual_review.run_review', lambda p,s: calls.append(p) or decisions(p,s))
    app=create_app(scans.settings(),SearchSettings(None,Path('unused')))
    app.config['TESTING']=True
    c=app.test_client();c.get('/')
    with c.session_transaction() as session:headers={'X-CSRF-Token':session['csrf']}
    assert c.post('/api/search/scan/plan',json={'query':'scene'}).status_code == 403
    response=c.post('/api/search/scan/plan',headers=headers,json={'query':'scene'})
    assert response.status_code == 200 and not calls
    plan=response.json;payload=dict(scan_id=plan['scan_id'],batch=0)
    assert c.post('/api/search/scan/batch',headers=headers,json=payload).status_code == 400
    payload['approve_frame_upload']=True
    other=app.test_client();other.get('/')
    with other.session_transaction() as session:other_headers={'X-CSRF-Token':session['csrf']}
    assert other.post('/api/search/scan/batch',headers=other_headers,json=payload).status_code == 409
    result=c.post('/api/search/scan/batch',headers=headers,json=payload)
    assert result.status_code == 200 and len(calls) == 1
    assert result.json['hits'][0]['video_url'].startswith('/media/videos/')
    assert c.post('/api/search/scan/cancel',headers=headers,json={'scan_id':plan['scan_id']}).status_code == 200
    payload['batch']=1
    assert c.post('/api/search/scan/batch',headers=headers,json=payload).status_code == 409
    assert len(calls) == 1


def test_offline_demo_prohibits_direct_scan(scans):
    app=create_app(scans.settings(),SearchSettings(None,Path('unused')),offline_search=lambda *a:None)
    c=app.test_client();c.get('/')
    with c.session_transaction() as s:headers={'X-CSRF-Token':s['csrf']}
    assert c.post('/api/search/scan/plan',headers=headers,json={'query':'scene'}).status_code == 403
    assert c.post('/api/search/scan/batch',headers=headers,json={'approve_frame_upload':True}).status_code == 403


def test_new_upload_joins_next_plan_but_never_expands_existing_approval(scans):
    original=scenario_scan.build_library_plan(scans.settings(),'scene')
    make_video(scans.video_dir/'new-camera.mp4',seconds=3,seed=8)
    scans.run()
    assert len(original['videos']) == 2
    assert all(h['filename'] != 'new-camera.mp4' for h in original['hits'])
    refreshed=scenario_scan.build_library_plan(scans.settings(),'scene')
    assert len(refreshed['videos']) == 3
    assert refreshed['hits'][-1]['filename'] == 'new-camera.mp4'
    assert [h['scan_window'] for h in refreshed['hits']] == list(range(1,len(refreshed['hits'])+1))


def test_selected_range_is_not_silently_extended(scans):
    ident=scans.videos()[0]['id']
    p=scenario_scan.build_library_plan(scans.settings(),'scene',[ident],start=8,end=17)
    assert len(p['videos']) == 1 and len(p['hits']) == 1
    assert p['hits'][0]['start_sec'] == 8 and p['hits'][0]['end_sec'] == 17
    assert p['max_images'] == 6 and p['max_calls'] == 1


def test_far_too_large_range_requires_explicit_smaller_scope(scans):
    import sqlite3
    with sqlite3.connect(scans.db_path) as conn:
        conn.execute('UPDATE videos SET duration_sec=10000')
    with pytest.raises(ValueError,match='No selected recording'):
        scenario_scan.build_library_plan(scans.settings(),'scene')
