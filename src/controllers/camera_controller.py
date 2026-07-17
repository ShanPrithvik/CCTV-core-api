import os
import time

from flask import request, jsonify, Blueprint, send_from_directory, Response
from werkzeug.exceptions import NotFound
from src.services.camera_service import add_camera_service, get_cameras_service, remove_camera_service, get_camera_service
from src.models.camera import camera_schema, cameras_schema
from src.services.stream_utils import get_latest_frame

camera_bp = Blueprint('camera_bp', __name__)

# Path where camera snapshots are stored (env-configurable; defaults to a
# local folder so this works out of the box on any OS). Resolved to an
# absolute path (relative to the process CWD, matching how local_storage.py
# writes files) so Flask's send_from_directory doesn't instead resolve it
# relative to app.root_path (the src/ package dir), which would never match.
IMAGE_DIR = os.path.abspath(os.getenv("CAMERA_SNAPSHOT_DIR", "cctv_snip"))

# How long the MJPEG stream waits for a new frame before giving up (seconds).
STREAM_POLL_INTERVAL = 0.2
STREAM_IDLE_TIMEOUT = 15

@camera_bp.route('/api/camera', methods=['POST'])
def add_camera():
    data = request.get_json() or {}
    camera_name = data.get('cameraName')
    rtsp_url = data.get('rtsp')
    
    if not camera_name or not rtsp_url:
        return jsonify({"error": "cameraName and rtsp are required"}), 400

    try:
        new_camera = add_camera_service(camera_name, rtsp_url)

        return jsonify({
            "message": "Camera added successfully",
            "camera": camera_schema.dump(new_camera)
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@camera_bp.route('/api/camera', methods=['GET'])
def get_cameras():
    try:
        cameras = get_cameras_service()
        return jsonify(cameras_schema.dump(cameras)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@camera_bp.route('/api/camera/<int:camera_id>', methods=['GET'])
def get_camera(camera_id):
    try:
        print (camera_id)
        cameras = get_camera_service(camera_id)
        return jsonify(camera_schema.dump(cameras)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@camera_bp.route('/api/camera/<int:camera_id>', methods=['DELETE'])
def remove_camera(camera_id):
    try:
        result = remove_camera_service(camera_id)
        if result:
            return jsonify({"message": "Camera removed successfully"}), 200
        else:
            return jsonify({"error": "Camera not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    # Route to serve camera view snapshot images
@camera_bp.route('/camera-view/<filename>', methods=['GET'])
def serve_camera_image(filename):
    try:
        return send_from_directory(IMAGE_DIR, filename)
    except (FileNotFoundError, NotFound):
        return jsonify({"error": "Image not found"}), 404


@camera_bp.route('/api/camera/<int:camera_id>/stream', methods=['GET'])
def stream_camera(camera_id):
    """
    Live MJPEG view of a camera's detection output. While a detection rule
    is running for this camera, the worker publishes annotated frames (ROI,
    bounding boxes, alert overlays) to Redis; this endpoint reads the latest
    one and streams it to the browser as multipart/x-mixed-replace, which
    a plain <img> tag can render directly.
    """
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
                        # No rule has produced a frame yet; stop holding the connection open.
                        break
                    continue
                # Reuse the last frame briefly if the worker missed a beat.
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
