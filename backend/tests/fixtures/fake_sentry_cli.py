"""Stand-in for the `sentrysearch` CLI (index command only). No API calls.

Appends its argv to FAKE_BRIDGE_LOG, and on success adds the file to FAKE_BRIDGE_STATE so the
fake bridge's `stats` sees it. FAKE_CLI_MODE: ok (default) | fail | silent_fail (exit 0, nothing stored).
"""

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["FAKE_BRIDGE_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(["cli", *args]) + "\n")

mode = os.environ.get("FAKE_CLI_MODE", "ok")
if mode == "fail":
    print(f"Error: indexing failed (key {os.environ.get('GEMINI_API_KEY', '')})", file=sys.stderr)
    sys.exit(1)
if mode == "silent_fail":
    sys.exit(0)

state_file = Path(os.environ["FAKE_BRIDGE_STATE"])
state = json.loads(state_file.read_text(encoding="utf-8"))
if args[1] not in state["source_files"]:
    state["source_files"].append(args[1])
state_file.write_text(json.dumps(state), encoding="utf-8")
print(f"Indexed chunks from {args[1]}")
