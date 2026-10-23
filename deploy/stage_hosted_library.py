"""Stage the footage for the hosted website: python deploy/stage_hosted_library.py

Copies only the approved public clips (the four CAVIAR clips) from data/videos, with their footage notes
and camera-map entries, into deploy/hosted-library/ (git-ignored). deploy/Dockerfile.hosted bakes that
folder into a private image; nothing else from data/ goes into it.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "deploy" / "hosted-library"
MARKER = OUT / ".staged-by-stage_hosted_library"
CLIPS = ["caviar_Browse2.mp4", "caviar_EnterExitCrossingPaths1cor.mp4",
         "caviar_EnterExitCrossingPaths1front.mp4", "caviar_Rest_FallOnFloor.mp4"]


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    if OUT.exists():
        if not MARKER.is_file():
            print(f"{OUT} exists but was not made by this script; move it away first.", file=sys.stderr)
            return 1
        shutil.rmtree(OUT)   # only ever a folder this script made
    (OUT / "videos").mkdir(parents=True)
    MARKER.touch()
    hashes = set()
    for name in CLIPS:
        source = DATA / "videos" / name
        if not source.is_file():
            print(f"Missing {source}; prepare the CAVIAR clips first.", file=sys.stderr)
            return 1
        shutil.copy2(source, OUT / "videos" / name)
        hashes.add(sha256(source))
    notes = json.loads((DATA / "footage_notes.json").read_text(encoding="utf-8"))
    notes["notes"] = [n for n in notes["notes"] if n["sha256"] in hashes]
    (OUT / "footage_notes.json").write_text(json.dumps(notes, indent=1), encoding="utf-8")
    cameras = json.loads((DATA / "cameras.json").read_text(encoding="utf-8"))
    cameras = {sha: c for sha, c in cameras.items() if sha in hashes}
    (OUT / "cameras.json").write_text(json.dumps(cameras, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Staged {len(CLIPS)} clips, {len(notes['notes'])} footage notes and {len(cameras)} camera(s) in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
