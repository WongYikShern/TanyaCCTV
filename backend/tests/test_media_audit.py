"""Offline decoded-media integrity tests; not accuracy tests of human event labels."""
import importlib.util
from pathlib import Path

from tests.conftest import make_video

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/audit_caviar_media.py'
spec=importlib.util.spec_from_file_location('audit_media_test',SCRIPT)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def test_identical_decoded_frames_pass_and_wrong_frame_count_fails(tmp_path):
    import cv2
    video=tmp_path/'a.mp4';make_video(video,seconds=2,seed=1)
    cap=cv2.VideoCapture(str(video));n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
    good=audit.compare_decoded(video,video,n,fps)
    assert not good['issues'] and good['worst_frame_mae']==0
    bad=audit.compare_decoded(video,video,n+1,fps)
    assert any('frame count' in e for e in bad['issues'])


def test_wrong_time_mapping_and_different_images_are_reported(tmp_path):
    import cv2
    a=tmp_path/'a.mp4';b=tmp_path/'b.mp4'
    make_video(a,seconds=2,seed=1);make_video(b,seconds=2,seed=2)
    cap=cv2.VideoCapture(str(a));n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
    bad=audit.compare_decoded(a,b,n,fps+1,max_mae=.001)
    assert any('frame rate' in e for e in bad['issues'])
    assert bad['frames_above_threshold']>0


def test_changed_original_stops_before_decode_and_does_not_create_ground_truth(tmp_path,monkeypatch):
    import json
    caviar=tmp_path/'data/cctv_validation/caviar'
    for name in ('originals','videos','annotations'):(caviar/name).mkdir(parents=True)
    original=caviar/'originals/a.mpg';original.write_bytes(b'changed source')
    prepared=caviar/'videos/a.mp4';prepared.write_bytes(b'prepared')
    annotation=caviar/'annotations/a.xml';annotation.write_bytes(b'labels')
    plan=tmp_path/'evaluation/datasets/caviar-small.json';plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps(dict(clips=[dict(name='a',video_sha256='wrong',annotation_sha256=audit.digest(annotation),decoded_frames=25,prepared_fps=25)])),encoding='utf-8')
    clip=dict(video='a.mp4',xml=annotation,video_sha256=audit.digest(prepared),decoded_frames=25,fps=25,duration_sec=1)
    monkeypatch.setattr(audit.real_dataset,'load_clips',lambda *args:[clip])
    def forbidden(*args,**kwargs):raise AssertionError('Changed source must not be decoded or used to build labels')
    monkeypatch.setattr(audit,'compare_decoded',forbidden)
    monkeypatch.setattr(audit.real_dataset,'build',forbidden)
    out=tmp_path/'out';out.mkdir()
    report=audit.audit(tmp_path,out)
    assert report['passed'] is False
    assert 'Original source hash' in report['issues'][0]
    assert not (out/'caviar_ground_truth.json').exists()
    assert original.read_bytes()==b'changed source'
