"""Start the local TanyaCCTV dashboard: python backend/scripts/run_web.py (http://localhost:5001/).

The search interpreter is TANYA_SENTRY_PYTHON if set, otherwise .venv/sentry if it exists
(see tanya.config.load_search_settings). Run check_setup.py for a full readiness report.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tanya.config import ConfigError, load_search_settings, load_settings  # noqa: E402
from tanya.setup_check import PASS, WEB_PORT, check_port  # noqa: E402
from tanya.web import create_app  # noqa: E402


def startup_lines(settings, search_settings) -> list[str]:
    """Readiness summary printed at startup. Shows only whether a key is set, never its value."""
    engine = bool(search_settings.sentry_python and search_settings.sentry_python.is_file())
    key = bool(os.environ.get("GEMINI_API_KEY"))
    return [
        f"TanyaCCTV is running at http://localhost:{WEB_PORT}/  (Ctrl+C to stop)",
        f"  Videos:        {settings.video_dir}",
        f"  Search engine: {'found' if engine else 'not configured (local features still work)'}",
        f"  Gemini key:    {'set' if key else 'not set (AI search disabled)'}",
        "  Full readiness report: python backend/scripts/check_setup.py",
    ]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    port = check_port()
    if port.status != PASS:
        print(f"Cannot start: {port.detail}. {port.fix}.", file=sys.stderr)
        return 1
    try:
        settings, search_settings = load_settings(), load_search_settings()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    app = create_app(settings, search_settings)
    print("\n".join(startup_lines(settings, search_settings)), flush=True)
    try:
        app.run(host="127.0.0.1", port=WEB_PORT, debug=False)
    except OSError as e:  # e.g. the port was taken between the check and startup
        print(f"Cannot start the website: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
