from src.models.camera import Camera, db
from src.services.image_capture import capture_rtsp_screenshot
from src.services.local_storage import save_to_local_storage
from src.services.stream_security import validate_stream_url
from src.utils.validation import is_safe_camera_name, snapshot_filename

import os


def add_camera_service(camera_name, rtsp_url, organization_id=None):
    """Creates a new Camera record and commits it to the database."""
    if organization_id is None:
        raise ValueError("organization_id is required")
    if not is_safe_camera_name(camera_name):
        raise ValueError("cameraName must be 1-50 characters (letters, numbers, spaces, . _ -)")

    validate_stream_url(rtsp_url)

    file_name = snapshot_filename(camera_name)
    local_directory = os.getenv("CAMERA_SNAPSHOT_DIR", "cctv_snip")
    base_url = os.getenv("API_BASE_URL", "http://localhost:5000").rstrip("/")
    camera_view_url = f"{base_url}/camera-view/{file_name}"

    camera_view_byte = capture_rtsp_screenshot(rtsp_url)
    save_to_local_storage(camera_view_byte, file_name, save_directory=local_directory)

    new_camera = Camera(
        camera_name=camera_name.strip(),
        rtsp_url=rtsp_url,
        view=camera_view_url,
        organization_id=organization_id,
    )
    db.session.add(new_camera)
    db.session.commit()

    return new_camera


def get_cameras_service(organization_id=None):
    if organization_id is None:
        return []
    return Camera.query.filter_by(status="Active", organization_id=organization_id).all()


def get_camera_service(camera_id, organization_id=None):
    if organization_id is None:
        return None
    return Camera.query.filter_by(
        id=camera_id, organization_id=organization_id
    ).first()


def remove_camera_service(camera_id, organization_id=None):
    camera = get_camera_service(camera_id, organization_id=organization_id)
    if not camera:
        return False
    camera.status = "Inactive"
    db.session.commit()
    return True
