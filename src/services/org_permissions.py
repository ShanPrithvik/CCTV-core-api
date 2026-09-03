"""Org-scoped permission checks shared by camera and rule controllers."""

import flask

from src.models.membership import Membership


def current_user():
    return getattr(flask.g, "current_user", None)


def current_org_id():
    return getattr(flask.g, "current_org_id", None)


def is_org_member(org_id) -> bool:
    user = current_user()
    if not user or org_id is None:
        return False
    m = Membership.query.filter_by(
        user_id=user.id, organization_id=org_id, status='Active'
    ).first()
    return bool(m)


def is_org_admin(org_id) -> bool:
    user = current_user()
    if not user or org_id is None:
        return False
    m = Membership.query.filter_by(
        user_id=user.id, organization_id=org_id, status='Active'
    ).first()
    return bool(m and m.role in ('Owner', 'Admin'))
