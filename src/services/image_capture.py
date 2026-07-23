import os

# Bound how long FFmpeg (OpenCV's backend) waits when opening/reading a stream,
# so a dead or malicious camera cannot hang the synchronous add-camera request
# indefinitely. FFmpeg's "timeout" option is in microseconds. Must be set before
# cv2 opens any capture, hence at import time.
_STREAM_TIMEOUT_MS = int(os.getenv("STREAM_TIMEOUT_MS", "10000"))
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", f"timeout;{_STREAM_TIMEOUT_MS * 1000}"
)

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
    # Open the RTSP stream via the FFmpeg backend so OPENCV_FFMPEG_CAPTURE_OPTIONS
    # (the timeout set above) applies.
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
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
