"""Print what is in the index database (read-only).

Usage:
    python backend/scripts/show_index.py              # list videos
    python backend/scripts/show_index.py --frames 1   # list frames of video id 1
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tanya.config import ConfigError, load_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show indexed videos and frames.")
    parser.add_argument("--frames", type=int, metavar="VIDEO_ID", help="list frames for this video id")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    if not settings.db_path.exists():
        print(f"No database yet at {settings.db_path}. Run index_videos.py first.")
        return 1

    # Open read-only so this script can never change the index.
    conn = sqlite3.connect(f"{settings.db_path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if args.frames is None:
            rows = conn.execute(
                "SELECT v.id, v.rel_path, v.status, v.frame_interval_sec, v.duration_sec, v.fps, "
                "v.width, v.height, v.frame_count, COUNT(f.id) AS frame_rows, v.error "
                "FROM videos v LEFT JOIN frames f ON f.video_id = v.id GROUP BY v.id ORDER BY v.id"
            ).fetchall()
            print(f"{'id':>3}  {'status':<10} {'frames':>6} {'every':>6} {'duration':>9} {'fps':>6} {'size':>10}  path")
            for r in rows:
                size = f"{r['width']}x{r['height']}" if r["width"] else "-"
                dur = f"{r['duration_sec']:.1f}s" if r["duration_sec"] is not None else "-"
                fps = f"{r['fps']:.2f}" if r["fps"] else "-"
                print(
                    f"{r['id']:>3}  {r['status']:<10} {r['frame_rows']:>6} {r['frame_interval_sec']:>5}s "
                    f"{dur:>9} {fps:>6} {size:>10}  {r['rel_path']}"
                )
                if r["error"]:
                    print(f"     error: {r['error']}")
            print(f"\n{len(rows)} video(s)")
        else:
            rows = conn.execute(
                "SELECT frame_number, timestamp_sec, image_path FROM frames "
                "WHERE video_id = ? ORDER BY timestamp_sec",
                (args.frames,),
            ).fetchall()
            for r in rows:
                exists = "ok" if (settings.frames_dir / r["image_path"]).is_file() else "MISSING"
                print(f"t={r['timestamp_sec']:>9.3f}s  frame#{r['frame_number']:<7} [{exists}] {r['image_path']}")
            print(f"\n{len(rows)} frame(s) for video id {args.frames}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
