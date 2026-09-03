"""Shared input validation helpers."""

from __future__ import annotations

import re

from werkzeug.utils import secure_filename

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_CAMERA_NAME = re.compile(r"^[\w \-.]{1,50}$")


def is_valid_email(email: str) -> bool:
    return bool(email) and len(email) <= 255 and bool(_EMAIL_RE.match(email))


def password_is_strong_enough(password: str) -> bool:
    return isinstance(password, str) and 8 <= len(password) <= 256


def parse_positive_int(value, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def snapshot_filename(camera_name: str) -> str:
    """Return a filesystem-safe snapshot name derived from the camera name."""
    cleaned = secure_filename((camera_name or "").strip().replace(" ", "_"))
    if not cleaned:
        cleaned = "camera"
    if not cleaned.lower().endswith(".png"):
        cleaned = f"{cleaned}.png"
    return cleaned


def is_safe_camera_name(camera_name: str) -> bool:
    return bool(camera_name) and bool(_SAFE_CAMERA_NAME.match(camera_name.strip()))
