"""drop route operator id

Revision ID: 20260417_drop_route_operator_id
Revises: 20260417_drop_student_operator_id
Create Date: 2026-04-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260417_drop_route_operator_id"
down_revision = "20260417_drop_student_operator_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("routes") as batch_op:
        batch_op.drop_constraint("fk_routes_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_routes_operator_id")
        batch_op.drop_column("operator_id")


def downgrade() -> None:
    with op.batch_alter_table("routes") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_routes_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_routes_operator_id_operators",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="SET NULL",
        )
