import os
import time
import logging

from flask import jsonify, Blueprint, send_from_directory, Response, g
from werkzeug.exceptions import NotFound
from werkzeug.utils import secure_filename
from src.services.camera_service import add_camera_service, get_cameras_service, remove_camera_service, get_camera_service
from src.models.camera import camera_schema, cameras_schema
from src.services.stream_utils import get_latest_frame
from src.services.org_permissions import is_org_admin, require_active_org
from src.auth import jwt_required, optional_jwt, require_stream_or_snapshot_auth
from src.utils.request_helpers import json_body

camera_bp = Blueprint("camera_bp", __name__)
logger = logging.getLogger("cctv.camera")

IMAGE_DIR = os.path.abspath(os.getenv("CAMERA_SNAPSHOT_DIR", "cctv_snip"))
STREAM_POLL_INTERVAL = float(os.getenv("STREAM_POLL_INTERVAL", "0.05"))
STREAM_IDLE_TIMEOUT = float(os.getenv("STREAM_IDLE_TIMEOUT", "15"))


@camera_bp.route("/api/camera", methods=["POST"])
@jwt_required
def add_camera():
    denied = require_active_org()
    if denied:
        return denied
    if not is_org_admin(g.current_org_id):
        return jsonify({"error": "Forbidden"}), 403

    data = json_body()
    camera_name = data.get("cameraName")
    rtsp_url = data.get("rtsp")

    if not camera_name or not rtsp_url:
        return jsonify({"error": "cameraName and rtsp are required"}), 400

    try:
        new_camera = add_camera_service(
            camera_name, rtsp_url, organization_id=g.current_org_id
        )
        return jsonify({
            "message": "Camera added successfully",
            "camera": camera_schema.dump(new_camera),
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("Failed to add camera")
        return jsonify({"error": "Failed to add camera"}), 500


@camera_bp.route("/api/camera", methods=["GET"])
@jwt_required
def get_cameras():
    denied = require_active_org()
    if denied:
        return denied
    try:
        cameras = get_cameras_service(organization_id=g.current_org_id)
        return jsonify(cameras_schema.dump(cameras)), 200
    except Exception:
        logger.exception("Failed to list cameras")
        return jsonify({"error": "Failed to list cameras"}), 500


@camera_bp.route("/api/camera/<int:camera_id>", methods=["GET"])
@jwt_required
def get_camera(camera_id):
    denied = require_active_org()
    if denied:
        return denied
    try:
        camera = get_camera_service(camera_id, organization_id=g.current_org_id)
        if not camera:
            return jsonify({"error": "Camera not found"}), 404
        return jsonify(camera_schema.dump(camera)), 200
    except Exception:
        logger.exception("Failed to fetch camera")
        return jsonify({"error": "Failed to fetch camera"}), 500


@camera_bp.route("/api/camera/<int:camera_id>", methods=["DELETE"])
@jwt_required
def remove_camera(camera_id):
    denied = require_active_org()
    if denied:
        return denied
    if not is_org_admin(g.current_org_id):
        return jsonify({"error": "Forbidden"}), 403

    try:
        camera = get_camera_service(camera_id, organization_id=g.current_org_id)
        if not camera:
            return jsonify({"error": "Camera not found"}), 404

        if remove_camera_service(camera_id, organization_id=g.current_org_id):
            return jsonify({"message": "Camera removed successfully"}), 200
        return jsonify({"error": "Camera not found"}), 404
    except Exception:
        logger.exception("Failed to remove camera")
        return jsonify({"error": "Failed to remove camera"}), 500


@camera_bp.route("/camera-view/<filename>", methods=["GET"])
@optional_jwt
def serve_camera_image(filename):
    denied = require_stream_or_snapshot_auth()
    if denied:
        return denied

    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return jsonify({"error": "Image not found"}), 404

    if getattr(g, "current_user", None):
        org_id = getattr(g, "current_org_id", None)
        if org_id is None:
            return jsonify({"error": "Forbidden"}), 403
        from src.models.camera import Camera
        camera = Camera.query.filter(
            Camera.organization_id == org_id,
            Camera.view.like(f"%/{safe_name}"),
        ).first()
        if not camera:
            return jsonify({"error": "Image not found"}), 404

    try:
        return send_from_directory(IMAGE_DIR, safe_name)
    except (FileNotFoundError, NotFound):
        return jsonify({"error": "Image not found"}), 404


@camera_bp.route("/api/camera/<int:camera_id>/stream", methods=["GET"])
@optional_jwt
def stream_camera(camera_id):
    """
    Live MJPEG view of a camera's detection output. Accepts auth via:
    - Authorization: Bearer <jwt>
    - ?token=<jwt> (for <img> tags that cannot set headers)
    - X-API-Key header / ?api_key= query param (legacy shared key)
    """
    denied = require_stream_or_snapshot_auth()
    if denied:
        return denied

    org_id = getattr(g, "current_org_id", None)
    if getattr(g, "current_user", None) and org_id is None:
        return jsonify({"error": "Forbidden"}), 403

    camera = get_camera_service(camera_id, organization_id=org_id)
    if not camera:
        # Shared API-key path (no JWT user) may look up by id only for the
        # legacy single-tenant demo. JWT users are strictly org-scoped above.
        if getattr(g, "current_user", None):
            return jsonify({"error": "Forbidden"}), 403
        from src.models.camera import Camera
        camera = Camera.query.filter_by(id=camera_id, status="Active").first()
        if not camera:
            return jsonify({"error": "Forbidden"}), 403

    def generate():
        last_sent = None
        idle_since = None
        while True:
            frame_bytes = get_latest_frame(camera_id)

            if frame_bytes is None:
                # Published frames carry a short TTL, so a missing key means the
                # detection task has stopped. End the response instead of
                # holding the socket (and one of the browser's six per-origin
                # connections) open forever re-sending a stale frame.
                if idle_since is None:
                    idle_since = time.time()
                elif time.time() - idle_since > STREAM_IDLE_TIMEOUT:
                    break
                time.sleep(STREAM_POLL_INTERVAL)
                continue

            idle_since = None

            # Polling is faster than the publish rate, so most reads return the
            # frame we already sent. Re-sending it burns bandwidth without
            # changing the picture.
            if frame_bytes == last_sent:
                time.sleep(STREAM_POLL_INTERVAL)
                continue

            last_sent = frame_bytes
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                + frame_bytes + b"\r\n"
            )
            time.sleep(STREAM_POLL_INTERVAL)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")
