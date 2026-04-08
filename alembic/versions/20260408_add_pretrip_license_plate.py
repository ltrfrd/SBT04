"""add pretrip license plate

Revision ID: 20260408_pretrip_license_plate
Revises: 20260408_run_schedule_alerts
Create Date: 2026-04-08 12:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_pretrip_license_plate"
down_revision = "20260408_run_schedule_alerts"
branch_labels = None
depends_on = None


# -----------------------------------------------------------
# - Upgrade
# - Add required license plate to existing pre-trip inspections
# -----------------------------------------------------------
def upgrade() -> None:
    with op.batch_alter_table("pretrip_inspections") as batch_op:
        batch_op.add_column(sa.Column("license_plate", sa.String(), nullable=False, server_default=""))

    with op.batch_alter_table("pretrip_inspections") as batch_op:
        batch_op.alter_column("license_plate", server_default=None)


# -----------------------------------------------------------
# - Downgrade
# - Remove required license plate from pre-trip inspections
# -----------------------------------------------------------
def downgrade() -> None:
    with op.batch_alter_table("pretrip_inspections") as batch_op:
        batch_op.drop_column("license_plate")
