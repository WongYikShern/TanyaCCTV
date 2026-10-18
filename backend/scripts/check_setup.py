"""Check that TanyaCCTV is ready to run (read-only; never shows the API key).

    .\\.venv\\Scripts\\python.exe backend\\scripts\\check_setup.py
    .\\.venv\\Scripts\\python.exe backend\\scripts\\check_setup.py --json

Exit code 0: the local website and indexer can run (warnings may disable AI search).
Exit code 1: something required is missing; follow the "fix:" lines.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tanya.setup_check import FAIL, WARN, as_json, run_all, summary_lines  # noqa: E402


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Check the TanyaCCTV setup (read-only).")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args(argv)
    checks = run_all()
    if args.json:
        print(as_json(checks))
    else:
        print("\n".join(summary_lines(checks)))
        failed = sum(c.status == FAIL for c in checks)
        warned = sum(c.status == WARN for c in checks)
        if failed:
            print(f"\n{failed} required item(s) failed. The website cannot run until they are fixed.")
        elif warned:
            print(f"\nReady for local use, with {warned} warning(s). AI search may be unavailable.")
        else:
            print("\nAll checks passed.")
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
