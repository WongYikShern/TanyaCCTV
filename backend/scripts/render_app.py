"""TanyaCCTV on a web host such as Render (see docs/deploy-render.md).

Build step (run once, inside the Docker image):
    python backend/scripts/render_app.py build /srv/demo

Web server (gunicorn imports `app` from this file; one worker, because uploads, scans and the
CSRF secret live in that one process):
    gunicorn --chdir backend/scripts --workers 1 --threads 8 --bind 0.0.0.0:$PORT render_app:app

TANYA_MODE chooses what is served:
    demo (default)  the offline demo built at TANYA_DEMO_DIR (default /srv/demo): preset event index,
                    no API key, nothing sent to Google. A redeploy or restart brings it back to the
                    freshly built state.
    full            the normal website on the folders named by TANYA_VIDEO_DIR, TANYA_FRAMES_DIR and
                    TANYA_DB_PATH (put them on a persistent disk). AI search also needs SentrySearch and
                    a Gemini key, which this image does not install.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend/, for `tanya`
sys.path.insert(0, str(Path(__file__).resolve().parent))       # backend/scripts, for run_offline_demo

from tanya import event_index, person_detection  # noqa: E402
from tanya.config import PROJECT_ROOT, SearchSettings, Settings  # noqa: E402
from tanya.web import create_app  # noqa: E402

DEFAULT_DEMO_DIR = "/srv/demo"


def build(root: Path) -> None:
    """Generate the demo footage, frames and event index once (same steps as run_offline_demo.py)."""
    from run_offline_demo import prepare
    prepare(root)


def demo_app(root: Path):
    """Serve a demo workspace that build() already prepared, without re-generating anything."""
    index_path = root / "event-index.json"
    if not index_path.is_file():
        raise RuntimeError(f"No prepared demo at {root}. Run: python backend/scripts/render_app.py build {root}")
    settings = Settings(root / "videos", root / "frames", root / "index.db")
    search_settings = SearchSettings(None, PROJECT_ROOT / "search_engine/tanya_bridge.py")
    return create_app(settings, search_settings,
                      offline_search=event_index.EventIndexSearch(index_path, person_detection.load_config()))


def make_app():
    mode = os.environ.get("TANYA_MODE", "demo").strip().lower()
    if mode == "full":
        return create_app()
    if mode != "demo":
        raise RuntimeError(f"TANYA_MODE must be 'demo' or 'full', not {mode!r}")
    return demo_app(Path(os.environ.get("TANYA_DEMO_DIR", DEFAULT_DEMO_DIR)))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "build":
        build(Path(sys.argv[2]))
        sys.exit(0)
    print(__doc__, file=sys.stderr)
    sys.exit(2)

# Built when gunicorn imports this module (the build command above exits before reaching it).
app = make_app()
