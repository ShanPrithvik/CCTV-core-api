from src.models.camera import Camera, db
from src.services.image_capture import capture_rtsp_screenshot
from src.services.local_storage import save_to_local_storage
from src.services.stream_security import validate_stream_url

import os


def add_camera_service(camera_name, rtsp_url):
    """Creates a new Camera record and commits it to the database."""
    # Reject malformed / disallowed stream URLs before we ever open them (SSRF
    # mitigation). Raises ValueError, which the controller maps to a 400.
    validate_stream_url(rtsp_url)

    # Local file name and local file path
    file_name = f"{camera_name}.png"
    local_directory = os.getenv("CAMERA_SNAPSHOT_DIR", "cctv_snip")
    base_url = os.getenv("API_BASE_URL", "http://localhost:5000")
    camera_view_url = f"{base_url}/camera-view/{camera_name}.png"

    # Create database record
    new_camera = Camera(camera_name=camera_name, rtsp_url=rtsp_url, view=camera_view_url)
    db.session.add(new_camera)
    db.session.commit()

    # Capture and save screenshot locally
    camera_view_byte = capture_rtsp_screenshot(rtsp_url)
    save_to_local_storage(camera_view_byte, file_name, save_directory=local_directory)

    return new_camera

def get_cameras_service():
    return Camera.query.filter_by(status='Active').all() 

def get_camera_service(camera_id):
    return Camera.query.get(camera_id)


def remove_camera_service(camera_id):
    camera = Camera.query.get(camera_id)
    if not camera:
        return False  
    camera.status = 'Inactive'
    db.session.commit()
    return True
