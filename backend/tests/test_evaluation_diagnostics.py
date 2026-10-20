"""Offline regression tests. Fixtures are invented, never genuine inference results."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from tanya import benchmark

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/yolo'))
import analyse_cached as cached


def test_individual_miss_is_reported_when_query_has_one_hit():
    q=benchmark.Query('two events','direct','test',[benchmark.Span('a',0,2),benchmark.Span('a',10,12)])
    run=dict(mode='ranked',source='mock',engine='fixture',responses={'two events':dict(status='ok',windows=[dict(video='a',start_sec=0,end_sec=3)])})
    result=benchmark.score_mode([q],run,'ranked')
    assert result.metrics['no_hit_query_rate']==0
    assert result.metrics['missed_individual_event_rate']==.5
    assert result.metrics['missed_events']==1
    assert result.metrics['matched_start_error_sec_mean']==0
    assert result.metrics['matched_end_error_sec_mean']==1
    assert result.per_query[0]['event_timing'][1]['start_error_sec'] is None


def test_duplicate_windows_do_not_reduce_misses_and_scan_uses_all_windows():
    q=benchmark.Query('event','direct','test',[benchmark.Span('a',40,42)])
    windows=[dict(video='a',start_sec=i,end_sec=i+1,verdict='supported') for i in range(6)]
    windows += [dict(video='a',start_sec=40,end_sec=42,verdict='supported')]*2
    run=dict(mode='scan',source='mock',engine='fixture',responses={'event':dict(status='ok',windows=windows)})
    result=benchmark.score_mode([q],run,'scan')
    assert result.metrics['recall@5']==0
    assert result.metrics['event_recall']==1
    assert result.metrics['missed_events']==0
    assert result.metrics['false_positive_windows']==6


def test_explicit_mock_scan_source_and_legacy_replay():
    assert benchmark.scan_run_from_results({},'test',source='mock')['source']=='mock'
    with pytest.raises(ValueError):benchmark.scan_run_from_results({},'test',source='invented')


def test_region_filter_counts_real_people_as_missed_not_removed_ground_truth():
    from caviar_yolo import detection_summary
    gt={0:[(0,0,10,20)]};raw={0:[(0,0,10,20,.9),(50,50,60,60,.8)]}
    filtered=cached.filter_regions(raw,[[0,0,20,30]])
    baseline=detection_summary(raw,gt,.25);candidate=detection_summary(filtered,gt,.25)
    assert baseline['tp']==1 and candidate['fn']==1 and candidate['fp']==1
    assert raw[0][0][-1]==.9   # original cache preserved
    with pytest.raises(ValueError):cached.filter_regions(raw,[[0,0,float('nan'),3]])


def test_cache_missing_frame_is_not_an_empty_detection(tmp_path):
    path=tmp_path/'cache.json'
    path.write_text(json.dumps([dict(frame=0,boxes=[])]),encoding='utf-8')
    with pytest.raises(ValueError,match='Incomplete'):cached.read_detections(path,2,.1)
    path.write_text(json.dumps([dict(frame=0,boxes=[])]*2),encoding='utf-8')
    with pytest.raises(ValueError,match='Duplicate'):cached.read_detections(path,1,.1)


def test_cache_threshold_sweep_reuses_input_without_inference(tmp_path):
    run_dir=tmp_path/'run';run_dir.mkdir();annotations=tmp_path/'labels';annotations.mkdir()
    meta=dict(environment=dict(conf_recorded=.1),totals=dict(videos_failed=0),errors=[],clips=[dict(video='a.mp4',frames=1,skipped_frames=0)])
    (run_dir/'results.json').write_text(json.dumps(meta),encoding='utf-8')
    (run_dir/'a_detections.json').write_text(json.dumps([dict(frame=0,boxes=[[0,0,10,20,.2]])]),encoding='utf-8')
    (annotations/'a.xml').write_text('<dataset><frame number="0"><objectlist><object id="0"><box xc="5" yc="10" w="10" h="20"/></object></objectlist></frame></dataset>',encoding='utf-8')
    report=cached.analyse(run_dir,annotations,[.1,.25])
    assert report['fresh_inference'] is False
    assert report['overall'][0]['baseline']['recall']==1
    assert report['overall'][1]['baseline']['recall']==0
    assert len(report['input_sha256'])==2
    with pytest.raises(ValueError,match='Thresholds'):cached.analyse(run_dir,annotations,[.05])


@pytest.mark.parametrize('start,end',[(-1,2),(0,float('inf')),(float('nan'),2)])
def test_invalid_timestamps_cannot_be_scored(start,end):
    q=benchmark.Query('q','direct','test',[benchmark.Span('a',0,2)])
    run=dict(mode='ranked',source='mock',responses={'q':dict(status='ok',windows=[dict(video='a',start_sec=start,end_sec=end)])})
    with pytest.raises(ValueError,match='invalid returned'):benchmark.score_mode([q],run,'ranked')


def test_evidence_cannot_claim_time_outside_its_scanned_window():
    q=benchmark.Query('q','direct','test',[benchmark.Span('a',0,2)])
    run=dict(mode='scan',source='mock',responses={'q':dict(status='ok',windows=[dict(video='a',start_sec=10,end_sec=20,verdict='supported',evidence_start_sec=0,evidence_end_sec=2)])})
    with pytest.raises(ValueError,match='inside'):benchmark.score_mode([q],run,'scan',use_evidence_span=True)


def test_contract_changes_with_labels_and_footage_but_not_json_key_order():
    truth={'cases':[{'query':'q','events':[]}]}
    clips=[dict(video='a.mp4',video_sha256='a'*64,duration_sec=10)]
    contract=benchmark.dataset_contract(truth,clips)
    assert benchmark.check_run_contract(dict(dataset_contract=contract),contract).startswith('matching')
    changed=benchmark.dataset_contract({'cases':[{'events':[],'query':'other'}]},clips)
    with pytest.raises(ValueError,match='does not match'):
        benchmark.check_run_contract(dict(dataset_contract=changed),contract)
    changed=benchmark.dataset_contract(truth,[dict(clips[0],video_sha256='b'*64)])
    assert changed!=contract
    assert 'UNBOUND' in benchmark.check_run_contract({},contract)
    with pytest.raises(ValueError,match='no dataset contract'):
        benchmark.check_run_contract({},contract,required=True)


def test_failure_cases_include_misses_bad_timing_and_failed_queries():
    queries=[benchmark.Query('q','direct','test',[benchmark.Span('a',0,1)]),benchmark.Query('neg','negative','test',[])]
    run=dict(source='mock',responses={'q':dict(status='ok',windows=[dict(video='a',start_sec=0,end_sec=10)]),'neg':dict(status='failed')})
    result=benchmark.score_mode(queries,run,'ranked')
    assert [q['query'] for q in result.failure_cases]==['q','neg']
    assert result.failure_cases[0]['event_timing'][0]['best_iou']==.1


def test_split_breakdowns_keep_unavailable_queries_out_of_scores():
    queries=[benchmark.Query('dev','direct','dev',[benchmark.Span('a',0,2)]),
             benchmark.Query('test','paraphrase','test',[benchmark.Span('a',10,12)]),
             benchmark.Query('missing','negative','test',[])]
    run=dict(source='mock',responses={
        'dev':dict(status='ok',windows=[dict(video='a',start_sec=0,end_sec=2)]),
        'test':dict(status='ok',windows=[])})
    result=benchmark.score_mode(queries,run,'ranked')
    assert result.breakdowns['split']['dev']['recall_at_5']==1
    test=result.breakdowns['split']['test']
    assert test['recall_at_5']==0 and test['unavailable']==1
    assert test['negative_false_positive_rate'] is None
    assert result.breakdowns['kind']['negative']['answered']==0


@pytest.mark.parametrize('verdict',[None,'unknown','Supported'])
def test_malformed_visual_review_cannot_become_a_correct_negative(verdict):
    query=benchmark.Query('negative','negative','test',[])
    run=dict(source='mock',responses={'negative':dict(status='ok',windows=[dict(video='a',start_sec=0,end_sec=2,verdict=verdict)])})
    with pytest.raises(ValueError,match='explicit'):benchmark.score_mode([query],run,'scan')


@pytest.mark.parametrize('latency',[-1,float('inf'),float('nan')])
def test_invalid_latency_rejected(latency):
    query=benchmark.Query('negative','negative','test',[])
    run=dict(source='mock',responses={'negative':dict(status='ok',latency_sec=latency,windows=[])})
    with pytest.raises(ValueError,match='latency'):benchmark.score_mode([query],run,'ranked')
