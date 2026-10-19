"""Offline, provenance-aware evaluation. No AI clients, paid execution or model training."""
from __future__ import annotations

import hashlib
import json
import math
from statistics import mean

from .evaluation import Case, Event, Window, matches, iou, score_case
from .scenario_scan import WINDOW_SEC, STRIDE_SEC, MAX_FRAMES, MAX_CANDIDATES
from .search_sync import estimate


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def validate_dataset(dataset):
    clips = {c['id']: c for c in dataset['clips']}
    if not clips or len(clips) != len(dataset['clips']):
        raise ValueError('Clip IDs must be nonempty and unique')
    for clip in clips.values():
        if not finite(clip['duration_sec']) or clip['duration_sec'] <= 0 or len(clip['sha256']) != 64:
            raise ValueError('Invalid clip duration or content hash')
    ids = [c['id'] for c in dataset['cases']]
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError('Case IDs must be nonempty and unique')
    for case in dataset['cases']:
        if not isinstance(case['query'],str) or not case['query'].strip():
            raise ValueError('A case has no query')
    return clips


def reviewed_case(case, clips):
    """Two independent full-video reviews, identical resolved labels, for every scoped clip."""
    scope = case.get('scope',list(clips))
    if not scope or len(scope)!=len(set(scope)) or set(scope)-set(clips):
        raise ValueError('Invalid case scope')
    reviews = case.get('clip_reviews',[])
    if len(reviews)!=len(scope) or {r['clip_id'] for r in reviews}!=set(scope):
        raise ValueError('Every scoped clip needs its own review')
    events=[]
    for row in reviews:
        first, second = row.get('review_a'),row.get('review_b')
        if not first or not second:
            raise ValueError('Two human reviews are missing')
        if (not first.get('reviewer') or not second.get('reviewer') or first['reviewer']==second['reviewer']
                or any(r.get('method')!='human_full_video' for r in (first,second))):
            raise ValueError('Need two distinct reviewers who watched the full clip')
        # Review records are declarations by the named reviewers, not authenticated attestations.
        decisions=[]
        for review in (first,second):
            presence=review.get('presence')
            spans=review.get('events',[])
            if presence not in ('present','absent'):
                raise ValueError('Unreviewed/uncertain labels cannot be scored as absent')
            if (presence=='present') != bool(spans):
                raise ValueError('Presence and event intervals disagree')
            normalized=[]
            for event in spans:
                start,end=event.get('start_sec'),event.get('end_sec')
                if not finite(start) or not finite(end) or not 0<=start<end<=clips[row['clip_id']]['duration_sec']:
                    raise ValueError('Label interval is outside its recording')
                normalized.append((start,end))
            decisions.append((presence,sorted(normalized)))
        if decisions[0]!=decisions[1]:
            raise ValueError('Reviewer disagreement needs resolution before scoring')
        events.extend(Event(row['clip_id'],a,b) for a,b in decisions[0][1])
    return Case(case['query'],events,case.get('event_type','unspecified'))


def readiness(dataset):
    clips=validate_dataset(dataset)
    ready,blocked={},[]
    for case in dataset['cases']:
        try:
            ready[case['id']]=reviewed_case(case,clips)
        except ValueError as error:
            blocked.append(dict(case_id=case['id'],reason=str(error)))
    return ready,blocked


def budget_plan(dataset, case_ids=None, clip_ids=None):
    clips=validate_dataset(dataset)
    cases=[c for c in dataset['cases'] if case_ids is None or c['id'] in case_ids]
    if not cases or (case_ids is not None and {c['id'] for c in cases}!=set(case_ids)):
        raise ValueError('Unknown or empty query selection')
    selected=[c for c in clips.values() if clip_ids is None or c['id'] in clip_ids]
    if not selected or (clip_ids is not None and {c['id'] for c in selected}!=set(clip_ids)):
        raise ValueError('Unknown or empty clip selection')
    parts=[]
    for c in selected:
        chunks,frames=estimate(c['duration_sec'])
        windows=max(1,math.ceil(max(0,c['duration_sec']-WINDOW_SEC)/STRIDE_SEC)+1)
        parts.append(dict(clip_id=c['id'],duration_sec=c['duration_sec'],video_sha256=c['sha256'],
                          embedding_chunks=chunks,embedding_billed_frames=frames,scan_windows=windows))
    q=len(cases);windows=sum(p['scan_windows'] for p in parts)
    scan_calls=q*math.ceil(windows/MAX_CANDIDATES);images=q*windows*MAX_FRAMES
    # Date-pinned planning assumptions, not a hard billing cap; no countTokens request is made.
    image_tokens=images*1120
    text_tokens=scan_calls*2000
    output_tokens=scan_calls*4096
    indexing=sum(p['embedding_billed_frames'] for p in parts)*.00079
    scan=(image_tokens+text_tokens)*.75/1_000_000+output_tokens*3.75/1_000_000
    _,blocked=readiness(dataset)
    return dict(operation='PLAN ONLY: no network, indexing or inference',pricing_checked='2026-10-20',
                dataset_sha256=fingerprint(dataset),labels_ready=not blocked,
                clips=parts,queries=[dict(case_id=c['id'],query=c['query']) for c in cases],
                ranked=dict(model='gemini-embedding-2',new_index=True,removals=0,
                            indexing_calls=sum(p['embedding_chunks'] for p in parts),query_calls=q,
                            billed_frames=sum(p['embedding_billed_frames'] for p in parts),
                            indexing_estimate_usd=round(indexing,4),
                            query_estimate_usd=round(sum(len(c['query'].split())*2+4 for c in cases)*.2/1_000_000,6)),
                scene_scan=dict(model='gemini-3.8-flash',thinking_level='low',windows_per_query=windows,
                                max_requests=scan_calls,max_images=images,
                                estimated_input_tokens=image_tokens+text_tokens,
                                max_output_tokens=output_tokens,estimated_cost_usd=round(scan,4)),
                total_estimate_usd=round(indexing+scan+sum(len(c['query'].split())*2+4 for c in cases)*.2/1_000_000,4),
                approval=dict(approved=False,quota_verified=False,budget_usd=None),
                assumptions=['Standard paid-tier rates, no discounts/free tier assumed.',
                             'Embedding overlap bills repeated frames; no still-frame discount assumed.',
                             'Scan: 1120 tokens/image plus 2000 prompt tokens/request and 4096 output tokens/request.',
                             'Image token accounting, prompt size and actual charges may differ; this is not a dollar cap.',
                             'One attempt per approved operation; retries require a separate allowance.',
                             'No data is sent by this planner. Fresh indexing must use an isolated index, never the owner library.'])


def evaluate_recording(dataset,recording):
    clips=validate_dataset(dataset)
    if recording.get('dataset_sha256')!=fingerprint(dataset):
        raise ValueError('Recording does not match this frozen label/dataset version')
    mode=recording.get('mode')
    provenance=recording.get('provenance',{})
    inference=provenance.get('inference')
    if mode not in ('ranked','scene_scan') or inference not in ('live_ai','mock','offline_replay'):
        raise ValueError('Explicit mode and inference provenance are required')
    if inference=='live_ai' and (not provenance.get('model') or not provenance.get('run_id') or not provenance.get('recorded_at')):
        raise ValueError('Live inference needs a model, run ID and timestamp')
    if set(recording.get('indexed_clips',[]))!=set(clips):
        raise ValueError('The benchmark index/scan scope must identify every dataset clip')
    ready,blocked=readiness(dataset)
    known={c['id']:c for c in dataset['cases']}
    entries={}
    for entry in recording.get('queries',[]):
        ident=entry['case_id']
        if ident not in known or ident in entries:
            raise ValueError('Unknown or duplicate query response')
        entries[ident]=entry
    report=dict(mode=mode,inference=inference,metrics_source='live AI recording, scored offline' if inference=='live_ai'
                else 'TEST/REPLAY ONLY — not genuine AI inference',label_blockers=blocked,
                not_measured=[],per_query=[],failures=[],summary={})
    for ident,case in ready.items():
        entry=entries.get(ident)
        if not entry or entry.get('status')!='completed':
            report['not_measured'].append(dict(case_id=ident,reason=entry.get('status','missing') if entry else 'missing'))
            continue
        if mode=='scene_scan' and entry.get('coverage_complete') is not True:
            report['not_measured'].append(dict(case_id=ident,reason='Incomplete or unverified scan coverage'))
            continue
        scope=set(known[ident].get('scope',list(clips)))
        returned=[];unclear=0;rejected=0
        for w in entry.get('windows',[]):
            start,end=w.get('start_sec'),w.get('end_sec');clip=w.get('video')
            if clip not in scope or not finite(start) or not finite(end) or not 0<=start<end<=clips[clip]['duration_sec']:
                raise ValueError('Returned window is outside the evaluated footage')
            if mode=='scene_scan':
                verdict=w.get('verdict')
                if verdict not in ('supported','unclear','not_supported'):
                    raise ValueError('A scene-scan window needs an explicit verdict')
                if verdict!='supported':
                    unclear+=verdict=='unclear';rejected+=verdict=='not_supported';continue
            score=w.get('score',0)
            if not finite(score):raise ValueError('Invalid ranking score')
            returned.append(Window(clip,start,end,score))
        # Scan order is chronological, never a fabricated similarity ranking.
        if mode=='scene_scan':returned.sort(key=lambda w:(w.video,w.start_sec,w.end_sec))
        false=[w for w in returned if not any(matches(w,e) for e in case.events)]
        strict=score_case(case,returned,mode,ks=(5,),min_iou=.5)
        broad=score_case(case,returned,mode,ks=(5,))
        timing=[]
        for event in case.events:
            candidates=[w for w in returned if matches(w,event)]
            best=max(candidates,key=lambda w:iou(w,event),default=None)
            timing.append(dict(event=dict(video=event.video,start_sec=event.start_sec,end_sec=event.end_sec),
                               best_iou=iou(best,event) if best else 0,
                               start_error_sec=abs(best.start_sec-event.start_sec) if best else None,
                               end_error_sec=abs(best.end_sec-event.end_sec) if best else None))
        all_recall=(sum(any(matches(w,e) for w in returned) for e in case.events)/len(case.events)) if case.events else None
        row=dict(case_id=ident,query=case.query,event_type=case.event_type,negative=not case.events,
                 supported_or_ranked_windows=len(returned),unclear_windows=unclear,rejected_windows=rejected,
                 recall_at_5=broad.recall_at.get(5),recall_at_5_iou_05=strict.recall_at.get(5),
                 recall_all=all_recall,false_positive_windows=len(false),negative_has_return=bool(returned) if not case.events else None,
                 timing=timing)
        report['per_query'].append(row)
        if false or (case.events and all_recall<1) or any(t['best_iou']<.5 for t in timing):
            report['failures'].append(dict(case_id=ident,false_positive_windows=[dict(video=w.video,start_sec=w.start_sec,end_sec=w.end_sec) for w in false],
                                           missing_or_poorly_localized=[t for t in timing if t['best_iou']<.5]))
    positives=[q for q in report['per_query'] if not q['negative']]
    negatives=[q for q in report['per_query'] if q['negative']]
    timing=[t for q in positives for t in q['timing'] if t['start_error_sec'] is not None]
    report['summary']=dict(measured_queries=len(report['per_query']),positive_queries=len(positives),negative_queries=len(negatives),
        recall_at_5=mean(q['recall_at_5'] for q in positives) if positives else None,
        recall_at_5_iou_05=mean(q['recall_at_5_iou_05'] for q in positives) if positives else None,
        mean_best_event_iou=mean(t['best_iou'] for q in positives for t in q['timing']) if positives else None,
        mean_start_error_sec=mean(t['start_error_sec'] for t in timing) if timing else None,
        mean_end_error_sec=mean(t['end_error_sec'] for t in timing) if timing else None,
        recall_all=mean(q['recall_all'] for q in positives) if positives else None,
        false_positive_windows=sum(q['false_positive_windows'] for q in report['per_query']),
        negative_query_return_rate=mean(q['negative_has_return'] for q in negatives) if negatives else None)
    report['notes']=['Ranked negatives report unrelated retrievals, not false confirmed detections.',
        'Scan negatives report false supported windows; no absence claim follows from zero supported samples.',
        'Scene-scan Recall@5 uses chronological order; use recall_all for exhaustive scan coverage.',
        'Overlapping windows may duplicate an event; they do not increase event recall.',
        'Missing/error/partial runs and unresolved labels are not silently counted as correct rejections.']
    return report


def merge_reviews(dataset, first, second):
    """Attach independent review exports; disagreements stay blocked, never auto-resolved."""
    from copy import deepcopy
    validate_dataset(dataset)
    expected=fingerprint(dataset)
    names=[r.get('reviewer','').strip() for r in (first,second)]
    if not all(names) or names[0].casefold()==names[1].casefold():
        raise ValueError('Two different human reviewers are required')
    result=deepcopy(dataset)
    known={(c['id'],r['clip_id']) for c in dataset['cases'] for r in c['clip_reviews']}
    for export,name,slot in zip((first,second),names,('review_a','review_b')):
        if export.get('dataset_sha256')!=expected or export.get('method')!='human_full_video':
            raise ValueError('Review export has a different dataset or review method')
        decisions={}
        for decision in export.get('decisions',[]):
            pair=(decision.get('case_id'),decision.get('clip_id'))
            if pair not in known or pair in decisions:
                raise ValueError('Review has an unknown or duplicate clip/query decision')
            presence=decision.get('presence')
            if presence not in ('present','absent','uncertain'):
                raise ValueError('Invalid review presence')
            if presence!='uncertain' and decision.get('full_video_watched') is not True:
                raise ValueError('Final decisions require full-video review')
            decisions[pair]=dict(reviewer=name,method='human_full_video',presence=presence,
                                 events=decision.get('events',[]),notes=decision.get('notes',''),
                                 recorded_at=decision.get('recorded_at'))
        for case in result['cases']:
            for row in case['clip_reviews']:
                row[slot]=decisions.get((case['id'],row['clip_id']))
    return result
