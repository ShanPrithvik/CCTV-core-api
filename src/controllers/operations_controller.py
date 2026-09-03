from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from src.auth import jwt_required
from src.init import db
from src.models.camera import Camera
from src.models.camera_health import CameraHealth
from src.models.event import Alert, Event
from src.services.org_permissions import require_active_org
from src.services.stream_utils import get_latest_frame

operations_bp = Blueprint("operations_bp", __name__)


def _iso(value):
    return value.isoformat() if value else None


def _event_payload(event):
    return {
        "id": event.id,
        "camera_id": event.camera_id,
        "camera_name": event.camera.camera_name if event.camera else None,
        "event_type": event.event_type,
        "severity": event.severity,
        "confidence": event.confidence,
        "occurred_at": _iso(event.occurred_at),
        "ended_at": _iso(event.ended_at),
        "snapshot_path": event.snapshot_path,
        "clip_path": event.clip_path,
        "metadata": event.event_metadata or {},
    }


def _alert_payload(alert):
    payload = {
        "id": alert.id,
        "status": alert.status,
        "assigned_user_id": alert.assigned_user_id,
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": _iso(alert.acknowledged_at),
        "resolved_at": _iso(alert.resolved_at),
        "created_at": _iso(alert.created_at),
        "event": _event_payload(alert.event),
    }
    return payload


def _health_payload(health):
    return {
        "camera_id": health.camera_id,
        "camera_name": health.camera.camera_name if health.camera else None,
        "status": health.status,
        "source": health.source,
        "last_frame_at": _iso(health.last_frame_at),
        "checked_at": _iso(health.checked_at),
        "detail": health.detail or {},
    }


def _refresh_health(org_id):
    now = datetime.now(timezone.utc)
    cameras = Camera.query.filter_by(organization_id=org_id, status="Active").all()
    rows = []
    for camera in cameras:
        health = CameraHealth.query.filter_by(camera_id=camera.id).first()
        if health is None:
            health = CameraHealth(
                organization_id=org_id,
                camera_id=camera.id,
                status="UNKNOWN",
            )

        # This is deliberately called an analytics-frame signal, not a camera
        # uptime check: the current system only publishes frames while a rule runs.
        has_frame = get_latest_frame(camera.id) is not None
        if has_frame:
            health.status = "ONLINE"
            health.last_frame_at = now
        elif health.last_frame_at:
            health.status = "STALE"
        else:
            health.status = "UNKNOWN"
        health.checked_at = now
        health.detail = {
            "meaning": (
                "Recent analytics frame received"
                if has_frame
                else "No recent analytics frame; camera reachability is not yet independently verified"
            )
        }
        db.session.add(health)
        rows.append(health)

    db.session.commit()
    return rows


@operations_bp.route("/api/events", methods=["GET"])
@jwt_required
def list_events():
    denied = require_active_org()
    if denied:
        return denied

    limit = min(max(request.args.get("limit", 50, type=int), 1), 200)
    query = Event.query.filter_by(organization_id=g.current_org_id)
    event_type = (request.args.get("event_type") or "").strip()
    camera_id = request.args.get("camera_id", type=int)
    if event_type:
        query = query.filter_by(event_type=event_type)
    if camera_id:
        query = query.filter_by(camera_id=camera_id)
    events = query.order_by(Event.occurred_at.desc()).limit(limit).all()
    return jsonify([_event_payload(event) for event in events]), 200


@operations_bp.route("/api/alerts", methods=["GET"])
@jwt_required
def list_alerts():
    denied = require_active_org()
    if denied:
        return denied

    limit = min(max(request.args.get("limit", 50, type=int), 1), 200)
    query = Alert.query.filter_by(organization_id=g.current_org_id)
    status = (request.args.get("status") or "").strip().upper()
    if status:
        query = query.filter_by(status=status)
    alerts = query.order_by(Alert.created_at.desc()).limit(limit).all()
    return jsonify([_alert_payload(alert) for alert in alerts]), 200


@operations_bp.route("/api/alerts/<int:alert_id>", methods=["PATCH"])
@jwt_required
def update_alert(alert_id):
    denied = require_active_org()
    if denied:
        return denied

    alert = Alert.query.filter_by(
        id=alert_id, organization_id=g.current_org_id
    ).first()
    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    status = ((request.get_json(silent=True) or {}).get("status") or "").strip().upper()
    if status not in {"NEW", "ACKNOWLEDGED", "RESOLVED"}:
        return jsonify({"error": "status must be NEW, ACKNOWLEDGED, or RESOLVED"}), 400

    now = datetime.now(timezone.utc)
    alert.status = status
    if status == "NEW":
        alert.acknowledged_by = None
        alert.acknowledged_at = None
        alert.resolved_at = None
    else:
        if not alert.acknowledged_at:
            alert.acknowledged_by = g.current_user.id
            alert.acknowledged_at = now
        alert.resolved_at = now if status == "RESOLVED" else None
    db.session.commit()
    return jsonify(_alert_payload(alert)), 200


@operations_bp.route("/api/camera-health", methods=["GET"])
@jwt_required
def list_camera_health():
    denied = require_active_org()
    if denied:
        return denied
    rows = _refresh_health(g.current_org_id)
    return jsonify([_health_payload(row) for row in rows]), 200


@operations_bp.route("/api/operations/overview", methods=["GET"])
@jwt_required
def operations_overview():
    denied = require_active_org()
    if denied:
        return denied

    health = _refresh_health(g.current_org_id)
    alerts = (
        Alert.query.filter_by(organization_id=g.current_org_id)
        .order_by(Alert.created_at.desc())
        .limit(20)
        .all()
    )
    new_alerts = Alert.query.filter_by(
        organization_id=g.current_org_id, status="NEW"
    ).count()
    return jsonify({
        "summary": {
            "new_alerts": new_alerts,
            "active_cameras": len(health),
            "online_cameras": sum(1 for row in health if row.status == "ONLINE"),
            "attention_cameras": sum(1 for row in health if row.status != "ONLINE"),
        },
        "alerts": [_alert_payload(alert) for alert in alerts],
        "camera_health": [_health_payload(row) for row in health],
    }), 200
