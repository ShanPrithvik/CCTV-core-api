from flask import request, jsonify, Blueprint, send_from_directory
from src.services.camera_service import add_camera_service, get_cameras_service, remove_camera_service, get_camera_service
from src.models.camera import camera_schema, cameras_schema

camera_bp = Blueprint('camera_bp', __name__)

# 🔧 Path where images are stored (adjust if needed)
IMAGE_DIR = r"D:\CCTV_FE_BE\cctv_snip"

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
    
    # ✅ Route to serve camera view images
@camera_bp.route('/camera-view/<filename>', methods=['GET'])
def serve_camera_image(filename):
    try:
        return send_from_directory(IMAGE_DIR, filename)
    except FileNotFoundError:
        return jsonify({"error": "Image not found"}), 404