#!/bin/sh
# Refresh the code on the disk at the Mac's project path, keeping data/ (videos, frames, databases).
set -e
PROJECT=/Users/jasonlee/Documents/TanyaCCTV
mkdir -p "$PROJECT/data" "$HOME/.sentrysearch"
find "$PROJECT" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} +
cp -a /opt/app/. "$PROJECT/"
cd "$PROJECT"
exec python backend/scripts/run_web.py
