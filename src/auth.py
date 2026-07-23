"""Optional shared API-key authentication.

Behaviour
---------
* If ``API_KEY`` is unset / empty → auth is disabled (local demo stays open).
* If ``API_KEY`` is set → every non-exempt request must present a matching key via:

  - ``X-API-Key: <key>`` header, or
  - ``Authorization: Bearer <key>`` header, or
  - ``?api_key=<key>`` query parameter (needed for ``<img>`` / MJPEG URLs,
    which cannot set custom headers).

This is intentionally a single shared secret, not multi-user identity. It is a
Phase-1 gate so a public tunnel is not a fully open control plane. Replace with
OIDC/JWT + RBAC before any enterprise deployment.
"""

from __future__ import annotations

import hmac
import os

from flask import jsonify, request


# Paths that stay reachable without a key even when API_KEY is configured.
# Health probes must work for load balancers / orchestrators.
EXEMPT_PATHS = frozenset({"/", "/healthz", "/readyz"})
EXEMPT_PREFIXES = ("/static/",)


def _configured_api_key() -> str:
    return (os.getenv("API_KEY") or "").strip()


def auth_enabled() -> bool:
    return bool(_configured_api_key())


def _extract_presented_key():
    header_key = request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    query_key = request.args.get("api_key")
    if query_key:
        return query_key.strip()

    return None


def register_api_key_auth(app):
    """Install a ``before_request`` hook that enforces ``API_KEY`` when set."""

    @app.before_request
    def require_api_key():
        expected = _configured_api_key()
        if not expected:
            return None

        # Browsers send CORS preflight OPTIONS without custom headers (no
        # X-API-Key). Must allow them through so flask-cors can answer; the
        # real GET/POST that follows still requires the key.
        if request.method == "OPTIONS":
            return None

        path = request.path or "/"
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return None

        presented = _extract_presented_key()
        if presented is None or not hmac.compare_digest(presented, expected):
            return jsonify({
                "error": "Unauthorized",
                "hint": "Provide a valid API key via X-API-Key, Authorization: Bearer, or ?api_key=",
            }), 401

        return None
