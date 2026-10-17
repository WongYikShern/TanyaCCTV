"""Start the local TanyaCCTV dashboard: python backend/scripts/run_web.py."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tanya.web import create_app

if __name__ == "__main__":
    # A project-local search environment is optional; explicit settings take precedence.
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    search_python = root / ".venv" / "sentry" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if search_python.is_file() and not os.environ.get("TANYA_SENTRY_PYTHON", "").strip():
        os.environ["TANYA_SENTRY_PYTHON"] = str(search_python)
    create_app().run(host="127.0.0.1", port=5001, debug=False)
