"""The offline demo must stay offline even with a real key in the parent environment."""
import pytest
from tanya.config import SearchSettings
from tanya.offline_demo import replay_search
from tanya.web import create_app
from tests.search_fixtures import search_env  # noqa: F401


def test_replay_workflow_and_api_guards(search_env, monkeypatch):
    env = search_env
    def forbidden(*args, **kwargs):
        pytest.fail('Offline replay attempted an engine or image request')
    monkeypatch.setattr('tanya.sentry_client.run_bridge', forbidden)
    monkeypatch.setattr('tanya.visual_review.run_review', forbidden)
    app = create_app(env.settings, SearchSettings(None, env.search_settings.bridge_path), offline_search=replay_search)
    client = app.test_client()
    assert b'OFFLINE REPLAY DEMO' in client.get('/').data
    with client.session_transaction() as session:
        headers = {'X-CSRF-Token': session['csrf']}
    assert client.get('/api/status').json['offline_demo'] is True
    assert client.get('/api/status').json['search_ready'] is True
    result = client.post('/api/search', headers=headers, json={'query': 'a red car'})
    assert result.status_code == 200
    hit = result.json['hits'][0]
    assert (hit['filename'], hit['start_sec'], hit['end_sec']) == ('cam2_carpark.mp4', 16, 40)
    assert 'OFFLINE REPLAY' in result.json['warnings'][0] or any('OFFLINE REPLAY' in w for w in result.json['warnings'])
    assert client.get(hit['video_url'], headers={'Range': 'bytes=0-99'}).status_code == 206
    for path, payload in [('/api/search/plan', {}), ('/api/search/sync', {'confirmed': True}),
                          ('/api/search', {'query': 'a red car', 'visual_check': True, 'approve_frame_upload': True})]:
        assert client.post(path, headers=headers, json=payload).status_code == 403
    unknown = client.post('/api/search', headers=headers, json={'query': 'an unrecorded event'})
    assert unknown.status_code == 503 and 'No live search was run' in unknown.json['error']
    # The injected replay also supports the complete investigation/report workflow.
    iid = client.post('/api/investigations', headers=headers, json={'title': 'Offline rehearsal'}).json['id']
    searched = client.post('/api/search', headers=headers, json={'query': 'a red car', 'investigation_id': iid})
    assert searched.status_code == 200 and searched.json['saved_query']
    evidence = client.post(f'/api/investigations/{iid}/evidence', headers=headers, json=dict(
        video_id=hit['video_id'], start_sec=hit['start_sec'], end_sec=hit['end_sec'],
        query='a red car', search_mode='ranked', rank=1, best_score=hit['best_score'],
        score_above_median=hit['best_score_above_median']))
    assert evidence.status_code == 201
    eid = evidence.json['id']
    assert client.post(f'/api/investigations/{iid}/evidence/{eid}/review', headers=headers,
                       json={'decision': 'correct', 'note': 'Synthetic rehearsal'}).status_code == 200
    report = client.post(f'/api/investigations/{iid}/report', headers=headers, json={'format': 'json'})
    assert report.json['summary']['human_confirmed'] == 1
    assert client.post(f'/api/investigations/{iid}/report', headers=headers,
                       json={'format': 'html'}).mimetype == 'text/html'
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    assert client.get('/api/status').json['search_ready'] is True
    assert env.calls() == []
