"""
Shared helpers for running detection tasks headlessly on a server.

On a desktop with a display, detection tasks can still open a debug window
(set HEADLESS=false). On any server (Docker, a cloud VM, CI, etc.) there is
no display, so by default (HEADLESS=true) frames are published to Redis
instead, where the Flask API streams them to the browser as MJPEG.
"""
import os
from typing import Optional

import cv2

from src.config.redis_config import get_redis_url

_redis_client = None

FRAME_KEY_PREFIX = "camera_frame:"
FRAME_TTL_SECONDS = 10


def is_headless() -> bool:
    return os.getenv("HEADLESS", "true").strip().lower() not in ("0", "false", "no")


def get_redis_client():
    """Lazily create a shared Redis client from REDIS_URL."""
    global _redis_client
    if _redis_client is None:
        import redis

        redis_url = get_redis_url()
        _redis_client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def frame_key(camera_id) -> str:
    return f"{FRAME_KEY_PREFIX}{camera_id}"


def publish_frame(camera_id, frame, ttl_seconds: int = FRAME_TTL_SECONDS) -> None:
    """Encode a BGR frame as JPEG and publish it to Redis for live viewing."""
    if camera_id is None:
        return
    try:
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return
        client = get_redis_client()
        client.set(frame_key(camera_id), buffer.tobytes(), ex=ttl_seconds)
    except Exception as e:
        print(f"[stream_utils] Failed to publish frame for camera {camera_id}: {e}")


def get_latest_frame(camera_id) -> Optional[bytes]:
    """Read the latest published JPEG frame for a camera, or None if unavailable."""
    try:
        client = get_redis_client()
        return client.get(frame_key(camera_id))
    except Exception as e:
        print(f"[stream_utils] Failed to read latest frame for camera {camera_id}: {e}")
        return None


def display_frame(window_name: str, frame, camera_id=None) -> bool:
    """
    Show a frame. In headless mode, publish it to Redis for the live-view
    endpoint. Otherwise, open a desktop preview window.

    Returns True if the caller should stop the detection loop (user pressed
    'q' in a desktop window). Always False in headless mode.
    """
    if is_headless():
        publish_frame(camera_id, frame)
        return False

    cv2.imshow(window_name, frame)
    return cv2.waitKey(1) & 0xFF == ord("q")


def setup_window(window_name: str, mode=None) -> None:
    """Create a desktop preview window, unless running headless."""
    if is_headless():
        return
    cv2.namedWindow(window_name, mode if mode is not None else cv2.WINDOW_NORMAL)


def teardown_windows() -> None:
    if is_headless():
        return
    cv2.destroyAllWindows()


def alert_beep(frequency: int = 1000, duration_ms: int = 1000) -> None:
    """Best-effort audible alert. No-op headless or on non-Windows systems."""
    if is_headless():
        return
    try:
        import winsound

        winsound.Beep(frequency, duration_ms)
    except Exception:
        pass
