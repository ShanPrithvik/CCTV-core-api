"""Best-effort request rate limiting.

Uses Redis when available (shared across gunicorn workers) and falls back to
an in-process counter so login protection still works without Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)


def _memory_allow(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    with _lock:
        stamps = [t for t in _hits[key] if now - t < window_seconds]
        if len(stamps) >= limit:
            _hits[key] = stamps
            return False
        stamps.append(now)
        _hits[key] = stamps
        return True


def allow(key: str, limit: int, window_seconds: int) -> bool:
    try:
        from src.services.stream_utils import get_redis_client

        client = get_redis_client()
        redis_key = f"rl:{key}"
        current = client.incr(redis_key)
        if current == 1:
            client.expire(redis_key, window_seconds)
        return int(current) <= limit
    except Exception:
        return _memory_allow(key, limit, window_seconds)
