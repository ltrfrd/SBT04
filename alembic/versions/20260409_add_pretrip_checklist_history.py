"""add pretrip checklist history

Revision ID: 20260409_pretrip_checklist
Revises: 20260409_posttrip_inspections
Create Date: 2026-04-09 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260409_pretrip_checklist"
down_revision = "20260409_posttrip_inspections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pretrip_inspections") as batch_op:
        batch_op.add_column(sa.Column("brakes_checked", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("lights_checked", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("tires_checked", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("emergency_equipment_checked", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("pretrip_inspections") as batch_op:
        batch_op.alter_column("brakes_checked", server_default=None)
        batch_op.alter_column("lights_checked", server_default=None)
        batch_op.alter_column("tires_checked", server_default=None)
        batch_op.alter_column("emergency_equipment_checked", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("pretrip_inspections") as batch_op:
        batch_op.drop_column("emergency_equipment_checked")
        batch_op.drop_column("tires_checked")
        batch_op.drop_column("lights_checked")
        batch_op.drop_column("brakes_checked")
