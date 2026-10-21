"""Local-only dashboard and API around the existing indexer and search bridge."""
from dataclasses import asdict
from pathlib import Path
import os
import secrets
import sqlite3
import threading
import time
import uuid
import hashlib
import json
import math

from flask import Flask, abort, jsonify, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from .config import SUPPORTED_EXTENSIONS, SEARCHABLE_EXTENSIONS, load_settings, load_search_settings
from .indexer import Indexer, scan_video_dir, sha256_file
from . import playback
from . import person_detection
from .search import search_videos
from .sentry_client import SearchError, redact
from . import sentry_client
from .search_sync import build_plan, load_manifest, apply_plan, sentry_cli_command
from . import scenario_scan
from .visual_review import review_results
from . import feedback
from . import case_report
from .investigations import (InvestigationError, NotFound, Store, StoreUnavailable, resolve_sources,
                             timeline, verify_sources)


def safe_upload_name(original):
    """Sanitised upload name with an allowed video extension, or None if the type is not allowed.

    secure_filename() drops non-ASCII characters, so "监控录像.mp4" becomes "mp4" and would lose its
    extension. The extension is therefore validated on the original name (basename only), and a
    generic "video<ext>" name is used when sanitising leaves no usable name.
    """
    base = (original or "").replace("\\", "/").rsplit("/", 1)[-1].strip().rstrip(".")
    extension = Path(base).suffix.lower()
    if not Path(base).stem or extension not in SUPPORTED_EXTENSIONS:
        return None
    name = secure_filename(base)
    if Path(name).suffix.lower() != extension or not Path(name).stem:
        name = "video" + extension
    return name


def create_app(settings=None, search_settings=None, *, offline_search=None):
    settings = settings or load_settings()
    search_settings = search_settings or load_search_settings()
    app = Flask(__name__)
    # Do not normalize double-slash media paths from invalid absolute DB references.
    app.url_map.merge_slashes = False
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=512 * 1024 * 1024,
                      SESSION_COOKIE_SAMESITE="Strict")
    lock = threading.Lock()
    scan_jobs = {}
    # Identifies this website process, so an open page can tell that the server was restarted (possibly with a
    # different library, where the same video id names other footage) instead of mixing old and new state.
    instance = secrets.token_hex(8)
    # "replay" (recorded ranked results) or "event_index" (preset annotated events); None = normal app.
    demo_mode = getattr(offline_search, "mode", "replay") if offline_search is not None else None
    yolo = person_detection.load_config()   # optional; nothing runs until a user asks for one video
    settings.video_dir.mkdir(parents=True, exist_ok=True)

    def rows(sql, params=()):
        if not settings.db_path.exists():
            return []
        conn = sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def media_path(root, rel):
        path = (root / rel).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            abort(404)
        return path

    def feedback_path():
        return settings.db_path.with_name("search_feedback.db")

    store = Store(settings.db_path.with_name("investigations.db"))

    def search_run_settings(visual_check):
        return {"chunks_requested": 10, "merge_ratio": search_settings.merge_ratio,
                "merge_gap_sec": search_settings.merge_gap_sec, "visual_check": visual_check,
                "engine": "SentrySearch d3efd6a (Gemini Embedding 2), 10 s chunks / 2 s overlap"}

    def search_state(video, manifest):
        if video["status"] != "done":
            return "local_index_needed"
        if Path(video["rel_path"]).suffix.lower() not in SEARCHABLE_EXTENSIONS:
            return "unsupported"
        source = os.path.abspath(settings.video_dir / video["rel_path"])
        if manifest.get(source, {}).get("sha256") == video["sha256"]:
            return "prepared"
        return "needs_preparation"

    def search_coverage():
        manifest = load_manifest(settings)
        videos = rows("SELECT * FROM videos ORDER BY id DESC")
        return {state: [v["filename"] for v in videos if search_state(v, manifest) == state]
                for state in ("prepared", "needs_preparation", "unsupported", "local_index_needed")}

    @app.before_request
    def local_requests_only():
        if offline_search is not None and request.path in {"/api/search/plan", "/api/search/sync"}:
            abort(403, description="AI preparation is disabled in the offline replay demo.")
        # Reject DNS rebinding and cross-site mutation requests, even on localhost.
        if request.host not in {"localhost:5001", "127.0.0.1:5001", "localhost", "127.0.0.1"}:
            abort(403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):  # every state-changing method needs the token
            token = session.get("csrf")
            if not token or not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), token):
                abort(403, description="Refresh the page before trying again.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-TanyaCCTV-Instance"] = instance
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(InvestigationError)
    def investigation_error(error):
        return jsonify(error=str(error)), 404 if isinstance(error, NotFound) else 400

    @app.errorhandler(StoreUnavailable)
    def store_unavailable(error):
        return jsonify(error=str(error)), 503

    @app.get("/")
    def home():
        session.setdefault("csrf", secrets.token_hex(32))
        return render_template("dashboard.html", csrf=session["csrf"], instance=instance,
                               offline_demo=offline_search is not None, demo_mode=demo_mode)

    @app.get("/api/status")
    def status():
        engine = bool(search_settings.sentry_python and search_settings.sentry_python.is_file()
                      and search_settings.bridge_path.is_file())
        if engine:
            try:
                sentry_cli_command(search_settings)
            except SearchError:
                engine = False
        key = bool(os.environ.get("GEMINI_API_KEY"))
        return jsonify(offline_demo=offline_search is not None, demo_mode=demo_mode, engine_ready=engine, key_ready=key,
                       yolo_ready=yolo.available,
                       search_ready=(offline_search is not None) or (engine and key),
                       scan_ready=bool(key and search_settings.sentry_python and search_settings.sentry_python.is_file()
                                       and offline_search is None),
                       busy=lock.locked(), max_upload_mb=512, coverage=search_coverage())

    playback_dir = settings.db_path.with_name("playback")

    def source_path(video):
        """The original recording's path, or None if it is missing or outside the video folder."""
        root = settings.video_dir.resolve()
        path = (root / video["rel_path"]).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None

    def playback_info(video):
        """How the browser can play this recording. Never modifies anything."""
        source = source_path(video)
        if source is None:
            return {"status": "missing", "url": None, "codec": None, "codec_name": None,
                    "message": "The original file is no longer in the video folder. Restore it, or re-index "
                               "to update the library."}
        code = playback.codec_of(source)
        info = {"codec": code, "codec_name": playback.codec_name(code), "changed": False, "changed_message": None}
        # Cheap integrity hint (no hashing on every page view): the size recorded at indexing no longer matches.
        if video.get("size_bytes") is not None and source.stat().st_size != video["size_bytes"]:
            info.update(changed=True, changed_message=("This file has changed since it was indexed (its size differs), so it may not be the footage "
                       "the frames, search results and evidence refer to. Re-index it before relying on it; "
                       "report exports re-check every source's content hash."))
        if playback.browser_playable(source, code):
            return dict(info, status="playable", url=url_for("video_file", video_id=video["id"]), message=None)
        if playback.copy_path(playback_dir, video["sha256"]).is_file():
            return dict(info, status="copy_ready", url=url_for("playback_file", video_id=video["id"]),
                        message=f"Playing a browser copy; the original uses {info['codec_name']}.")
        container = source.suffix.lower()
        reason = (f"{container.upper().lstrip('.')} files" if container not in playback.BROWSER_CONTAINERS
                  else f"{info['codec_name']} video")
        return dict(info, status="needs_copy", url=None,
                    message=f"Browsers cannot play {reason}. A browser-playable copy can be made on this "
                            "computer (the original is not changed).")

    @app.get("/api/videos")
    def videos():
        result = rows("SELECT * FROM videos ORDER BY id DESC")
        manifest = load_manifest(settings)
        for video in result:
            video["search_state"] = search_state(video, manifest)
            frame = rows("SELECT image_path FROM frames WHERE video_id=? ORDER BY timestamp_sec LIMIT 1",
                         (video["id"],))
            video["thumbnail_url"] = url_for("frame_file", rel=frame[0]["image_path"]) if frame else None
            video["video_url"] = url_for("video_file", video_id=video["id"])
            video["playback"] = playback_info(video)
        # Files already in the video folder but not yet indexed would otherwise be invisible.
        known = {v["rel_path"] for v in result}
        waiting, unsupported = [], []
        try:
            supported, other, _outside = scan_video_dir(settings.video_dir)
            root = settings.video_dir.resolve()
            waiting = [p.relative_to(root).as_posix() for p in supported if p.relative_to(root).as_posix() not in known]
            unsupported = [p.relative_to(root).as_posix() for p in other]
        except (OSError, ValueError):
            pass
        return jsonify(videos=result, waiting_files=waiting, unsupported_files=unsupported)

    @app.get("/api/videos/<int:video_id>/playback")
    def video_playback(video_id):
        video = rows("SELECT id, sha256, rel_path, filename, duration_sec, size_bytes FROM videos WHERE id=?", (video_id,))
        if not video:
            abort(404, description="This video is no longer in the library.")
        info = playback_info(video[0])
        if info["status"] == "needs_copy":
            info["ffmpeg_available"] = playback.find_ffmpeg(search_settings.sentry_python) is not None
        return jsonify(info)

    @app.post("/api/videos/<int:video_id>/playback-copy")
    def make_playback_copy(video_id):
        video = rows("SELECT id, sha256, rel_path, filename, duration_sec, size_bytes FROM videos WHERE id=?", (video_id,))
        if not video:
            abort(404, description="This video is no longer in the library.")
        video = video[0]
        info = playback_info(video)
        if info["status"] != "needs_copy":
            return jsonify(info)
        ffmpeg = playback.find_ffmpeg(search_settings.sentry_python)
        if not ffmpeg:
            abort(503, description="FFmpeg was not found, so a browser copy cannot be made. Install FFmpeg (or set "
                                   "TANYA_FFMPEG / TANYA_SENTRY_PYTHON), or convert the video to H.264 MP4. The "
                                   "extracted frames below can still be reviewed.")
        if not lock.acquire(blocking=False):
            abort(409, description="Another operation is running. Try again when it finishes.")
        try:
            playback.make_copy(source_path(video), playback.copy_path(playback_dir, video["sha256"]), ffmpeg,
                               video["duration_sec"])
        except playback.PlaybackError as error:
            return jsonify(error=str(error)), 500
        finally:
            lock.release()
        return jsonify(playback_info(video))

    @app.get("/api/videos/<int:video_id>/frames")
    def frames(video_id):
        if not rows("SELECT id FROM videos WHERE id=?", (video_id,)):
            abort(404)
        # Page large recordings instead of returning an unbounded image gallery.
        page = request.args.get("page", 0, type=int)
        if page is None or page < 0:
            abort(400)
        result = rows("SELECT timestamp_sec,image_path FROM frames WHERE video_id=? "
                      "ORDER BY timestamp_sec LIMIT 61 OFFSET ?", (video_id, page * 60))
        for frame in result:
            frame["url"] = url_for("frame_file", rel=frame["image_path"])
        return jsonify(frames=result[:60], has_more=len(result) > 60)

    @app.get("/api/videos/<int:video_id>/people")
    def people(video_id):
        """Cached YOLO person-presence candidates for this exact video (never runs the detector)."""
        video = rows("SELECT id, sha256 FROM videos WHERE id=? AND status='done'", (video_id,))
        if not video:
            abort(404, description="This video is no longer in the library.")
        return jsonify(available=yolo.available, reason=yolo.reason(),
                       result=person_detection.load_cached(settings, video[0]["sha256"], yolo))

    @app.post("/api/videos/<int:video_id>/people")
    def find_people(video_id):
        """Run local YOLO person detection on this one video, in the separate YOLO environment."""
        video = rows("SELECT id, sha256, rel_path, filename, duration_sec FROM videos WHERE id=? AND status='done'",
                     (video_id,))
        if not video:
            abort(404, description="This video is no longer in the library.")
        if not yolo.available:
            abort(503, description=yolo.reason())
        source = source_path(video[0])
        if source is None:
            abort(404, description="The original file is no longer in the video folder.")
        if sha256_file(source) != video[0]["sha256"]:
            abort(409, description="This file has changed since it was indexed. Re-index it first.")
        if not lock.acquire(blocking=False):   # one GPU job at a time (4 GB laptop GPU)
            abort(409, description="Another operation is running. Try again when it finishes.")
        try:
            result = person_detection.run(settings, source, video[0]["sha256"], video[0]["duration_sec"], yolo)
        except person_detection.PersonDetectionError as error:
            return jsonify(error=str(error)), 500
        finally:
            lock.release()
        return jsonify(available=True, reason=None, result=result)

    @app.get("/media/frames/<path:rel>")
    def frame_file(rel):
        if Path(rel).suffix.lower() != ".jpg":
            abort(404)
        return send_file(media_path(settings.frames_dir, rel), conditional=True)

    @app.get("/media/videos/<int:video_id>")
    def video_file(video_id):
        video = rows("SELECT rel_path FROM videos WHERE id=?", (video_id,))
        if not video:
            abort(404)
        return send_file(media_path(settings.video_dir, video[0]["rel_path"]), conditional=True)

    @app.get("/media/playback/<int:video_id>")
    def playback_file(video_id):
        video = rows("SELECT sha256 FROM videos WHERE id=?", (video_id,))
        if not video:
            abort(404)
        return send_file(media_path(playback_dir, f"{video[0]['sha256']}.mp4"), conditional=True,
                         mimetype="video/mp4")

    @app.post("/api/upload")
    def upload():
        if request.form.get("authorized") != "yes":
            abort(400, description="Confirm you have permission to use this footage.")
        file = request.files.get("video")
        name = safe_upload_name(file.filename if file else "")
        if name is None:
            abort(400, description="Choose an MP4, MOV, AVI, MKV or M4V video.")
        if not lock.acquire(blocking=False):
            abort(409, description="Indexing is running. Please try again when it finishes.")
        try:
            # Unique names prevent replacement of any existing original footage.
            target = settings.video_dir / f"{uuid.uuid4().hex[:12]}_{name}"
            try:
                with target.open("xb") as destination:
                    file.save(destination)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            # Identical footage already in the library: discard only the copy written by this
            # request (never an existing file) and say which video it matches.
            same = rows("SELECT filename FROM videos WHERE sha256 = ? AND status = 'done'",
                        (sha256_file(target),))
            if same:
                target.unlink(missing_ok=True)
                return jsonify(filename=None, duplicate_of=same[0]["filename"]), 200
            return jsonify(filename=target.name), 201
        finally:
            lock.release()

    @app.post("/api/index")
    def index():
        if not lock.acquire(blocking=False):
            abort(409, description="Indexing is already running.")
        try:
            summary = Indexer(settings, log=lambda message: None).run()
            return jsonify(asdict(summary))
        finally:
            lock.release()

    @app.post("/api/search/scan/plan")
    def scenario_plan():
        if offline_search is not None:
            abort(403, description="Direct scanning is disabled in the offline replay demo.")
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description="Send a scene description and recording selection.")
        if not lock.acquire(blocking=False):
            abort(409, description="Wait for the current operation to finish.")
        try:
            plan = scenario_scan.build_library_plan(settings, data.get('query'), data.get('video_ids'),
                                                   data.get('start_sec', 0), data.get('end_sec'))
            now = time.monotonic()
            for ident in list(scan_jobs):
                if now-scan_jobs[ident]['created'] > 3600:
                    del scan_jobs[ident]
            if len(scan_jobs) >= 8:
                abort(409, description="Cancel an earlier scan or refresh the server before creating more plans.")
            ident = uuid.uuid4().hex
            scan_jobs[ident] = dict(plan=plan, owner=session['csrf'], created=now, stopped=False)
            return jsonify(scan_id=ident, **scenario_scan.public_plan(plan))
        except (ValueError, SearchError) as error:
            return jsonify(error=redact(str(error))), 400
        finally:
            lock.release()

    @app.post("/api/search/scan/batch")
    def scenario_batch():
        if offline_search is not None:
            abort(403, description="Direct scanning is disabled in the offline replay demo.")
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get('approve_frame_upload') is not True:
            abort(400, description="Review the scan plan and approve its Google frame uploads first.")
        if not lock.acquire(blocking=False):
            abort(409, description="Wait for the current operation to finish.")
        job = None
        try:
            ident = data.get('scan_id')
            job = scan_jobs.get(ident) if isinstance(ident, str) else None
            if (not job or job['owner'] != session['csrf'] or job['stopped']
                    or time.monotonic()-job['created'] > 3600):
                abort(409, description="This scan is stopped, expired or unavailable. Review a new plan.")
            result = scenario_scan.run_batch(job['plan'], data.get('batch'), settings, search_settings)
            for hit in result['hits']+result['unclear_hits']+result['rejected_hits']:
                hit['video_url'] = url_for('video_file', video_id=hit['video_id'])
                hit['thumbnail_url'] = url_for('frame_file', rel=hit['thumbnail']) if hit['thumbnail'] else None
            result['excluded_recordings'] = job['plan']['excluded']
            if result['done']:
                scan_jobs.pop(ident, None)
            return jsonify(result)
        except (ValueError, SearchError) as error:
            if job:
                job['stopped'] = True
            return jsonify(error=redact(str(error))), 503
        finally:
            lock.release()

    @app.post("/api/search/scan/cancel")
    def scenario_cancel():
        data = request.get_json(silent=True) or {}
        ident = data.get('scan_id') if isinstance(data, dict) else None
        job = scan_jobs.get(ident) if isinstance(ident, str) else None
        if job and job['owner'] == session['csrf']:
            job['stopped'] = True
            del scan_jobs[ident]
        return jsonify(ok=True)

    @app.post("/api/search")
    def search():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            abort(400, description="Send a JSON object containing a query.")
        query = data.get("query", "")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            abort(400, description="Enter a description between 1 and 500 characters.")
        visual_check = data.get("visual_check", False)
        if type(visual_check) is not bool:
            abort(400, description="visual_check must be true or false.")
        if visual_check and offline_search is not None:
            abort(403, description="Image checking is disabled in the offline replay demo; no Google calls are made.")
        if visual_check and data.get("approve_frame_upload") is not True:
            abort(400, description="Approve sending sampled frames to Google before visual checking.")
        investigation_id = data.get("investigation_id")
        if investigation_id is not None and type(investigation_id) is not int:
            abort(400, description="investigation_id must be a number.")
        if not lock.acquire(blocking=False):
            abort(409, description="Wait for local indexing to finish before searching.")
        try:
            result = (offline_search or search_videos)(query.strip(), settings, search_settings).to_dict()
            coverage = search_coverage()
            # The preset event index does not use AI preparation, so that warning does not apply to it.
            if coverage["needs_preparation"] and demo_mode != "event_index":
                result["warnings"].insert(0, "These videos are not prepared for current AI search: "
                                          + ", ".join(coverage["needs_preparation"])
                                          + ". Review the AI indexing plan to include them.")
            result["coverage"] = coverage
            if visual_check:
                result = review_results(result, settings, search_settings)
        except (SearchError, ValueError) as error:
            return jsonify(error=redact(str(error))), 503
        finally:
            lock.release()
        all_hits = result["hits"] + result.get("unclear_hits", []) + result.get("rejected_hits", [])
        # Show the reviewer's own earlier decision for the same query/window/mode. This is display
        # only: it never changes ranking, grouping or the system status ("uncertain").
        mode = "visual" if visual_check else "ranked"
        earlier = feedback.lookup(feedback_path(), redact(query.strip()), mode,
                                  [(h["video_id"], h["start_sec"], h["end_sec"]) for h in all_hits])
        for hit in all_hits:
            hit["video_url"] = url_for("video_file", video_id=hit["video_id"])
            hit["thumbnail_url"] = url_for("frame_file", rel=hit["thumbnail"]) if hit["thumbnail"] else None
            hit["human_review"] = earlier.get((hit["video_id"], hit["start_sec"], hit["end_sec"]))
        if investigation_id is not None:
            # Save the query and the settings it ran with, so the investigation can re-run it.
            try:
                result["saved_query"] = store.save_query(
                    investigation_id, query, mode, search_run_settings(visual_check), result_count=len(all_hits))
            except (InvestigationError, StoreUnavailable) as error:
                result["warnings"].insert(0, f"The search ran, but was not saved to the investigation: {error}")
        return jsonify(result)

    @app.post("/api/feedback")
    def save_feedback():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description="Send a review object.")
        query = data.get("query")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            abort(400, description="A review needs its original search query.")
        if data.get("assessment") not in ("correct", "wrong", "unsure") or data.get("search_mode") not in ("visual", "ranked"):
            abort(400, description="Choose Correct, Wrong, or Unsure for a valid search mode.")
        if type(data.get("video_id")) is not int:
            abort(400, description="Choose an indexed video.")
        videos = rows("SELECT filename,duration_sec FROM videos WHERE id=?", (data["video_id"],))
        if not videos:
            abort(404, description="This video is no longer indexed.")
        start, end = data.get("start_sec"), data.get("end_sec")
        if (any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end))
                or not 0 <= start < end <= (videos[0]["duration_sec"] or 0)):
            abort(400, description="Review times must be inside the indexed video.")
        feedback.save(feedback_path(), dict(
            query=redact(query.strip()), video_id=data["video_id"], filename=videos[0]["filename"],
            start_sec=start, end_sec=end, search_mode=data["search_mode"], assessment=data["assessment"]))
        return jsonify(ok=True)

    @app.get("/api/feedback/export")
    def export_feedback():
        return app.response_class(feedback.export_csv(feedback_path()),
            mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="search-feedback.csv"',
                                          "Cache-Control": "no-store"})

    def current_plan():
        if not settings.db_path.exists():
            raise SearchError("Index your local videos first.")
        return build_plan(settings, sentry_client.stats(search_settings)["source_files"], load_manifest(settings))

    def fingerprint(plan):
        return hashlib.sha256(json.dumps(asdict(plan), sort_keys=True).encode()).hexdigest()

    @app.post("/api/search/plan")
    def search_plan():
        if not lock.acquire(blocking=False):
            abort(409, description="Another operation is running. Try again when it finishes.")
        try:
            plan = current_plan()
            session["sync_plan"] = fingerprint(plan)
            # Show only local video names, not other projects in the shared index.
            return jsonify(to_index=[v.rel_path for v in plan.to_index],
                           removals=len(plan.to_remove), up_to_date=len(plan.up_to_date),
                           not_searchable=plan.not_searchable,
                           estimated_cost_usd=plan.estimated_cost_usd)
        except SearchError as error:
            return jsonify(error=redact(str(error))), 503
        finally:
            lock.release()

    @app.post("/api/search/sync")
    def search_sync():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            abort(400, description="Review the plan and confirm before preparing AI search.")
        if not lock.acquire(blocking=False):
            abort(409, description="Another operation is running. Try again when it finishes.")
        try:
            plan = current_plan()
            if session.get("sync_plan") != fingerprint(plan):
                abort(409, description="The plan has changed. Review the latest plan first.")
            session.pop("sync_plan", None)
            logs = []
            ok = apply_plan(plan, settings, search_settings, sentry_cli_command(search_settings), log=logs.append)
            return jsonify(ok=ok, messages=[redact(line) for line in logs])
        except SearchError as error:
            return jsonify(error=redact(str(error))), 503
        finally:
            lock.release()

    # ------------------------------------------------------------------ investigations

    def library_by_sha():
        return {v["sha256"]: v for v in rows("SELECT id, sha256, filename, rel_path, duration_sec, size_bytes FROM videos "
                                             "WHERE status = 'done'")}

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description="Send a JSON object.")
        return data

    def investigation_view(inv_id):
        """Investigation with source-resolved, chronologically ordered evidence and media URLs."""
        inv = store.get(inv_id)
        items, basis = timeline(resolve_sources(inv["evidence"], library_by_sha(), settings.video_dir),
                                inv["recording_clocks"])
        for e in items:
            available = e["source_status"] != "missing"
            e["video_url"] = url_for("video_file", video_id=e["current_video_id"]) if available else None
            e["thumbnail_url"] = (url_for("frame_file", rel=e["thumbnail"])
                                  if available and e["thumbnail"] else None)
        inv["evidence"], inv["timeline_basis"] = items, basis
        recordings = {}
        for e in items:
            recordings.setdefault(e["video_sha256"], {"video_sha256": e["video_sha256"],
                                                      "filename": e["current_filename"] or e["video_filename"],
                                                      "recorded_start": inv["recording_clocks"].get(e["video_sha256"])})
        inv["recordings"] = list(recordings.values())
        return inv

    @app.get("/api/investigations")
    def list_investigations():
        return jsonify(investigations=store.list())

    @app.post("/api/investigations")
    def create_investigation():
        data = body()
        inv = store.create(data.get("title"), data.get("description", ""))
        return jsonify(investigation_view(inv["id"])), 201

    @app.get("/api/investigations/<int:inv_id>")
    def get_investigation(inv_id):
        return jsonify(investigation_view(inv_id))

    @app.post("/api/investigations/<int:inv_id>")
    def update_investigation(inv_id):
        data = body()
        store.update(inv_id, title=data.get("title"), description=data.get("description"))
        return jsonify(investigation_view(inv_id))

    @app.post("/api/investigations/<int:inv_id>/status")
    def investigation_status(inv_id):
        store.set_status(inv_id, body().get("status"))
        return jsonify(investigation_view(inv_id))

    @app.post("/api/investigations/<int:inv_id>/queries/<int:query_id>/remove")
    def remove_saved_query(inv_id, query_id):
        store.remove_query(inv_id, query_id)
        return jsonify(investigation_view(inv_id))

    @app.post("/api/investigations/<int:inv_id>/evidence")
    def add_evidence(inv_id):
        data = body()
        if type(data.get("video_id")) is not int:
            abort(400, description="Choose a clip from an indexed video.")
        video = rows("SELECT id, sha256, filename, rel_path, duration_sec FROM videos WHERE id=? AND status='done'",
                     (data["video_id"],))
        if not video:
            abort(404, description="This video is no longer indexed.")
        video = video[0]
        # The source reference and thumbnail come from the server's own records, never the client.
        thumbnail = data.get("thumbnail")
        if not isinstance(thumbnail, str) or not rows("SELECT 1 FROM frames WHERE video_id=? AND image_path=?",
                                                      (video["id"], thumbnail)):
            thumbnail = None  # anything that is not one of this video's own frames is dropped
        store.add_evidence(inv_id, dict(
            video_sha256=video["sha256"], video_filename=video["filename"], video_rel_path=video["rel_path"],
            video_duration_sec=video["duration_sec"], start_sec=data.get("start_sec"), end_sec=data.get("end_sec"),
            query=redact(data.get("query", "").strip()) if isinstance(data.get("query"), str) else data.get("query"),
            search_mode=data.get("search_mode"), rank=data.get("rank"), best_score=data.get("best_score"),
            score_above_median=data.get("score_above_median"), visual_verdict=data.get("visual_verdict"),
            visual_reason=redact(data["visual_reason"]) if isinstance(data.get("visual_reason"), str) else None,
            thumbnail=thumbnail))
        return jsonify(investigation_view(inv_id)), 201

    @app.post("/api/investigations/<int:inv_id>/evidence/<int:ev_id>/remove")
    def remove_evidence(inv_id, ev_id):
        store.remove_evidence(inv_id, ev_id, body().get("reason", ""))
        return jsonify(investigation_view(inv_id))

    @app.post("/api/investigations/<int:inv_id>/evidence/<int:ev_id>/review")
    def review_evidence(inv_id, ev_id):
        data = body()
        updated = store.review_evidence(inv_id, ev_id, decision=data.get("decision"), note=data.get("note"))
        # Mirror the decision into search feedback so result cards show it ("Your earlier review").
        current = library_by_sha().get(updated["video_sha256"])
        warning = None
        if (data.get("decision") and current and updated["search_mode"] in ("ranked", "visual")
                and updated["end_sec"] <= (current["duration_sec"] or 0)):
            try:
                feedback.save(feedback_path(), dict(
                    query=updated["query"], video_id=current["id"], filename=current["filename"],
                    start_sec=updated["start_sec"], end_sec=updated["end_sec"],
                    search_mode=updated["search_mode"], assessment=updated["decision"]))
            except sqlite3.Error:
                # The investigation decision is already saved; only the search-card mirror failed.
                warning = ("Your decision was saved in the investigation, but the search review file "
                           "(search_feedback.db) could not be updated. It was left unchanged.")
        view = investigation_view(inv_id)
        if warning:
            view["warning"] = warning
        return jsonify(view)

    @app.post("/api/investigations/<int:inv_id>/clock")
    def recording_clock(inv_id):
        data = body()
        store.set_recording_start(inv_id, data.get("video_sha256"), data.get("recorded_start"))
        return jsonify(investigation_view(inv_id))

    @app.get("/api/investigations/<int:inv_id>/audit")
    def investigation_audit(inv_id):
        return jsonify(audit=store.audit(inv_id))

    @app.post("/api/investigations/<int:inv_id>/report")
    def investigation_report(inv_id):
        fmt = body().get("format")
        if fmt not in ("html", "json"):
            abort(400, description="Choose an HTML or JSON report.")
        inv = investigation_view(inv_id)
        store.record_export(inv_id, fmt)  # recorded before rendering, so the report includes it
        items = verify_sources(inv["evidence"], settings.video_dir, sha256_file)
        report = case_report.build_report(inv, items, inv["timeline_basis"], store.audit(inv_id))
        text = (case_report.render_html(report, settings.frames_dir) if fmt == "html"
                else case_report.render_json(report))
        name = f"investigation-{inv_id}-report.{fmt}"
        return app.response_class(text, mimetype="text/html" if fmt == "html" else "application/json",
                                  headers={"Content-Disposition": f'attachment; filename="{name}"',
                                           "Cache-Control": "no-store"})

    return app
