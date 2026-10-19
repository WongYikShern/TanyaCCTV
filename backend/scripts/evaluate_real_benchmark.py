"""Offline-only real CCTV benchmark tooling. This script cannot call Gemini."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tanya.real_benchmark import budget_plan, evaluate_recording, readiness, fingerprint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['check','plan','evaluate'])
    parser.add_argument('--dataset',type=Path,default=Path('evaluation/real_cctv/draft.json'))
    parser.add_argument('--recording',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    dataset=json.loads(args.dataset.read_text(encoding='utf-8'))
    if args.operation=='check':
        ready,blocked=readiness(dataset)
        media=[]
        for clip in dataset['clips']:
            path=Path(clip['path'])
            state='missing' if not path.is_file() else ('verified' if hashlib.sha256(path.read_bytes()).hexdigest()==clip['sha256'] else 'HASH MISMATCH')
            media.append(dict(clip_id=clip['id'],status=state))
        result=dict(dataset_sha256=fingerprint(dataset),ready_cases=list(ready),blocked_cases=blocked,media=media)
    elif args.operation=='plan':
        result=budget_plan(dataset)
    else:
        if not args.recording:parser.error('evaluate requires --recording')
        result=evaluate_recording(dataset,json.loads(args.recording.read_text(encoding='utf-8')))
    rendered=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if args.output:args.output.write_text(rendered,encoding='utf-8')
    else:print(rendered,end='')


if __name__=='__main__':main()
