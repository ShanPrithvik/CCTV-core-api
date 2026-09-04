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

# Detection runs on 1280x720 frames, but a q80 JPEG of one is ~250 KB, which is
# ~2.5 MB/s per viewer at the rate tasks publish. The live view is a monitoring
# preview, not the recorded evidence (clips are saved at full size), so downscale
# and recompress before publishing.
STREAM_MAX_WIDTH = int(os.getenv("STREAM_MAX_WIDTH", "960"))
STREAM_JPEG_QUALITY = int(os.getenv("STREAM_JPEG_QUALITY", "65"))

# Several rules can watch one camera, and each decodes the stream at its own
# offset. If they all write the same frame key the live view interleaves images
# from different points in the video, which looks like the picture jumping back
# and forth. Elect one publisher per camera instead: detection and alerting
# still run for every rule, only the preview picks an owner. The claim expires
# so another task takes over if the owner dies.
FRAME_OWNER_PREFIX = "camera_frame_owner:"
FRAME_OWNER_TTL_SECONDS = 5
RULES_EPOCH_PREFIX = "camera_rules_epoch:"
PIPELINE_TASK_PREFIX = "camera_pipeline_task:"


def _owns_live_view(client, camera_id, owner: str) -> bool:
    key = f"{FRAME_OWNER_PREFIX}{camera_id}"
    if client.set(key, owner, nx=True, ex=FRAME_OWNER_TTL_SECONDS):
        return True
    current = client.get(key)
    if current is not None and current.decode() == owner:
        client.expire(key, FRAME_OWNER_TTL_SECONDS)
        return True
    return False


def bump_rules_epoch(camera_id) -> None:
    """Wake the camera pipeline so it reloads Active rules from the database."""
    try:
        get_redis_client().incr(f"{RULES_EPOCH_PREFIX}{camera_id}")
    except Exception:
        pass


def read_rules_epoch(camera_id):
    try:
        value = get_redis_client().get(f"{RULES_EPOCH_PREFIX}{camera_id}")
        return int(value) if value is not None else 0
    except Exception:
        return None


def get_camera_pipeline_task_id(camera_id):
    try:
        value = get_redis_client().get(f"{PIPELINE_TASK_PREFIX}{camera_id}")
        return value.decode() if value else None
    except Exception:
        return None


def set_camera_pipeline_task_id(camera_id, task_id: str) -> None:
    try:
        get_redis_client().set(f"{PIPELINE_TASK_PREFIX}{camera_id}", task_id)
    except Exception:
        pass


def clear_camera_pipeline_task_id(camera_id) -> None:
    try:
        get_redis_client().delete(f"{PIPELINE_TASK_PREFIX}{camera_id}")
    except Exception:
        pass


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


def publish_frame(
    camera_id, frame, ttl_seconds: int = FRAME_TTL_SECONDS, owner: str = None
) -> None:
    """Encode a BGR frame as JPEG and publish it to Redis for live viewing.

    `owner` identifies the calling task so that only one of several rules
    watching a camera drives its live view. Passing None publishes
    unconditionally.
    """
    if camera_id is None:
        return
    try:
        client = get_redis_client()
        # Checked before encoding: a task that does not own the live view
        # should not pay for the resize and JPEG compression at all.
        if owner is not None and not _owns_live_view(client, camera_id, owner):
            return

        height, width = frame.shape[:2]
        if STREAM_MAX_WIDTH > 0 and width > STREAM_MAX_WIDTH:
            scale = STREAM_MAX_WIDTH / float(width)
            frame = cv2.resize(
                frame,
                (STREAM_MAX_WIDTH, max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        ok, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
        )
        if not ok:
            return
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


def display_frame(window_name: str, frame, camera_id=None, owner: str = None) -> bool:
    """
    Show a frame. In headless mode, publish it to Redis for the live-view
    endpoint. Otherwise, open a desktop preview window.

    Returns True if the caller should stop the detection loop (user pressed
    'q' in a desktop window). Always False in headless mode.
    """
    if is_headless():
        publish_frame(camera_id, frame, owner=owner)
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
