from flask import Blueprint, request, jsonify, g
import os
import secrets
from sqlalchemy.exc import IntegrityError

from src.init import db
from src.models.organization import Organization
from src.models.membership import Membership
from src.models.user import User
from src.auth import jwt_required, create_access_token
from src.services.email_service import send_invite_email
from src.services.org_permissions import is_org_admin, is_org_owner
from src.utils.request_helpers import json_body
from src.utils.validation import is_valid_email

membership_bp = Blueprint("membership_bp", __name__)
ALLOWED_ROLES = ("Owner", "Admin", "Member")


def _current_user():
    return g.current_user


def _parse_org_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _last_owner_guard(organization_id: int, exclude_membership_id: int | None = None) -> bool:
    """Return True if removing/demoting the given membership would leave the org with zero Owners."""
    query = Membership.query.filter_by(
        organization_id=organization_id, role="Owner", status="Active"
    )
    if exclude_membership_id is not None:
        query = query.filter(Membership.id != exclude_membership_id)
    return query.count() == 0


def _invite_link(token: str) -> str:
    public_app_url = (os.getenv("PUBLIC_APP_URL") or os.getenv("API_BASE_URL") or "http://localhost:5000").rstrip("/")
    return f"{public_app_url}/accept-invite?token={token}"


@membership_bp.route("/api/org", methods=["POST"])
@jwt_required
def create_organization():
    data = json_body()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > 255:
        return jsonify({"error": "name is too long"}), 400

    user = _current_user()

    org = Organization(name=name, status="Active")
    db.session.add(org)
    db.session.flush()

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role="Owner",
        status="Active",
    )
    db.session.add(membership)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Failed to create organization"}), 500

    return jsonify({
        "id": org.id,
        "name": org.name,
        "status": org.status,
        "role": membership.role,
    }), 201


@membership_bp.route("/api/org/members", methods=["POST"])
@jwt_required
def invite_member():
    user = _current_user()

    data = json_body()
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "Member").strip()
    organization_id = _parse_org_id(data.get("organization_id"))

    if not email or not organization_id:
        return jsonify({"error": "email and organization_id are required"}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Invalid email address"}), 400

    if role not in ALLOWED_ROLES:
        return jsonify({"error": "role must be Owner, Admin, or Member"}), 400

    if not is_org_admin(organization_id):
        return jsonify({"error": "Forbidden"}), 403

    if role == "Owner" and not is_org_owner(organization_id):
        return jsonify({"error": "Only an Owner can invite another Owner"}), 403

    target_user = User.query.filter_by(email=email).first()
    if not target_user:
        target_user = User(email=email, name=email.split("@")[0], status="Pending")
        target_user.password_hash = ""
        db.session.add(target_user)
        db.session.flush()

    existing = Membership.query.filter_by(
        user_id=target_user.id, organization_id=organization_id
    ).first()
    if existing and existing.status == "Active":
        return jsonify({"error": "User is already a member"}), 409

    invite_token = secrets.token_urlsafe(32)
    if existing:
        existing.status = "Pending"
        existing.role = role
        existing.invite_token = invite_token
        membership = existing
    else:
        membership = Membership(
            user_id=target_user.id,
            organization_id=organization_id,
            role=role,
            status="Pending",
            invite_token=invite_token,
        )
        db.session.add(membership)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Failed to invite member"}), 500

    org = db.session.get(Organization, organization_id)
    org_name = org.name if org else "the organization"
    send_invite_email(
        to_email=target_user.email,
        invite_token=invite_token,
        organization_name=org_name,
        inviter_name=user.name,
    )

    return jsonify({
        "id": membership.id,
        "user_id": target_user.id,
        "email": target_user.email,
        "name": target_user.name,
        "organization_id": organization_id,
        "role": role,
        "status": "Pending",
        "invite_token": invite_token,
        "invite_link": _invite_link(invite_token),
    }), 201


@membership_bp.route("/api/org/members/<int:membership_id>", methods=["PATCH"])
@jwt_required
def update_member_role(membership_id: int):
    membership = db.session.get(Membership, membership_id)
    if not membership:
        return jsonify({"error": "Membership not found"}), 404

    if not is_org_admin(membership.organization_id):
        return jsonify({"error": "Forbidden"}), 403

    data = json_body()
    role = data.get("role")
    if role not in ALLOWED_ROLES:
        return jsonify({"error": "role must be Owner, Admin, or Member"}), 400

    if role == "Owner" and not is_org_owner(membership.organization_id):
        return jsonify({"error": "Only an Owner can assign the Owner role"}), 403

    if membership.role == "Owner" and role != "Owner":
        if _last_owner_guard(membership.organization_id, exclude_membership_id=membership.id):
            return jsonify({"error": "Cannot demote the last Owner"}), 409

    membership.role = role
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to update role"}), 500

    from src.utils.serializers import membership_summary
    return jsonify(membership_summary(membership)), 200


@membership_bp.route("/api/org/members/<int:membership_id>", methods=["DELETE"])
@jwt_required
def remove_member(membership_id: int):
    membership = db.session.get(Membership, membership_id)
    if not membership:
        return jsonify({"error": "Membership not found"}), 404

    if not is_org_admin(membership.organization_id):
        return jsonify({"error": "Forbidden"}), 403

    if membership.role == "Owner":
        if _last_owner_guard(membership.organization_id, exclude_membership_id=membership.id):
            return jsonify({"error": "Cannot remove the last Owner"}), 409

    membership.status = "Inactive"
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to remove member"}), 500

    from src.utils.serializers import membership_summary
    return jsonify({"message": "Member removed", "membership": membership_summary(membership)}), 200


@membership_bp.route("/api/org/members", methods=["GET"])
@jwt_required
def list_members():
    org_id = request.args.get("organization_id", type=int)
    if not org_id:
        return jsonify({"error": "organization_id is required"}), 400

    if not is_org_admin(org_id):
        return jsonify({"error": "Forbidden"}), 403

    members = (
        Membership.query.filter_by(organization_id=org_id, status="Active")
        .join(User, Membership.user_id == User.id)
        .all()
    )

    from src.utils.serializers import membership_summary
    return jsonify([membership_summary(m) for m in members]), 200


@membership_bp.route("/api/org", methods=["GET"])
@jwt_required
def list_organizations():
    user = _current_user()

    memberships = Membership.query.filter_by(user_id=user.id, status="Active").all()
    return jsonify([
        {
            "id": m.organization_id,
            "name": m.organization.name,
            "status": m.organization.status,
            "role": m.role,
        }
        for m in memberships
    ]), 200


@membership_bp.route("/api/org/<int:organization_id>/switch", methods=["POST"])
@jwt_required
def switch_organization(organization_id: int):
    user = _current_user()

    membership = Membership.query.filter_by(
        user_id=user.id, organization_id=organization_id, status="Active"
    ).first()
    if not membership:
        return jsonify({"error": "Not a member of this organization"}), 403

    token = create_access_token(user.id, user.email, user.name, organization_id=organization_id)
    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "active_organization_id": organization_id,
        },
    }), 200


@membership_bp.route("/api/org/invites", methods=["GET"])
@jwt_required
def list_pending_invites():
    org_id = request.args.get("organization_id", type=int)
    if not org_id:
        return jsonify({"error": "organization_id is required"}), 400

    if not is_org_admin(org_id):
        return jsonify({"error": "Forbidden"}), 403

    invites = (
        Membership.query.filter_by(organization_id=org_id, status="Pending")
        .join(User, Membership.user_id == User.id)
        .all()
    )

    return jsonify([
        {
            "id": m.id,
            "user_id": m.user_id,
            "email": m.user.email,
            "name": m.user.name,
            "organization_id": m.organization_id,
            "role": m.role,
            "status": m.status,
        }
        for m in invites
    ]), 200
