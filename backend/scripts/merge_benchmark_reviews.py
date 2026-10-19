"""Combine two independent exports; unresolved or missing labels remain blocked."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tanya.real_benchmark import merge_reviews, readiness

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first',type=Path)
    parser.add_argument('second',type=Path)
    parser.add_argument('--dataset',type=Path,default=Path('evaluation/real_cctv/draft.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output already exists; choose a new filename to preserve reviews')
    load=lambda path:json.loads(path.read_text(encoding='utf-8'))
    result=merge_reviews(load(args.dataset),load(args.first),load(args.second))
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    ready,blocked=readiness(result)
    print(json.dumps(dict(ready_cases=list(ready),blocked_cases=blocked),indent=2))
