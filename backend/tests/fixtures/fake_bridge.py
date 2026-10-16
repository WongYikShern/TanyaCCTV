"""Stand-in for search_engine/tanya_bridge.py, used by TanyaCCTV's integration tests.

Controlled by environment variables:
  FAKE_BRIDGE_MODE   ok (default) | error | garbage | crash | sleep | bad_status | exit_nonzero | key_check
  FAKE_BRIDGE_STATE  JSON file {"source_files": [...]} shared with fake_sentry_cli.py
  FAKE_BRIDGE_LOG    file to which each call's argv is appended (one JSON line per call)
  FAKE_VIDEO_DIR     replaces "{VIDEO_DIR}" in recorded results
Search results come from recorded_live.json (real scores from the 2026-10-17 live run).
The "misbehaving" modes deliberately echo GEMINI_API_KEY so tests can prove the client redacts it.
"""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
mode = os.environ.get("FAKE_BRIDGE_MODE", "ok")
key = os.environ.get("GEMINI_API_KEY", "")
args = sys.argv[1:]

if os.environ.get("FAKE_BRIDGE_LOG"):
    with open(os.environ["FAKE_BRIDGE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(args) + "\n")


def state():
    p = os.environ.get("FAKE_BRIDGE_STATE")
    return json.loads(Path(p).read_text(encoding="utf-8")) if p else {"source_files": []}


def save(s):
    Path(os.environ["FAKE_BRIDGE_STATE"]).write_text(json.dumps(s), encoding="utf-8")


def out(payload, code=0):
    print(json.dumps(payload))
    sys.exit(code)


if mode == "error":
    out({"ok": False, "error": f"401 API key not valid: {key}", "error_type": "ClientError"}, 1)
if mode == "garbage":
    print(f"warning: using key {key}", file=sys.stderr)
    print("this is not json")
    sys.exit(0)
if mode == "crash":
    print(f"Traceback (most recent call last):\nRuntimeError: bad key {key}", file=sys.stderr)
    sys.exit(3)
if mode == "sleep":
    time.sleep(30)
if mode == "key_check":
    out({"ok": True, "results": [], "key_present": bool(key)})

command = args[0]
if command == "stats":
    out({"ok": True, "total_chunks": 0, "source_files": state()["source_files"]})
if command == "remove":
    src = args[args.index("--source-file") + 1]
    s = state()
    if src not in s["source_files"]:
        out({"ok": False, "error": "refusing to remove: no exact match", "error_type": "BridgeError"}, 1)
    s["source_files"].remove(src)
    save(s)
    out({"ok": True, "source_file": src, "removed_chunks": 2})
if command == "search":
    # Like argparse: the query is the value after "--" (or the first non-option argument).
    query = args[args.index("--") + 1] if "--" in args else args[1]
    n = int(args[args.index("--n") + 1])
    recorded = json.loads((HERE / "recorded_live.json").read_text(encoding="utf-8"))
    data = recorded.get(query, {"ok": True, "query": query, "results": []})
    text = json.dumps(data).replace("{VIDEO_DIR}", os.environ.get("FAKE_VIDEO_DIR", "C:/videos").replace("\\", "/"))
    data = json.loads(text)
    data["results"] = data["results"][:n]
    if mode == "bad_status" and data["results"]:
        data["results"][0]["status"] = "confirmed"
    out(data, 2 if mode == "exit_nonzero" else 0)
out({"ok": False, "error": f"unknown command {command}", "error_type": "BridgeError"}, 1)
