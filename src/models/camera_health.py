from datetime import datetime, timezone

from src.init import db


def utcnow():
    return datetime.now(timezone.utc)


class CameraHealth(db.Model):
    __tablename__ = "CameraHealth"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("Organization.id"), nullable=False, index=True
    )
    camera_id = db.Column(
        db.Integer, db.ForeignKey("Camera.id"), nullable=False, unique=True, index=True
    )
    status = db.Column(db.String(20), nullable=False, default="UNKNOWN", index=True)
    source = db.Column(db.String(40), nullable=False, default="analytics_frame")
    last_frame_at = db.Column(db.DateTime(timezone=True), nullable=True)
    checked_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    detail = db.Column(db.JSON, nullable=False, default=dict)

    camera = db.relationship("Camera", lazy="joined")
