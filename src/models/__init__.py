from ..init import db

from .camera import Camera, camera_schema, cameras_schema
from .ruleConfig import RuleConfig
from .ruleTypes import RuleTypes
from .user import User, user_schema, users_schema
from .organization import Organization, organization_schema, organizations_schema
from .membership import Membership, membership_schema, memberships_schema

__all__ = [
    "Camera",
    "camera_schema",
    "cameras_schema",
    "RuleConfig",
    "RuleTypes",
    "User",
    "user_schema",
    "users_schema",
    "Organization",
    "organization_schema",
    "organizations_schema",
    "Membership",
    "membership_schema",
    "memberships_schema",
]

# Relationships that cross model files, added after all classes exist to
# avoid circular-import mapper errors during app startup.
User.memberships = db.relationship('Membership', backref='user', lazy=True)
Organization.memberships = db.relationship('Membership', backref='organization', lazy=True)
