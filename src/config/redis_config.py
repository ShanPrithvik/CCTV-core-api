"""Redis connection settings shared by Flask, Celery, and live-frame storage."""

from __future__ import annotations

import os
from urllib.parse import quote, urlsplit, urlunsplit

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def get_redis_url() -> str:
    """Return a Redis URL, injecting ``REDIS_PASSWORD`` when the URL has none.

    ``REDIS_URL`` remains the source of host/port/db. If it already includes
    credentials, it is left unchanged so existing ``redis://:pass@host:6379/0``
    configs keep working.
    """
    url = (os.getenv("REDIS_URL") or DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL
    password = os.getenv("REDIS_PASSWORD", "")
    if not password:
        return url

    parts = urlsplit(url)
    if parts.password is not None:
        return url

    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    user = quote(parts.username or "", safe="")
    secret = quote(password, safe="")
    netloc = f"{user}:{secret}@{host}{port}"
    path = parts.path or "/0"
    return urlunsplit((parts.scheme or "redis", netloc, path, parts.query, parts.fragment))
