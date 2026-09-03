"""Authentication layer.

Combines two mechanisms:
1. Optional shared API-key gate (``API_KEY`` env var) for backward compatibility.
2. JWT Bearer auth for multi-user identity and org scoping.

If both are present, JWT wins for authenticated endpoints; ``API_KEY`` only
allows requests through when no Bearer token is supplied.
"""

from __future__ import annotations

import datetime
import hmac
import os
from functools import wraps

from flask import jsonify, request, g
import jwt


# Paths that stay reachable without auth.
EXEMPT_PATHS = frozenset({"/", "/healthz", "/readyz"})
EXEMPT_PREFIXES = ("/static/",)

JWT_ALGORITHM = "HS256"


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


def _extract_bearer_token():
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    query_token = request.args.get("token")
    if query_token:
        return query_token.strip()
    return None


def _get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if not secret:
        return ""
    return secret


def _has_valid_jwt() -> bool:
    token = _extract_bearer_token()
    if not token:
        return False
    secret = _get_jwt_secret()
    if not secret:
        return False
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return True
    except Exception:
        return False


def create_access_token(user_id: int, email: str, name: str, organization_id: int | None = None) -> str:
    """Return a signed JWT for the given user."""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "org": organization_id,
        "iat": now,
        "exp": now + datetime.timedelta(hours=12),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])


def register_api_key_auth(app):
    """Install a ``before_request`` hook that enforces ``API_KEY`` when set."""

    @app.before_request
    def require_api_key():
        expected = _configured_api_key()
        if not expected:
            return None

        if request.method == "OPTIONS":
            return None

        path = request.path or "/"
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return None

        if _has_valid_jwt():
            return None

        presented = _extract_presented_key()
        if presented is None or not hmac.compare_digest(presented, expected):
            return jsonify({
                "error": "Unauthorized",
                "hint": "Provide a valid API key via X-API-Key, Authorization: Bearer, or ?api_key=",
            }), 401

        return None


def jwt_required(fn):
    """Decorator that validates JWT and sets ``g.current_user`` and ``g.current_org_id``."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return jsonify({"error": "Missing token"}), 401

        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        from src.models.user import User
        user = User.query.filter_by(id=int(payload["sub"]), status='Active').first()
        if not user:
            return jsonify({"error": "User not found"}), 401

        g.current_user = user
        g.current_org_id = payload.get("org")
        return fn(*args, **kwargs)

    return wrapper


def optional_jwt(fn):
    """Like ``jwt_required`` but does not reject missing/invalid tokens."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if token:
            try:
                payload = decode_token(token)
                from src.models.user import User
                user = User.query.filter_by(id=int(payload["sub"]), status='Active').first()
                if user:
                    g.current_user = user
                    g.current_org_id = payload.get("org")
            except Exception:
                pass
        return fn(*args, **kwargs)

    return wrapper
