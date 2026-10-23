# Hosted offline demo: synthetic footage and the preset event index, no API key or live search.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 TANYA_HOST=0.0.0.0
CMD ["python", "backend/scripts/run_offline_demo.py"]
