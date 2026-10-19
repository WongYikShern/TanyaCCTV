"""Local-only human label collection. No Gemini imports or API calls."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import Flask, abort, jsonify, send_file
from tanya.real_benchmark import fingerprint, validate_dataset

ROOT=Path(__file__).resolve().parents[2]


def create_app(dataset_path):
    dataset=json.loads(Path(dataset_path).read_text(encoding='utf-8'))
    validate_dataset(dataset)
    media={}
    for index,clip in enumerate(dataset['clips']):
        path=(ROOT/clip['path']).resolve()
        if not path.is_relative_to(ROOT/'data/cctv_validation'):
            raise ValueError('Review media must be inside data/cctv_validation')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=clip['sha256']:
            raise ValueError(f'Missing or changed media: {clip["id"]}')
        media[index]=path
    app=Flask(__name__,static_folder=None)

    @app.get('/')
    def home():
        return send_file(ROOT/'evaluation/real_cctv/review.html')

    @app.get('/dataset')
    def data():
        # Hide other reviewers' decisions and publisher hints during independent review.
        return jsonify(dataset_sha256=fingerprint(dataset),clips=dataset['clips'],
                       cases=[dict(id=c['id'],query=c['query'],scope=c.get('scope',[v['id'] for v in dataset['clips']])) for c in dataset['cases']])

    @app.get('/media/<int:index>')
    def video(index):
        if index not in media:abort(404)
        return send_file(media[index],conditional=True,mimetype='video/mp4')

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return response
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=ROOT/'evaluation/real_cctv/draft.json')
    parser.add_argument('--port',type=int,default=5012)
    args=parser.parse_args()
    create_app(args.dataset).run(host='127.0.0.1',port=args.port,debug=False)
