"""Metric and readiness tests use invented labels, never genuine AI inference."""
from copy import deepcopy
import pytest
from tanya.real_benchmark import budget_plan, evaluate_recording, fingerprint, readiness


def fixture():
    def case(ident,events):
        review=dict(reviewer='Alice',method='human_full_video',presence='present' if events else 'absent',events=events)
        other=dict(review,reviewer='Bob')
        return dict(id=ident,query=ident,clip_reviews=[dict(clip_id='clip',review_a=review,review_b=other)])
    return dict(clips=[dict(id='clip',duration_sec=60,sha256='a'*64)],cases=[case('positive',[dict(start_sec=40,end_sec=45)]),case('negative',[])])


def recording(data,mode='ranked'):
    return dict(dataset_sha256=fingerprint(data),mode=mode,provenance=dict(inference='mock'),indexed_clips=['clip'],queries=[])


def test_missing_reviews_and_disagreement_block_scoring():
    data=fixture();data['cases'][0]['clip_reviews'][0]['review_b']=None
    ready,blocked=readiness(data)
    assert list(ready)==['negative'] and len(blocked)==1
    data=fixture();data['cases'][0]['clip_reviews'][0]['review_b']['reviewer']='Alice'
    assert len(readiness(data)[1])==1


def test_wrong_dataset_and_missing_provenance_rejected():
    data=fixture();run=recording(data);run['dataset_sha256']='wrong'
    with pytest.raises(ValueError):evaluate_recording(data,run)
    run=recording(data);run['provenance']={'inference':'live_ai'}
    with pytest.raises(ValueError):evaluate_recording(data,run)


def test_missing_partial_negative_never_correct_rejection():
    data=fixture();run=recording(data)
    run['queries']=[dict(case_id='negative',status='partial',windows=[])]
    report=evaluate_recording(data,run)
    assert report['summary']['negative_query_return_rate'] is None
    assert len(report['not_measured'])==2


def test_timing_duplicates_and_false_positive():
    data=fixture();run=recording(data)
    run['queries']=[dict(case_id='positive',status='completed',windows=[dict(video='clip',start_sec=40,end_sec=45)]*2),dict(case_id='negative',status='completed',windows=[dict(video='clip',start_sec=0,end_sec=10)])]
    report=evaluate_recording(data,run)
    assert report['summary']['recall_at_5']==1
    assert report['summary']['mean_start_error_sec']==0
    assert report['summary']['false_positive_windows']==1
    assert report['summary']['negative_query_return_rate']==1
    assert 'not genuine AI' in report['metrics_source']


def test_scan_chronology_and_full_recall_are_distinct():
    data=fixture();run=recording(data,'scene_scan')
    windows=[dict(video='clip',start_sec=40,end_sec=45,verdict='supported')]+[dict(video='clip',start_sec=i,end_sec=i+1,verdict='supported') for i in range(6)]
    run['queries']=[dict(case_id='positive',status='completed',coverage_complete=True,windows=windows)]
    report=evaluate_recording(data,run)
    assert report['summary']['recall_at_5']==0
    assert report['summary']['recall_all']==1
    run['queries'][0]['coverage_complete']=False
    assert evaluate_recording(data,run)['summary']['measured_queries']==0


def test_budget_is_only_a_plan():
    plan=budget_plan(fixture())
    assert plan['approval']==dict(approved=False,quota_verified=False,budget_usd=None)
    assert plan['scene_scan']['max_images']==2*9*6
    assert plan['ranked']['indexing_calls']>0


def test_merge_keeps_independent_reviews_and_blocks_incomplete_exports():
    from tanya.real_benchmark import merge_reviews
    data=fixture()
    first=dict(dataset_sha256=fingerprint(data),reviewer='Alice',method='human_full_video',decisions=[dict(case_id='negative',clip_id='clip',presence='absent',events=[],full_video_watched=True)])
    second=dict(first,reviewer='Bob')
    merged=merge_reviews(data,first,second)
    ready,blocked=readiness(merged)
    assert list(ready)==['negative'] and len(blocked)==1
    assert data['cases'][0]['clip_reviews'][0]['review_a'] is not None
    with pytest.raises(ValueError):merge_reviews(data,first,dict(second,reviewer='alice'))
    incomplete=deepcopy(second);incomplete['decisions'][0]['full_video_watched']=False
    with pytest.raises(ValueError):merge_reviews(data,first,incomplete)
    stale=dict(second,dataset_sha256='wrong')
    with pytest.raises(ValueError):merge_reviews(data,first,stale)


def test_review_server_serves_only_verified_media_and_hides_labels(tmp_path,monkeypatch):
    import hashlib
    import importlib.util
    import json
    from pathlib import Path
    script=Path(__file__).resolve().parents[1]/'scripts/review_real_benchmark.py'
    spec=importlib.util.spec_from_file_location('review_server_test',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',tmp_path)
    media=tmp_path/'data/cctv_validation/sample.mp4';media.parent.mkdir(parents=True);media.write_bytes(b'fake-media-for-http-test')
    page=tmp_path/'evaluation/real_cctv/review.html';page.parent.mkdir(parents=True);page.write_text('<title>review</title>',encoding='utf-8')
    data=fixture();data['clips'][0].update(path=str(media.relative_to(tmp_path)),sha256=hashlib.sha256(media.read_bytes()).hexdigest())
    dataset=tmp_path/'dataset.json';dataset.write_text(json.dumps(data),encoding='utf-8')
    client=module.create_app(dataset).test_client()
    assert client.get('/').status_code==200
    body=client.get('/dataset').get_json()
    assert 'clip_reviews' not in body['cases'][0]
    assert client.get('/.env').status_code==404
    assert client.get('/media/999').status_code==404
    response=client.get('/media/0',headers={'Range':'bytes=0-3'})
    assert response.status_code==206 and response.data==b'fake'
    media.write_bytes(b'changed')
    with pytest.raises(ValueError):module.create_app(dataset)
