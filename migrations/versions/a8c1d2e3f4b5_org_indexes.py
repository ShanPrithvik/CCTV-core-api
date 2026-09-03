"""indexes for org scoping and invite lookup

Revision ID: a8c1d2e3f4b5
Revises: 4cf70ef98ced
Create Date: 2026-09-04 01:00:00.000000

"""
from alembic import op


revision = "a8c1d2e3f4b5"
down_revision = "4cf70ef98ced"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("Camera") as batch_op:
        batch_op.create_index("ix_camera_organization_id", ["organization_id"])
        batch_op.create_index("ix_camera_status", ["status"])

    with op.batch_alter_table("RuleConfig") as batch_op:
        batch_op.create_index("ix_ruleconfig_organization_id", ["organization_id"])
        batch_op.create_index("ix_ruleconfig_camera_status", ["camera_id", "status"])

    with op.batch_alter_table("Membership") as batch_op:
        batch_op.create_index("ix_membership_invite_token", ["invite_token"], unique=True)


def downgrade():
    with op.batch_alter_table("Membership") as batch_op:
        batch_op.drop_index("ix_membership_invite_token")

    with op.batch_alter_table("RuleConfig") as batch_op:
        batch_op.drop_index("ix_ruleconfig_camera_status")
        batch_op.drop_index("ix_ruleconfig_organization_id")

    with op.batch_alter_table("Camera") as batch_op:
        batch_op.drop_index("ix_camera_status")
        batch_op.drop_index("ix_camera_organization_id")
