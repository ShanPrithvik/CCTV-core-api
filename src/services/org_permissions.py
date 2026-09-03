"""Org-scoped permission checks shared by camera and rule controllers."""

from flask import g, jsonify

from src.models.membership import Membership


def current_user():
    return getattr(g, "current_user", None)


def current_org_id():
    return getattr(g, "current_org_id", None)


def is_org_member(org_id) -> bool:
    user = current_user()
    if not user or org_id is None:
        return False
    try:
        org_id = int(org_id)
    except (TypeError, ValueError):
        return False
    m = Membership.query.filter_by(
        user_id=user.id, organization_id=org_id, status="Active"
    ).first()
    return bool(m)


def is_org_admin(org_id) -> bool:
    user = current_user()
    if not user or org_id is None:
        return False
    try:
        org_id = int(org_id)
    except (TypeError, ValueError):
        return False
    m = Membership.query.filter_by(
        user_id=user.id, organization_id=org_id, status="Active"
    ).first()
    return bool(m and m.role in ("Owner", "Admin"))


def is_org_owner(org_id) -> bool:
    user = current_user()
    if not user or org_id is None:
        return False
    try:
        org_id = int(org_id)
    except (TypeError, ValueError):
        return False
    m = Membership.query.filter_by(
        user_id=user.id, organization_id=org_id, status="Active"
    ).first()
    return bool(m and m.role == "Owner")


def camera_visible_in_org(camera, org_id) -> bool:
    """True only when the camera is explicitly owned by this organization."""
    if camera is None or org_id is None or camera.organization_id is None:
        return False
    try:
        return int(camera.organization_id) == int(org_id)
    except (TypeError, ValueError):
        return False


def require_active_org():
    org_id = current_org_id()
    if org_id is None:
        return jsonify({
            "error": "No active organization. Switch organization or create one first.",
        }), 403
    if not is_org_member(org_id):
        return jsonify({"error": "Forbidden"}), 403
    return None
