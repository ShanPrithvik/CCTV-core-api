"""add events alerts and camera health

Revision ID: b9d2e3f4a5c6
Revises: a8c1d2e3f4b5
Create Date: 2026-09-04 02:18:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b9d2e3f4a5c6"
down_revision = "a8c1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "Event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_path", sa.String(length=1024), nullable=True),
        sa.Column("clip_path", sa.String(length=1024), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["Camera.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["Organization.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_camera_id", "Event", ["camera_id"])
    op.create_index("ix_event_event_type", "Event", ["event_type"])
    op.create_index("ix_event_occurred_at", "Event", ["occurred_at"])
    op.create_index("ix_event_organization_id", "Event", ["organization_id"])
    op.create_index("ix_event_severity", "Event", ["severity"])

    op.create_table(
        "Alert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["User.id"]),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["User.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["Event.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["Organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_alert_created_at", "Alert", ["created_at"])
    op.create_index("ix_alert_event_id", "Alert", ["event_id"], unique=True)
    op.create_index("ix_alert_organization_id", "Alert", ["organization_id"])
    op.create_index("ix_alert_status", "Alert", ["status"])

    op.create_table(
        "CameraHealth",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["Camera.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["Organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id"),
    )
    op.create_index("ix_camerahealth_camera_id", "CameraHealth", ["camera_id"], unique=True)
    op.create_index("ix_camerahealth_organization_id", "CameraHealth", ["organization_id"])
    op.create_index("ix_camerahealth_status", "CameraHealth", ["status"])


def downgrade():
    op.drop_table("CameraHealth")
    op.drop_table("Alert")
    op.drop_table("Event")
