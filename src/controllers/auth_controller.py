import logging
import os

from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError

from src.init import db
from src.utils.request_helpers import json_body
from src.utils.validation import is_valid_email, password_is_strong_enough
from src.models.user import User
from src.models.organization import Organization
from src.models.membership import Membership
from src.auth import create_access_token, jwt_required, jwt_configured
from src.services import rate_limit

auth_bp = Blueprint("auth_bp", __name__)
logger = logging.getLogger("cctv.auth")

AUTH_RATE_LIMIT = int(os.getenv("AUTH_RATE_LIMIT", "10"))
AUTH_RATE_WINDOW = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", "300"))


def _client_key(prefix: str, extra: str = "") -> str:
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").strip().lower() in ("1", "true", "yes"):
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown").split(",")[0].strip()
    else:
        ip = request.remote_addr or "unknown"
    return f"{prefix}:{ip}:{extra}"


def _auth_limited(prefix: str, extra: str = ""):
    if not rate_limit.allow(_client_key(prefix, extra), AUTH_RATE_LIMIT, AUTH_RATE_WINDOW):
        return jsonify({"error": "Too many attempts. Try again later."}), 429
    return None


def _user_payload(user, org_id, memberships):
    from src.utils.serializers import membership_summary
    return {
        "token": create_access_token(user.id, user.email, user.name, organization_id=org_id),
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "active_organization_id": org_id,
        },
        "memberships": [membership_summary(m) for m in memberships],
    }


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = json_body()
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    org_name = (data.get("organization_name") or "").strip()
    invite_token = (data.get("invite_token") or "").strip()

    if not jwt_configured():
        return jsonify({"error": "Authentication is not configured"}), 503

    limited = _auth_limited("register", email)
    if limited:
        return limited

    if not email or not name or not password:
        return jsonify({"error": "email, name, and password are required"}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Invalid email address"}), 400
    if not password_is_strong_enough(password):
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if len(name) > 255:
        return jsonify({"error": "name is too long"}), 400

    existing = User.query.filter_by(email=email).first()
    if existing and existing.status != "Pending":
        return jsonify({"error": "Email already registered"}), 409

    # An invited (Pending) account can only be claimed with the matching invite.
    if existing and existing.status == "Pending" and not invite_token:
        return jsonify({"error": "This email has a pending invite. Register with invite_token."}), 409

    user = existing or User(email=email, name=name, status="Active")
    user.name = name
    user.set_password(password)
    user.status = "Active"

    try:
        db.session.add(user)
        db.session.flush()

        if invite_token:
            membership = Membership.query.filter_by(
                invite_token=invite_token, status="Pending"
            ).first()
            if not membership:
                db.session.rollback()
                return jsonify({"error": "Invalid invite token"}), 404

            invited_user = db.session.get(User, membership.user_id)
            if invited_user and invited_user.email != email:
                db.session.rollback()
                return jsonify({"error": "This invite was sent to a different email address"}), 403

            membership.user_id = user.id
            membership.status = "Active"
            membership.invite_token = None
            org_id = membership.organization_id
        else:
            if not org_name:
                db.session.rollback()
                return jsonify({"error": "organization_name or invite_token is required"}), 400
            if len(org_name) > 255:
                db.session.rollback()
                return jsonify({"error": "organization_name is too long"}), 400

            org = Organization(name=org_name, status="Active")
            db.session.add(org)
            db.session.flush()
            org_id = org.id

            membership = Membership(
                user_id=user.id,
                organization_id=org_id,
                role="Owner",
                status="Active",
            )
            db.session.add(membership)

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Email already registered"}), 409
    except RuntimeError:
        db.session.rollback()
        logger.exception("Registration failed")
        return jsonify({"error": "Authentication is not configured"}), 500

    memberships = Membership.query.filter_by(user_id=user.id, status="Active").all()
    return jsonify(_user_payload(user, org_id, memberships)), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = json_body()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not jwt_configured():
        return jsonify({"error": "Authentication is not configured"}), 503

    limited = _auth_limited("login", email)
    if limited:
        return limited

    user = User.query.filter_by(email=email, status="Active").first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    primary = (
        Membership.query.filter_by(user_id=user.id, status="Active")
        .order_by(Membership.id.asc())
        .first()
    )
    org_id = primary.organization_id if primary else None
    memberships = Membership.query.filter_by(user_id=user.id, status="Active").all()

    try:
        return jsonify(_user_payload(user, org_id, memberships)), 200
    except RuntimeError:
        logger.exception("Login token issuance failed")
        return jsonify({"error": "Authentication is not configured"}), 500


@auth_bp.route("/api/auth/me", methods=["GET"])
@jwt_required
def me():
    memberships = Membership.query.filter_by(user_id=g.current_user.id, status="Active").all()
    from src.utils.serializers import membership_summary
    return jsonify({
        "user": {
            "id": g.current_user.id,
            "email": g.current_user.email,
            "name": g.current_user.name,
            "active_organization_id": g.current_org_id,
        },
        "memberships": [membership_summary(m) for m in memberships],
    }), 200
