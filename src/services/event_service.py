"""Persist structured detection events from standalone Celery workers."""

import logging
import threading

from flask import Flask

from src.config.db_config import build_database_uri, sqlalchemy_engine_options
from src.init import db

logger = logging.getLogger("cctv.events")
_worker_app = None
_worker_app_lock = threading.Lock()


def _get_worker_app():
    global _worker_app
    if _worker_app is not None:
        return _worker_app

    with _worker_app_lock:
        if _worker_app is None:
            app = Flask("cctv-event-writer")
            app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
            app.config["SQLALCHEMY_ENGINE_OPTIONS"] = sqlalchemy_engine_options()
            app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
            db.init_app(app)
            # Register all mappers against this SQLAlchemy metadata.
            import src.models  # noqa: F401

            _worker_app = app
    return _worker_app


def record_detection_event(
    *,
    camera_id,
    event_type,
    severity="MEDIUM",
    confidence=None,
    clip_path=None,
    snapshot_path=None,
    metadata=None,
):
    """Create one Event and its operator-facing Alert.

    Returns the event ID, or ``None`` when persistence fails. Detection must
    continue even when the control-plane database is temporarily unavailable.
    """
    from src.models.camera import Camera
    from src.models.event import Alert, Event

    app = _get_worker_app()
    with app.app_context():
        try:
            camera = db.session.get(Camera, int(camera_id))
            if not camera or not camera.organization_id or camera.status != "Active":
                logger.warning("Skipping event for unavailable camera %s", camera_id)
                return None

            event = Event(
                organization_id=camera.organization_id,
                camera_id=camera.id,
                event_type=event_type,
                severity=severity,
                confidence=float(confidence) if confidence is not None else None,
                clip_path=clip_path,
                snapshot_path=snapshot_path,
                event_metadata=metadata or {},
            )
            db.session.add(event)
            db.session.flush()
            db.session.add(
                Alert(organization_id=camera.organization_id, event_id=event.id)
            )
            db.session.commit()
            return event.id
        except Exception:
            db.session.rollback()
            logger.exception("Failed to persist detection event for camera %s", camera_id)
            return None
