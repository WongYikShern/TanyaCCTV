"""Local-only dashboard and API around the existing indexer and search bridge."""
from dataclasses import asdict
from pathlib import Path
import os
import secrets
import sqlite3
import threading
import uuid
import hashlib
import json
import math

from flask import Flask, abort, jsonify, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from .config import SUPPORTED_EXTENSIONS, SEARCHABLE_EXTENSIONS, load_settings, load_search_settings
from .indexer import Indexer, sha256_file
from .search import search_videos
from .sentry_client import SearchError, redact
from . import sentry_client
from .search_sync import build_plan, load_manifest, apply_plan, sentry_cli_command
from .visual_review import review_results
from . import feedback


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


def create_app(settings=None, search_settings=None):
    settings = settings or load_settings()
    search_settings = search_settings or load_search_settings()
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=512 * 1024 * 1024,
                      SESSION_COOKIE_SAMESITE="Strict")
    lock = threading.Lock()
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
        # Reject DNS rebinding and cross-site mutation requests, even on localhost.
        if request.host not in {"localhost:5001", "127.0.0.1:5001", "localhost", "127.0.0.1"}:
            abort(403)
        if request.method == "POST":
            token = session.get("csrf")
            if not token or not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), token):
                abort(403, description="Refresh the page before trying again.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/")
    def home():
        session.setdefault("csrf", secrets.token_hex(32))
        return render_template("dashboard.html", csrf=session["csrf"])

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
        return jsonify(engine_ready=engine, key_ready=key, search_ready=engine and key,
                       busy=lock.locked(), max_upload_mb=512, coverage=search_coverage())

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
        return jsonify(videos=result)

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
        if visual_check and data.get("approve_frame_upload") is not True:
            abort(400, description="Approve sending sampled frames to Google before visual checking.")
        if not lock.acquire(blocking=False):
            abort(409, description="Wait for local indexing to finish before searching.")
        try:
            result = search_videos(query.strip(), settings, search_settings).to_dict()
            coverage = search_coverage()
            if coverage["needs_preparation"]:
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

    return app
