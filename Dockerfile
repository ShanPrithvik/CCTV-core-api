FROM python:3.11-slim

# ffmpeg: low-latency alert-clip encoding (src/services/local_storage.py)
# libgl1 / libglib2.0-0: runtime libs some OpenCV/Ultralytics codepaths touch
# even when running headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HEADLESS=true \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Overridden by docker-compose.yml for the Celery worker service.
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
