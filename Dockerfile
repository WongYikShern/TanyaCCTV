# TanyaCCTV web image for Render (or any Docker host). See docs/deploy-render.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TANYA_MODE=demo TANYA_DEMO_DIR=/srv/demo
WORKDIR /app

# OpenCV (headless) extracts frames. FFmpeg makes the demo footage and browser-playable copies: the
# static build from imageio-ffmpeg (the same one the AI search set-up uses), put on PATH as `ffmpeg`.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt gunicorn==23.0.0 imageio-ffmpeg==0.6.0 \
 && ln -s "$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" /usr/local/bin/ffmpeg \
 && ffmpeg -hide_banner -version | head -1

COPY . .
# Build the offline demo once, so the server starts in seconds and every restart starts clean.
RUN python backend/scripts/render_app.py build "$TANYA_DEMO_DIR"

# Render sets PORT. One worker: uploads, scans and the session secret live in that process.
CMD ["sh", "-c", "exec gunicorn --chdir backend/scripts --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:${PORT:-10000} render_app:app"]
