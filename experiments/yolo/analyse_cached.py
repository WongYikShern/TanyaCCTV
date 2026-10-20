"""Offline sensitivity analysis of saved YOLO detections. No model loading or inference.

Reuses results.json and *_detections.json from caviar_yolo.py. Ground truth stays unchanged
when regions remove detections, so hiding a real person is counted as a missed detection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from caviar_yolo import CAVIAR, NetworkGuard, detection_summary, publisher_boxes


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def rectangle(value):
    if (not isinstance(value,list) or len(value)!=4 or not all(finite(v) for v in value)
            or not 0<=value[0]<value[2] or not 0<=value[1]<value[3]):
        raise ValueError('Region must be [left, top, right, bottom] in original-frame pixels')
    return value


def filter_regions(per_frame, regions):
    """Exclude boxes whose centre falls inside a configured static region (half-open edges)."""
    regions=[rectangle(r) for r in regions]
    return {f:[d for d in ds if not any(a<=(d[0]+d[2])/2<c and b<=(d[1]+d[3])/2<e
                                        for a,b,c,e in regions)] for f,ds in per_frame.items()}


def read_detections(path, frames, min_conf):
    rows=json.loads(path.read_text(encoding='utf-8'));out={}
    for row in rows:
        frame=row['frame']
        if type(frame) is not int or not 0<=frame<frames or frame in out:
            raise ValueError('Duplicate or out-of-bounds cached frame')
        boxes=row['boxes']
        for d in boxes:
            if (len(d)!=5 or not all(finite(v) for v in d) or not d[0]<d[2] or not d[1]<d[3]
                    or not min_conf-.001<=d[4]<=1):
                raise ValueError('Malformed cached detection')
        out[frame]=boxes
    if set(out)!=set(range(frames)):
        raise ValueError('Incomplete cached frames; missing frames cannot be counted as empty detections')
    return out


def analyse(run_dir, annotation_dir, thresholds=(.10,.25,.40,.50,.70), regions=None):
    metadata_path=run_dir/'results.json'
    metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
    floor=metadata['environment']['conf_recorded']
    if (not finite(floor) or not thresholds or
            any(not finite(t) or not floor<=t<=1 for t in thresholds)):
        raise ValueError('Thresholds must be within [recorded minimum confidence, 1]; lower detections were not saved')
    if metadata.get('errors') or metadata['totals']['videos_failed']:
        raise ValueError('Source inference had failures; obtain a complete run before comparing settings')
    regions=regions or {}
    names=[c['video'] for c in metadata['clips']]
    if len(names)!=len(set(names)) or set(regions)-set(names):
        raise ValueError('Duplicate source clip or unknown region-filter clip')
    clips=[];hashes={};all_gt={};all_raw={};all_filtered={}
    for clip in metadata['clips']:
        name=clip['video']
        if Path(name).name!=name or Path(name).suffix!='.mp4':raise ValueError('Invalid clip filename')
        n=clip['frames']
        if type(n) is not int or n<=0 or clip.get('skipped_frames') not in (None,0):
            raise ValueError('Incomplete source clip')
        detection_path=run_dir/f'{Path(name).stem}_detections.json'
        annotation_path=annotation_dir/f'{Path(name).stem}.xml'
        raw=read_detections(detection_path,n,floor)
        gt=publisher_boxes(annotation_path)
        if not gt or max(gt)>=n:raise ValueError('Source run does not cover publisher-labelled frames')
        filtered=filter_regions(raw,regions.get(name,[]))
        for path in (detection_path,annotation_path):hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        rows=[]
        for threshold in thresholds:
            baseline=detection_summary(raw,gt,threshold);candidate=detection_summary(filtered,gt,threshold)
            rows.append(dict(conf=threshold,baseline=baseline,region_filtered=candidate,
                             detections_removed=baseline['tp']+baseline['fp']-candidate['tp']-candidate['fp'],
                             additional_missed_boxes=candidate['fn']-baseline['fn']))
        clips.append(dict(video=name,frames=n,labelled_frames=len(gt),thresholds=rows))
        all_gt.update({(name,f):b for f,b in gt.items()})
        all_raw.update({(name,f):b for f,b in raw.items()})
        all_filtered.update({(name,f):b for f,b in filtered.items()})
    if not clips:raise ValueError('No source clips')
    return dict(source='cached_detection_replay',fresh_inference=False,
                source_report_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),input_sha256=hashes,
                source_environment=metadata['environment'],region_policy=regions,
                clips=clips,overall=[dict(conf=t,baseline=detection_summary(all_raw,all_gt,t),
                                          region_filtered=detection_summary(all_filtered,all_gt,t)) for t in thresholds],
                limitations=['No new inference; cannot recover boxes below the recorded confidence floor.',
                             'No speed comparison is inferred from cached detections.',
                             'Ground truth is not masked: excluding real people reduces recall.',
                             'Publisher annotations are incomplete; unmatched boxes need human inspection.',
                             'Tune thresholds/regions on development footage; evaluate on separate held-out footage.',
                             'This measures person boxes, not entering, leaving or falls.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--annotations',type=Path,default=CAVIAR/'annotations')
    parser.add_argument('--thresholds',type=float,nargs='+',default=[.10,.25,.40,.50,.70])
    parser.add_argument('--regions',type=Path,help='JSON mapping clip filename to excluded rectangles')
    parser.add_argument('--out',type=Path,required=True,help='New local JSON file outside the repo or under ignored data/cctv_validation')
    args=parser.parse_args()
    allowed=(CAVIAR.parent).resolve()
    destination=args.out.resolve()
    project=Path(__file__).resolve().parents[2]
    if ('onedrive' in str(destination).lower() or args.out.exists() or
            (destination.is_relative_to(project) and not destination.is_relative_to(allowed))):
        parser.error('Choose a new local file outside OneDrive, outside the repo or under ignored data/cctv_validation; never overwrite results')
    with NetworkGuard() as guard:
        regions=json.loads(args.regions.read_text(encoding='utf-8')) if args.regions else None
        report=analyse(args.run_dir,args.annotations,args.thresholds,regions)
        report['network_attempts_blocked']=len(guard.attempts)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'Saved offline cached-detection analysis: {args.out}')
