# CCTV Core API

Backend service for an AI-powered CCTV surveillance system. It manages cameras and per-camera detection rules, and runs real-time video analytics on RTSP streams using [YOLOv8](https://github.com/ultralytics/ultralytics). Detection jobs run asynchronously as [Celery](https://docs.celeryq.dev/) tasks so that multiple camera streams can be monitored in parallel without blocking the API.

## Features

- **Camera management** — add, list, fetch, and (soft) delete cameras. A snapshot is captured from the RTSP stream when a camera is added.
- **Rule configuration** — attach detection rules to a camera, each backed by a model type and (optionally) a region of interest (ROI).
- **Detection models** (run as abortable Celery tasks):
  - `CROWD_DETECTION` — overcrowding detection inside an ROI, with a configurable person count and alert timeout.
  - `RESTRICTED_AREA` — alerts when any person/object enters a defined ROI.
  - `SHOPLIFTING` — shoplifting detection using a custom-trained model.
- **Automatic clip saving** — when an alert triggers, a short pre-/post-roll video clip is saved (FFmpeg with an OpenCV fallback).
- **Alert logging** — alerts are appended to text logs under `logs/`.

## Tech stack

- **Flask** — REST API (with Flask-CORS, Flask-SQLAlchemy, Flask-Marshmallow)
- **Celery + Redis** — asynchronous task queue / broker / result backend
- **MySQL** — persistent storage for cameras and rules
- **OpenCV + Ultralytics YOLOv8 + PyTorch** — video capture and inference

## Project structure

```
CCTV/
├── app.py                       # Flask app entrypoint + Celery config
├── requirements.txt
├── logs/                        # Alert logs (generated at runtime)
├── saved_clips/                 # Saved alert video clips (generated at runtime)
└── src/
    ├── init.py                  # App factory, DB/Marshmallow init
    ├── routes.py                # Blueprint registration
    ├── celery_worker.py         # Celery app + task autodiscovery
    ├── config/
    │   ├── db_config.py         # MySQL connection config (env-driven)
    │   └── celery_config.py     # Celery factory
    ├── controllers/             # HTTP route handlers (camera, rule)
    ├── services/                # Business logic + detection tasks
    ├── models/                  # SQLAlchemy models (Camera, RuleConfig, RuleTypes)
    └── enum/model_types.py      # Supported detection model types
```

## Prerequisites

- Python 3.10+
- MySQL server (a database named `cctv_db` by default)
- Redis server (for Celery)
- FFmpeg on your `PATH` (recommended for clip encoding; falls back to OpenCV)
- YOLOv8 model weights (see [Model weights](#model-weights))

> **Note:** the detection tasks use OpenCV display windows (`cv2.imshow`) and, for overcrowding, `winsound` (Windows-only) for the audible alert. Running the worker on a machine with a display is recommended; on Linux/macOS the `winsound` beep is not available.

## Setup

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

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_USER` | MySQL user | `root` |
| `DB_PASSWORD` | MySQL password | *(empty)* |
| `DB_HOST` | MySQL host | `localhost` |
| `DB_PORT` | MySQL port | `3306` |
| `DB_NAME` | Database name | `cctv_db` |
| `REDIS_URL` | Redis broker/result backend | `redis://localhost:6379/0` |

4. **Create the database**

```sql
CREATE DATABASE cctv_db;
```

Tables are created automatically on startup via `db.create_all()`.

## Model weights

Model weights (`*.pt`) are **not** committed to the repo. Place them where the services expect them:

- `src/trained-models/yolov8m.pt` — base YOLOv8 model (overcrowding)
- `yolov8m.pt` — base YOLOv8 model (restricted area)
- `src/trained-models/shoplifting_best.pt` — custom shoplifting model

The base `yolov8m.pt` can be downloaded from the [Ultralytics releases](https://github.com/ultralytics/assets/releases). The shoplifting model is a custom-trained weight.

## Running

Start Redis and MySQL first, then in separate terminals:

**1. Celery worker** (runs the detection tasks)

```bash
celery -A src.celery_worker.celery worker --loglevel=info
```

**2. Flask API**

```bash
python app.py
```

The API runs on `http://localhost:5000`.

## API reference

Base URL: `http://localhost:5000`

### Cameras

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/camera` | Add a camera. Body: `{ "cameraName": "...", "rtsp": "rtsp://..." }` |
| `GET` | `/api/camera` | List all active cameras |
| `GET` | `/api/camera/<camera_id>` | Get a single camera |
| `DELETE` | `/api/camera/<camera_id>` | Soft-delete (mark inactive) |
| `GET` | `/camera-view/<filename>` | Serve a captured camera snapshot |

### Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/camera/<camera_id>/rule` | Create a detection rule for a camera |
| `GET` | `/api/camera/<camera_id>/rule` | Get active rules for a camera |
| `DELETE` | `/api/camera/<camera_id>/rule/<rule_id>` | Soft-delete a rule and abort its task |

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

## Notes

- CORS is enabled for all origins on `/api/*` (tighten before production).
- Snapshot/clip output paths in `camera_service.py` and `camera_controller.py` currently use Windows-style paths (`D:\CCTV_FE_BE\cctv_snip`); adjust them for your environment.
- Alerts are written to `logs/overcrowding_alerts.txt` and `logs/restricted_area_alerts.txt`.
