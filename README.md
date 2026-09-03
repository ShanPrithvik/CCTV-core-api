# CCTV Core API

Backend service for an AI-powered CCTV surveillance system. It manages cameras and per-camera detection rules, and runs real-time video analytics on RTSP streams using [YOLOv8](https://github.com/ultralytics/ultralytics). Detection jobs run asynchronously as [Celery](https://docs.celeryq.dev/) tasks so that multiple camera streams can be monitored in parallel without blocking the API. It runs headless by default, so it works on a server/container with no display, and streams live annotated detection frames back to the frontend over HTTP.

## Features

- **Camera management** — add, list, fetch, and (soft) delete cameras. A snapshot is captured from the RTSP stream when a camera is added.
- **Rule configuration** — attach detection rules to a camera, each backed by a model type and (optionally) a region of interest (ROI).
- **Detection models** (run as abortable Celery tasks):
  - `CROWD_DETECTION` — overcrowding detection inside an ROI, with a configurable person count and alert timeout.
  - `RESTRICTED_AREA` — creates a high-priority event when a person enters a defined ROI.
  - `SHOPLIFTING` — shoplifting detection using a custom-trained model.
- **Live view** — while a rule is running, the worker publishes the latest annotated frame (ROI, boxes, alert overlays) to Redis; `GET /api/camera/<id>/stream` serves it as an MJPEG stream a browser `<img>` tag can render directly.
- **Automatic clip saving** — when an alert triggers, a short pre-/post-roll video clip is saved (FFmpeg with an OpenCV fallback).
- **Alert logging** — alerts are appended to text logs under `logs/`.
- **Headless by default** — no desktop windows or Windows-only audio calls at runtime; everything is env-configurable for containers/servers.

## Tech stack

- **Flask** — REST API (with Flask-CORS, Flask-SQLAlchemy, Flask-Marshmallow), served by **gunicorn** in production
- **Celery + Redis** — asynchronous task queue / broker / result backend, and the transport for live-view frames
- **SQLite** (default) or **MySQL** (opt-in) — persistent storage for cameras and rules
- **OpenCV + Ultralytics YOLOv8 + PyTorch** — video capture and inference (`yolov8n` by default for CPU-friendly deployments)

## Project structure

```
CCTV/
├── app.py                       # Flask app entrypoint + Celery config
├── requirements.txt
├── Dockerfile                   # CPU/headless image (api + worker share it)
├── docker-compose.yml           # api, worker, redis, mediamtx + demo publisher
├── logs/                        # Alert logs (generated at runtime)
├── saved_clips/                 # Saved alert video clips (generated at runtime)
└── src/
    ├── init.py                  # App factory, DB/Marshmallow init, CORS
    ├── routes.py                # Blueprint registration
    ├── celery_worker.py         # Celery app + task registration
    ├── config/
    │   ├── db_config.py         # SQLite (default) / MySQL config, env-driven
    │   └── celery_config.py     # Celery factory
    ├── controllers/             # HTTP route handlers (camera, rule, live stream)
    ├── services/
    │   ├── stream_utils.py      # Headless mode + Redis live-frame publish/read
    │   ├── overcrowding_service.py
    │   ├── restricted_area_service.py
    │   ├── shoplifting_service.py
    │   ├── camera_service.py / local_storage.py / image_capture.py
    │   └── rule_service.py
    ├── models/                  # SQLAlchemy models (Camera, RuleConfig, RuleTypes)
    └── enum/model_types.py      # Supported detection model types
```

## Quick start: Docker (recommended)

This brings up the API, a Celery worker, Redis, and a self-contained fake RTSP camera (a looped synthetic test pattern via [MediaMTX](https://github.com/bluenviron/mediamtx) + ffmpeg) — no external camera or manual service setup required.

```bash
cp .env.example .env
docker compose up --build
```

- API: `http://localhost:5000`
- Demo camera RTSP URL (use this when adding a camera from the frontend): `rtsp://mediamtx:8554/demo`
  - Note: this URL only resolves *inside* the Docker network. The `worker` container reads it directly; that's all that matters for detection to run.
- The demo feed is a synthetic test pattern (no real people/objects), so it proves the pipeline end-to-end (stream in → detection runs → live view works) but won't produce real crowd/restricted-area alerts. Swap in a real camera's `rtsp://` URL to see real detections.
- `yolov8n.pt` is downloaded automatically by Ultralytics on first use — no manual model setup needed for `CROWD_DETECTION` / `RESTRICTED_AREA`.
- `SHOPLIFTING` requires the custom `shoplifting_best.pt` weight, which is **not** included. Mount it if you have it (see the commented-out volume line in `docker-compose.yml`); without it, only shoplifting rules will fail (crowd/restricted-area are unaffected).

## Manual setup (without Docker)

### Prerequisites

- Python 3.10+
- Redis server (for Celery and live-view frames)
- FFmpeg on your `PATH` (recommended for clip encoding; falls back to OpenCV)
- MySQL, only if you set `DB_ENGINE=mysql` (SQLite is the default, zero setup)

### Setup

1. **Clone and enter the repo**

```bash
git clone git@github-personal:ShanPrithvik/CCTV-core-api.git
cd CCTV-core-api
```

2. **Create a virtual environment and install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3. **Configure environment variables**

```bash
cp .env.example .env
```

See [.env.example](.env.example) for the full list. Key ones:

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_ENGINE` | `sqlite` (zero setup) or `mysql` | `sqlite` |
| `REDIS_URL` | Redis broker/result backend + live-frame store | `redis://localhost:6379/0` |
| `HEADLESS` | `true`: no desktop windows, publish frames to Redis instead. `false`: open debug preview windows (local machine with a display only) | `true` |
| `CROWD_MODEL_PATH` / `RESTRICTED_MODEL_PATH` | YOLO weight for person detection; auto-downloads if a standard name like `yolov8n.pt` | `yolov8n.pt` |
| `SHOPLIFTING_MODEL_PATH` | Custom shoplifting weight (must be provided; no auto-download) | `src/trained-models/shoplifting_best.pt` |
| `DETECTION_FRAME_SKIP` / `SHOPLIFTING_FRAME_SKIP` | Run inference every Nth frame (higher = lighter on CPU) | `3` / `2` |
| `CAMERA_SNAPSHOT_DIR` / `SAVED_CLIPS_DIR` | Where snapshots/clips are written | `cctv_snip` / `saved_clips` |

If using `DB_ENGINE=mysql`, also set `DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`/`DB_NAME` and create the database: `CREATE DATABASE cctv_db;`. Tables are created automatically on startup either way.

### Running

Start Redis first, then in separate terminals:

```bash
# 1. Celery worker (runs the detection tasks)
celery -A src.celery_worker.celery worker --loglevel=info

# 2. Flask API (development)
python app.py

# 2. Flask API (production, instead of the above)
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

The API runs on `http://localhost:5000` by default.

## Model weights

- `yolov8n.pt` (default for `CROWD_DETECTION` / `RESTRICTED_AREA`) auto-downloads from Ultralytics on first use — nothing to provide. This keeps the default deployment CPU-friendly; swap `CROWD_MODEL_PATH`/`RESTRICTED_MODEL_PATH` to `yolov8m.pt` (or your own weight) for higher accuracy on a GPU/more powerful machine.
- `SHOPLIFTING` uses a custom-trained weight (`shoplifting_best.pt`) that is **not** included in this repo and has no auto-download. Provide your own at `SHOPLIFTING_MODEL_PATH`. If it's missing, only shoplifting rules fail — crowd/restricted-area detection are unaffected (models load lazily, per-task).

## Live view

`GET /api/camera/<camera_id>/stream` returns an MJPEG stream (`multipart/x-mixed-replace`) of the latest annotated frame for that camera, as published by whichever detection task is currently running for it. A plain `<img src="...">` tag renders it directly — see the frontend's `LiveView` component. If no rule is running (or `HEADLESS=false`, i.e. frames are shown in a desktop window instead), the endpoint has nothing to stream.

## API reference

Base URL: `http://localhost:5000` (or your deployed API URL)

### Cameras

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/camera` | Add a camera. Body: `{ "cameraName": "...", "rtsp": "rtsp://..." }` |
| `GET` | `/api/camera` | List all active cameras |
| `GET` | `/api/camera/<camera_id>` | Get a single camera |
| `DELETE` | `/api/camera/<camera_id>` | Soft-delete (mark inactive) |
| `GET` | `/camera-view/<filename>` | Serve a captured camera snapshot |
| `GET` | `/api/camera/<camera_id>/stream` | Live MJPEG view of the camera's detection output |

### Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/camera/<camera_id>/rule` | Create a detection rule for a camera |
| `GET` | `/api/camera/<camera_id>/rule` | Get active rules for a camera |
| `DELETE` | `/api/camera/<camera_id>/rule/<rule_id>` | Soft-delete a rule and abort its task |

Rule updates are available at
`PUT /api/camera/<camera_id>/rule/<rule_id>`.

### Security operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/operations/overview` | Alert-first summary with latest alerts and camera analytics-frame health |
| `GET` | `/api/events` | List structured events for the active organization |
| `GET` | `/api/alerts` | List alerts; optionally filter by `status` |
| `PATCH` | `/api/alerts/<alert_id>` | Set status to `NEW`, `ACKNOWLEDGED`, or `RESOLVED` |
| `GET` | `/api/camera-health` | List current analytics-frame health signals |

Camera health is intentionally reported as an **analytics-frame signal** in
this phase. `UNKNOWN` means no recent frame was published by a running
detection rule; it does not yet prove that the physical camera is offline.

**Example — create a crowd-detection rule:**

```json
POST /api/camera/1/rule
{
  "name": "Entrance crowd watch",
  "modelType": "CROWD_DETECTION",
  "rule": [
    {
      "roi": [
        { "x": 100, "y": 100 },
        { "x": 500, "y": 100 },
        { "x": 500, "y": 400 },
        { "x": 100, "y": 400 }
      ],
      "ruleTypes": [
        { "type": "Number of Person", "value": "5" },
        { "type": "Time to Lookout", "value": "10" }
      ]
    }
  ]
}
```

**Model-type rules:**

- `CROWD_DETECTION` — requires a 4-point `roi` and rule types `Number of Person` and `Time to Lookout`.
- `RESTRICTED_AREA` — requires a 4-point `roi`; `ruleTypes` must be empty.
- `SHOPLIFTING` — `roi` and `ruleTypes` must be empty.

## Deploying for free (single-stream demo)

This backend is well suited to a $0 demo on an [Oracle Cloud "Always Free" ARM VM](https://www.oracle.com/cloud/free/) (Ampere A1, up to 4 OCPU / 24 GB RAM, free indefinitely):

1. Provision the VM, install Docker + the Compose plugin.
2. `git clone` this repo onto the VM, `cp .env.example .env`, adjust `CORS_ALLOWED_ORIGINS` to your deployed frontend's URL.
3. `docker compose up -d --build`.
4. Put the API behind HTTPS (a Caddy reverse proxy with automatic Let's Encrypt certs, or a Cloudflare Tunnel, both free) and point the frontend's `REACT_APP_API_URL` at it.

This is a single-stream, CPU-only (`yolov8n`) setup meant to prove the pipeline works end-to-end — not a substitute for a real multi-camera GPU deployment.

## Notes

- CORS defaults to `*`; set `CORS_ALLOWED_ORIGINS` to your frontend's origin in production.
- Alerts are written to `logs/overcrowding_alerts.txt` and `logs/restricted_area_alerts.txt`.
- `HEADLESS=false` (desktop preview windows) is only meaningful on your own machine with a display; servers and containers should always use the default `HEADLESS=true`.
