"""add auth models and org fks

Revision ID: 4cf70ef98ced
Revises: e1e2efec4d8b
Create Date: 2026-07-28 18:07:07.286151

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4cf70ef98ced'
down_revision = 'e1e2efec4d8b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('Camera', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))

    with op.batch_alter_table('RuleConfig', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))

    op.create_table('User',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('status', sa.Enum('Active', 'Inactive', 'Pending', name='user_status'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_user_email')
    )
    op.create_table('Organization',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.Enum('Active', 'Inactive', name='org_status'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('Membership',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.Enum('Owner', 'Admin', 'Member', name='membership_role'), nullable=True),
        sa.Column('status', sa.Enum('Active', 'Inactive', 'Pending', name='membership_status'), nullable=True),
        sa.Column('invite_token', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['Organization.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['User.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'organization_id', name='uq_user_org')
    )


def downgrade():
    op.drop_table('Membership')
    op.drop_table('Organization')
    op.drop_table('User')

    with op.batch_alter_table('RuleConfig', schema=None) as batch_op:
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('Camera', schema=None) as batch_op:
        batch_op.drop_column('organization_id')
