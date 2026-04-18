"""add yard route assignments

Revision ID: 20260417_add_yard_route_assignments
Revises: 20260417_drop_route_operator_id
Create Date: 2026-04-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260417_add_yard_route_assignments"
down_revision = "20260417_drop_route_operator_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "yard_route_assignments",
        sa.Column("yard_id", sa.Integer(), sa.ForeignKey("yards.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id", ondelete="CASCADE"), primary_key=True),
        sa.UniqueConstraint("yard_id", "route_id", name="uq_yard_route"),
    )


def downgrade() -> None:
    op.drop_table("yard_route_assignments")
