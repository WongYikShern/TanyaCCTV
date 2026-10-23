# Hosted offline demo: synthetic footage and the preset event index, no API key or live search.
FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
# imageio-ffmpeg ships a static FFmpeg binary; linking it onto PATH is much lighter than the apt package.
RUN pip install --no-cache-dir -r backend/requirements.txt imageio-ffmpeg \
    && ln -s "$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" /usr/local/bin/ffmpeg

COPY . .

ENV PYTHONUNBUFFERED=1 TANYA_HOST=0.0.0.0
CMD ["python", "backend/scripts/run_offline_demo.py"]
