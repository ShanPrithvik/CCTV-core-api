import cv2
import numpy as np
from io import BytesIO
from PIL import Image

def capture_rtsp_screenshot(rtsp_url):
    """
    Captures a screenshot from an RTSP video stream, resizes it to 720p (1280x720), 
    and returns it as a BytesIO object.

    Args:
        rtsp_url (str): The RTSP URL of the camera.

    Returns:
        BytesIO: The screenshot image in BytesIO format.
    """
    # Open the RTSP stream
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        raise RuntimeError(f"Error: Unable to open video stream from {rtsp_url}")

    # Read a single frame
    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise RuntimeError("Error: Unable to capture frame from RTSP stream")

    # Resize to 720p (1280x720)
    frame_resized = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(frame_rgb)

    # Save the image to a BytesIO object
    img_io = BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)

    return img_io
