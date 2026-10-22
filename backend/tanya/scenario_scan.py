"""Bounded visual search across chosen recordings, independent of retrieval rankings."""
import math
import sqlite3

from .indexer import sha256_file
from .sentry_client import SearchError
from .visual_review import MAX_CANDIDATES, MAX_FRAMES, review_results

WINDOW_SEC = 12.0
STRIDE_SEC = 6.0
MAX_WINDOWS = 500


def source_path(settings, video):
    root = settings.video_dir.resolve()
    path = (root / video['rel_path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SearchError('The selected recording is missing or outside the library.')
    try:
        digest = sha256_file(path)
    except OSError:
        raise SearchError('The selected recording is not readable. Check its file permissions.') from None
    if digest != video['sha256']:
        raise SearchError('The recording has changed. Index it again before planning a scan.')
    return path


def build_plan(settings, query, video_id, start=0, end=None):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
        raise ValueError('Describe the scene using 1–500 characters.')
    if type(video_id) is not int:
        raise ValueError('Select one recording to scan.')
    if not settings.db_path.is_file():
        raise ValueError('Upload a recording and extract frames first.')
    with sqlite3.connect(f'{settings.db_path.resolve().as_uri()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM videos WHERE id=? AND status='done'", (video_id,)).fetchone()
        if row is None:
            raise ValueError('The selected recording needs local frame indexing first.')
        video = dict(row)
        duration = video['duration_sec']
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('The recording has no usable duration.')
        end = duration if end is None else end
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end)):
            raise ValueError('Use finite start/end times in seconds.')
        if not 0 <= start < end <= duration:
            raise ValueError(f'Choose a range inside this {duration:.2f}-second recording.')
        count = max(1, math.ceil(max(0, end-start-WINDOW_SEC)/STRIDE_SEC)+1)
        if count > MAX_WINDOWS:
            raise ValueError('Select a time range of 50 minutes or less per scan.')
        source_path(settings, video)
        hits = []
        for i in range(count):
            lo, hi = start+i*STRIDE_SEC, min(end, start+i*STRIDE_SEC+WINDOW_SEC)
            frames = conn.execute('SELECT timestamp_sec,image_path FROM frames WHERE video_id=? '
                                  'AND timestamp_sec BETWEEN ? AND ? ORDER BY timestamp_sec',
                                  (video_id, lo, hi)).fetchall()
            if not frames:
                raise ValueError('Some scan windows have no extracted frames. Index this recording again.')
            thumb = frames[len(frames)//2]
            hits.append(dict(video_id=video_id, filename=video['filename'], rel_path=video['rel_path'],
                             start_sec=lo, end_sec=hi, best_score=None, best_score_above_median=None,
                             chunks=[], status='uncertain', thumbnail=thumb['image_path'],
                             thumbnail_timestamp_sec=thumb['timestamp_sec'], scan_window=i+1))
    return dict(query=query.strip(), video=video, hits=hits, start_sec=start, end_sec=end,
                max_images=len(hits)*MAX_FRAMES, max_calls=math.ceil(len(hits)/MAX_CANDIDATES),
                window_count=len(hits), next_batch=0)


def build_library_plan(settings, query, video_ids=None, start=0, end=None):
    if video_ids is not None and (not isinstance(video_ids, list) or not video_ids
                                  or any(type(i) is not int for i in video_ids)):
        raise ValueError('Choose all recordings or a list of recording IDs.')
    if not settings.db_path.is_file():
        raise ValueError('Upload recordings and extract frames first.')
    with sqlite3.connect(f'{settings.db_path.resolve().as_uri()}?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT id,filename,status FROM videos ORDER BY id').fetchall()
    selected = [r for r in rows if video_ids is None or r[0] in video_ids]
    if video_ids is not None and {r[0] for r in selected} != set(video_ids):
        raise ValueError('One of the selected recordings no longer exists.')
    if len(selected) != 1 and (start != 0 or end is not None):
        raise ValueError('Choose one recording to limit its time range.')
    hits, videos, excluded = [], [], []
    for ident, filename, status in selected:
        try:
            part = build_plan(settings, query, ident, start, end)
        except (ValueError, SearchError) as error:
            excluded.append(dict(filename=filename, reason=str(error)))
            continue
        videos.append(part['video'])
        hits.extend(part['hits'])
    if not hits:
        raise ValueError('No selected recording can be scanned. Extract frames and check the files first.')
    if len(hits) > MAX_WINDOWS:
        raise ValueError('This library exceeds 500 scan windows. Select one recording or a smaller time range.')
    for i, hit in enumerate(hits):
        hit['scan_window'] = i+1
    return dict(query=query.strip(), videos=videos, hits=hits, excluded=excluded,
                max_images=len(hits)*MAX_FRAMES, max_calls=math.ceil(len(hits)/MAX_CANDIDATES),
                window_count=len(hits), next_batch=0)


def public_plan(plan):
    return dict(query=plan['query'], recordings=[dict(video_id=v['id'], filename=v['filename'])
                for v in plan['videos']], excluded=plan['excluded'], windows=plan['window_count'],
                ranges=[dict(video_id=v['id'], start_sec=min(h['start_sec'] for h in plan['hits'] if h['video_id']==v['id']),
                             end_sec=max(h['end_sec'] for h in plan['hits'] if h['video_id']==v['id'])) for v in plan['videos']],
                max_images=plan['max_images'], max_calls=plan['max_calls'],
                note='Checks up to six sampled images per overlapping 12-second window, across the '
                     'selected recordings. No embedding index is needed. Short events can fall between '
                     'samples; long sequences may need manual review. Sends frames and your query '
                     'to Google Gemini using your API account; charges depend on the configured model.')


def run_batch(plan, batch, settings, search_settings, reviewer=None):
    if type(batch) is not int or batch != plan['next_batch'] or batch >= plan['max_calls']:
        raise ValueError('This batch is out of order or already attempted. Review a new plan to retry.')
    selected_ids = {h['video_id'] for h in plan['hits'][batch*MAX_CANDIDATES:(batch+1)*MAX_CANDIDATES]}
    for video in plan['videos']:
        if video['id'] in selected_ids:
            source_path(settings, video)
    # Consume before sending. A timeout must not silently allow the same approved send again.
    plan['next_batch'] += 1
    hits = [dict(h) for h in plan['hits'][batch*MAX_CANDIDATES:(batch+1)*MAX_CANDIDATES]]
    result = dict(query=plan['query'], hits=hits, warnings=[], search_method='direct_visual_scan',
                  note='Visual matches from sampled footage, independent of embedding rankings. '
                       'Window boundaries are scan ranges, not exact event boundaries.')
    result = review_results(result, settings, search_settings, reviewer=reviewer)
    result['warnings'] = ['This scan checks samples throughout the approved range. Missing matches '
                          'do not establish absence. Review evidence images and full context.']
    result['batch'] = batch
    result['completed_windows'] = min((batch+1)*MAX_CANDIDATES, plan['window_count'])
    result['total_windows'] = plan['window_count']
    result['done'] = plan['next_batch'] == plan['max_calls']
    return result
