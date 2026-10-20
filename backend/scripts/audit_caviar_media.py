"""Offline audit of original/prepared CAVIAR frames; write a separate local dataset.

No downloads, AI calls, reviewer decisions or shared-file rewrites. Full decoded frame-order
comparison checks preparation, not whether publisher event labels are semantically correct.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from tanya import real_dataset


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def compare_decoded(original,prepared,expected_frames,expected_fps=25.0,max_mae=15.0):
    import cv2
    import numpy as np
    source=cv2.VideoCapture(str(original));copy=cv2.VideoCapture(str(prepared))
    if not source.isOpened() or not copy.isOpened():
        source.release();copy.release();raise ValueError('Could not decode original/prepared media')
    fps=copy.get(cv2.CAP_PROP_FPS);count=0;errors=[];total=0.0;worst=0.0;bad=0
    try:
        while True:
            a,x=source.read();b,y=copy.read()
            if not a and not b:break
            if a!=b:
                errors.append('Original and prepared decoded frame counts differ');break
            if x.shape!=y.shape:
                errors.append('Original and prepared frame dimensions differ');break
            mae=float(np.mean(cv2.absdiff(x,y)))
            total+=mae;worst=max(worst,mae);bad+=mae>max_mae;count+=1
    finally:
        source.release();copy.release()
    if count!=expected_frames:errors.append('Decoded frame count differs from the pinned publisher plan')
    if not math.isfinite(fps) or abs(fps-expected_fps)>.001:errors.append('Prepared frame rate differs from label time mapping')
    if bad:errors.append('Some corresponding decoded frames exceed the pixel-difference threshold')
    return dict(frames_compared=count,expected_frames=expected_frames,prepared_fps=fps,
                label_time_mapping='frame index / 25 fps; intervals end-exclusive',
                mean_absolute_pixel_error=round(total/count,4) if count else None,
                worst_frame_mae=round(worst,4),max_allowed_frame_mae=max_mae,
                frames_above_threshold=bad,issues=errors)


def audit(root,out):
    caviar=root/'data/cctv_validation/caviar'
    plan_path=root/'evaluation/datasets/caviar-small.json'
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    clips=real_dataset.load_clips(caviar,plan_path)
    report=dict(operation='offline original/prepared media audit; no AI inference',
                plan_sha256=digest(plan_path),clips=[],issues=[],human_label_verification=False)
    plans={c['name']+'.mp4':c for c in plan['clips']}
    for clip in clips:
        spec=plans[clip['video']];name=Path(clip['video']).stem
        original=caviar/'originals'/f'{name}.mpg';prepared=caviar/'videos'/clip['video'];annotation=clip['xml']
        hashes=dict(original=digest(original),prepared=digest(prepared),annotation=digest(annotation))
        issues=[]
        if hashes['original']!=spec['video_sha256']:issues.append('Original source hash differs from pinned publisher plan')
        if hashes['annotation']!=spec['annotation_sha256']:issues.append('Publisher annotation hash mismatch')
        if hashes['prepared']!=clip['video_sha256']:issues.append('Prepared file differs from local media manifest')
        if (clip['decoded_frames'] != spec['decoded_frames'] or
                abs(clip['fps']-spec['prepared_fps'])>.001 or
                abs(clip['duration_sec']-spec['decoded_frames']/spec['prepared_fps'])>.001):
            issues.append('Local manifest frame count/fps/duration differs from the pinned preparation plan')
        comparison=None
        if not issues:
            comparison=compare_decoded(original,prepared,spec['decoded_frames'],spec['prepared_fps'])
            issues+=comparison['issues']
        report['clips'].append(dict(video=clip['video'],sha256=hashes,comparison=comparison,issues=issues))
        report['issues'] += [clip['video']+': '+issue for issue in issues]
    report['passed']=not report['issues']
    # Do not apply or invent human reviews: this remains publisher-label-only.
    if report['passed']:
        built=real_dataset.build(clips)
        problems=real_dataset.validate_manifest_rows(built['rows'],{c['video']:c['duration_sec'] for c in clips})
        if problems:raise ValueError('; '.join(problems))
        real_dataset.write_outputs(clips,built,out,None,truth_path=out/'caviar_ground_truth.json')
    (out/'media-audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='New directory under ignored data/cctv_validation')
    args=parser.parse_args()
    path=args.out.resolve()
    if not path.is_relative_to((ROOT/'data/cctv_validation').resolve()) or path.exists():
        parser.error('Choose a new directory under ignored data/cctv_validation; existing outputs are preserved')
    path.mkdir(parents=True)
    try:report=audit(ROOT,path)
    except (OSError,ValueError,KeyError) as error:
        print(f'Audit failed: {error}',file=sys.stderr);return 1
    print(json.dumps(dict(passed=report['passed'],clips=len(report['clips']),issues=report['issues'],
                          human_label_verification=False,output=str(path)),indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
