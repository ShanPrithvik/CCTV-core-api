"""Security helpers for handling camera stream URLs.

Two concerns are addressed here:

1. SSRF mitigation for the URL a client hands us (which is later opened by
   OpenCV/FFmpeg): restrict the scheme to an allow-list and, optionally, block
   private / loopback / link-local / reserved network targets.

2. Credential hygiene: RTSP URLs commonly embed ``user:password@host``. We must
   never echo the password back through the API, so ``mask_credentials`` is used
   at serialization time.

The private-target block defaults to OFF so the local demo
(``rtsp://localhost:8554/demo``) keeps working out of the box. Set
``BLOCK_PRIVATE_STREAM_TARGETS=true`` in any real deployment.
"""

import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit


def _allowed_schemes():
    raw = os.getenv("ALLOWED_STREAM_SCHEMES", "rtsp,rtsps")
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def _block_private_targets():
    return os.getenv("BLOCK_PRIVATE_STREAM_TARGETS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_disallowed_ip(ip_str):
    """Return True for addresses we never want the server to dial."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_stream_url(url):
    """Validate a client-supplied stream URL.

    Raises ``ValueError`` when the URL is malformed, uses a disallowed scheme,
    or (when ``BLOCK_PRIVATE_STREAM_TARGETS`` is enabled) resolves to a
    private/loopback/link-local/reserved address.
    """
    if not url or not str(url).strip():
        raise ValueError("Stream URL is required")

    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "").lower()

    if scheme not in _allowed_schemes():
        allowed = ", ".join(sorted(_allowed_schemes()))
        raise ValueError(f"Unsupported stream URL scheme '{scheme}'. Allowed: {allowed}")

    host = parts.hostname
    if not host:
        raise ValueError("Stream URL must include a host")

    if not _block_private_targets():
        return url

    # Resolve every address the host maps to and reject if any is disallowed,
    # which also defends against a hostname that points at a private range.
    try:
        infos = socket.getaddrinfo(host, parts.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve stream host '{host}': {exc}")

    for info in infos:
        ip_str = info[4][0]
        if _is_disallowed_ip(ip_str):
            raise ValueError(
                "Stream URL target is not allowed (private/loopback/link-local address)"
            )

    return url


def mask_credentials(url):
    """Return ``url`` with any embedded ``user:password`` replaced by ``***``.

    Used for API responses and logs so camera credentials are never disclosed.
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    if not parts.hostname or (parts.username is None and parts.password is None):
        return url

    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    masked_netloc = f"***:***@{host}" if parts.username or parts.password else host
    return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))
