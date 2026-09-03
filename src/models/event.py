from datetime import datetime, timezone

from src.init import db


def utcnow():
    return datetime.now(timezone.utc)


class Event(db.Model):
    __tablename__ = "Event"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("Organization.id"), nullable=False, index=True
    )
    camera_id = db.Column(
        db.Integer, db.ForeignKey("Camera.id"), nullable=False, index=True
    )
    event_type = db.Column(db.String(80), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False, default="MEDIUM", index=True)
    confidence = db.Column(db.Float, nullable=True)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    snapshot_path = db.Column(db.String(1024), nullable=True)
    clip_path = db.Column(db.String(1024), nullable=True)
    event_metadata = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    camera = db.relationship("Camera", lazy="joined")


class Alert(db.Model):
    __tablename__ = "Alert"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("Organization.id"), nullable=False, index=True
    )
    event_id = db.Column(
        db.Integer, db.ForeignKey("Event.id"), nullable=False, unique=True, index=True
    )
    status = db.Column(db.String(20), nullable=False, default="NEW", index=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("User.id"), nullable=True)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey("User.id"), nullable=True)
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    event = db.relationship("Event", lazy="joined")
