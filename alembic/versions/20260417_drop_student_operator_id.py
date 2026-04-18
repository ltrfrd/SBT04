"""drop student operator id

Revision ID: 20260417_drop_student_operator_id
Revises: 20260416_route_student_district_batch_a
Create Date: 2026-04-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260417_drop_student_operator_id"
down_revision = "20260416_route_student_district_batch_a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_constraint("fk_students_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_students_operator_id")
        batch_op.drop_column("operator_id")


def downgrade() -> None:
    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_students_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_students_operator_id_operators",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="SET NULL",
        )
