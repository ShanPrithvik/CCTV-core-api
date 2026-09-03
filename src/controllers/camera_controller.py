import os
import time
import hmac

from flask import request, jsonify, Blueprint, send_from_directory, Response, g
from werkzeug.exceptions import NotFound
from src.services.camera_service import add_camera_service, get_cameras_service, remove_camera_service, get_camera_service
from src.models.camera import camera_schema, cameras_schema
from src.services.stream_utils import get_latest_frame
from src.services.org_permissions import is_org_admin
from src.auth import jwt_required, optional_jwt, _configured_api_key, _extract_presented_key
import jwt

camera_bp = Blueprint('camera_bp', __name__)

IMAGE_DIR = os.path.abspath(os.getenv("CAMERA_SNAPSHOT_DIR", "cctv_snip"))
STREAM_POLL_INTERVAL = 0.2
STREAM_IDLE_TIMEOUT = 15


@camera_bp.route('/api/camera', methods=['POST'])
@jwt_required
def add_camera():
    data = request.get_json() or {}
    camera_name = data.get('cameraName')
    rtsp_url = data.get('rtsp')
    
    if not camera_name or not rtsp_url:
        return jsonify({"error": "cameraName and rtsp are required"}), 400

    try:
        if not is_org_admin(g.current_org_id):
            return jsonify({"error": "Forbidden"}), 403

        new_camera = add_camera_service(
            camera_name, rtsp_url, organization_id=g.current_org_id
        )

        return jsonify({
            "message": "Camera added successfully",
            "camera": camera_schema.dump(new_camera)
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@camera_bp.route('/api/camera', methods=['GET'])
@jwt_required
def get_cameras():
    try:
        cameras = get_cameras_service(organization_id=g.current_org_id)
        return jsonify(cameras_schema.dump(cameras)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
     
@camera_bp.route('/api/camera/<int:camera_id>', methods=['GET'])
@jwt_required
def get_camera(camera_id):
    try:
        camera = get_camera_service(camera_id, organization_id=getattr(g, "current_org_id", None))
        if not camera:
            return jsonify({"error": "Camera not found"}), 404
        return jsonify(camera_schema.dump(camera)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@camera_bp.route('/api/camera/<int:camera_id>', methods=['DELETE'])
@jwt_required
def remove_camera(camera_id):
    try:
        if not is_org_admin(g.current_org_id):
            return jsonify({"error": "Forbidden"}), 403

        camera = get_camera_service(camera_id, organization_id=getattr(g, "current_org_id", None))
        if not camera:
            return jsonify({"error": "Camera not found"}), 404

        result = remove_camera_service(camera_id)
        if result:
            return jsonify({"message": "Camera removed successfully"}), 200
        else:
            return jsonify({"error": "Camera not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
     
# Route to serve camera view snapshot images
@camera_bp.route('/camera-view/<filename>', methods=['GET'])
@optional_jwt
def serve_camera_image(filename):
    try:
        return send_from_directory(IMAGE_DIR, filename)
    except (FileNotFoundError, NotFound):
        return jsonify({"error": "Image not found"}), 404


@camera_bp.route('/api/camera/<int:camera_id>/stream', methods=['GET'])
@optional_jwt
def stream_camera(camera_id):
    """
    Live MJPEG view of a camera's detection output. Accepts auth via:
    - Authorization: Bearer <jwt>
    - ?token=<jwt> (for <img> tags that cannot set headers)
    - X-API-Key header / ?api_key= query param (legacy shared key)
    """
    current_user = getattr(g, "current_user", None)
    if not current_user:
        expected = _configured_api_key()
        presented = _extract_presented_key()
        if not expected or not presented or not hmac.compare_digest(presented, expected):
            return jsonify({"error": "Unauthorized"}), 401

    camera = get_camera_service(camera_id, organization_id=getattr(g, "current_org_id", None))
    if not camera:
        return jsonify({"error": "Forbidden"}), 403

    def generate():
        last_frame = None
        idle_since = None
        while True:
            frame_bytes = get_latest_frame(camera_id)

            if frame_bytes is None:
                if last_frame is None:
                    time.sleep(STREAM_POLL_INTERVAL)
                    if idle_since is None:
                        idle_since = time.time()
                    elif time.time() - idle_since > STREAM_IDLE_TIMEOUT:
                        break
                    continue
                frame_bytes = last_frame
            else:
                last_frame = frame_bytes
                idle_since = None

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(STREAM_POLL_INTERVAL)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")
