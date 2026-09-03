import secrets

from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError

from src.init import db
from src.utils.request_helpers import json_body
from src.models.user import User
from src.models.organization import Organization
from src.models.membership import Membership
from src.auth import create_access_token, jwt_required

auth_bp = Blueprint("auth_bp", __name__)


@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = json_body()
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    org_name = (data.get("organization_name") or "").strip()
    invite_token = (data.get("invite_token") or "").strip()

    if not email or not name or not password:
        return jsonify({"error": "email, name, and password are required"}), 400

    existing = User.query.filter_by(email=email).first()
    if existing and existing.status != 'Pending':
        return jsonify({"error": "Email already registered"}), 409

    user = existing or User(email=email, name=name, status='Active')
    if not existing:
        user.set_password(password)
    else:
        user.name = name
        user.set_password(password)
        user.status = 'Active'

    try:
        db.session.add(user)
        db.session.flush()

        if invite_token:
            membership = Membership.query.filter_by(
                invite_token=invite_token, status='Pending'
            ).first()
            if not membership:
                return jsonify({"error": "Invalid invite token"}), 404

            invited_user = User.query.get(membership.user_id)
            if invited_user and invited_user.email != email:
                return jsonify({"error": "This invite was sent to a different email address"}), 403

            membership.user_id = user.id
            membership.status = 'Active'
            membership.invite_token = None
            org_id = membership.organization_id
        else:
            if not org_name:
                return jsonify({"error": "organization_name or invite_token is required"}), 400

            org = Organization(name=org_name, status='Active')
            db.session.add(org)
            db.session.flush()
            org_id = org.id

            membership = Membership(
                user_id=user.id,
                organization_id=org_id,
                role='Owner',
                status='Active',
            )
            db.session.add(membership)

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Email already registered"}), 409

    from src.utils.serializers import membership_summary
    token = create_access_token(user.id, user.email, user.name, organization_id=org_id)
    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "active_organization_id": org_id,
        },
        "memberships": [
            membership_summary(m)
            for m in Membership.query.filter_by(user_id=user.id, status='Active').all()
        ],
    }), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = json_body()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email, status='Active').first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    primary = (
        Membership.query.filter_by(user_id=user.id, status='Active')
        .order_by(Membership.id.asc())
        .first()
    )
    org_id = primary.organization_id if primary else None

    from src.utils.serializers import membership_summary
    token = create_access_token(user.id, user.email, user.name, organization_id=org_id)
    memberships = [
        membership_summary(m)
        for m in Membership.query.filter_by(user_id=user.id, status='Active').all()
    ]

    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "active_organization_id": org_id,
        },
        "memberships": memberships,
    }), 200


@auth_bp.route("/api/auth/me", methods=["GET"])
@jwt_required
def me():
    from src.utils.serializers import membership_summary
    memberships = [
        membership_summary(m)
        for m in Membership.query.filter_by(user_id=g.current_user.id, status='Active').all()
    ]
    return jsonify({
        "user": {
            "id": g.current_user.id,
            "email": g.current_user.email,
            "name": g.current_user.name,
            "active_organization_id": g.current_org_id,
        },
        "memberships": memberships,
    }), 200
