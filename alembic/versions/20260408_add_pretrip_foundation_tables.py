"""add pretrip foundation tables

Revision ID: 20260408_pretrip_foundation
Revises: 20260330_route_stop_school
Create Date: 2026-04-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_pretrip_foundation"
down_revision = "20260330_route_stop_school"
branch_labels = None
depends_on = None


# -----------------------------------------------------------
# - Upgrade
# - Create bus/day pre-trip inspection and defect tables
# -----------------------------------------------------------
def upgrade() -> None:
    op.create_table(
        "pretrip_inspections",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("bus_id", sa.Integer(), nullable=False),
        sa.Column("driver_name", sa.String(length=255), nullable=False),
        sa.Column("inspection_date", sa.Date(), nullable=False),
        sa.Column("inspection_time", sa.Time(), nullable=False),
        sa.Column("odometer", sa.Integer(), nullable=False),
        sa.Column("inspection_place", sa.String(length=255), nullable=False),
        sa.Column("use_type", sa.String(length=50), nullable=False),
        sa.Column("fit_for_duty", sa.String(length=10), nullable=False),
        sa.Column("no_defects", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("is_corrected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("corrected_by", sa.String(length=255), nullable=True),
        sa.Column("corrected_at", sa.DateTime(), nullable=True),
        sa.Column("original_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bus_id"], ["buses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("bus_id", "inspection_date", name="uq_pretrip_inspection_bus_date"),
    )
    op.create_index(op.f("ix_pretrip_inspections_id"), "pretrip_inspections", ["id"], unique=False)
    op.create_index(op.f("ix_pretrip_inspections_bus_id"), "pretrip_inspections", ["bus_id"], unique=False)
    op.create_index(op.f("ix_pretrip_inspections_inspection_date"), "pretrip_inspections", ["inspection_date"], unique=False)

    op.create_table(
        "pretrip_defects",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("pretrip_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["pretrip_id"], ["pretrip_inspections.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_pretrip_defects_id"), "pretrip_defects", ["id"], unique=False)
    op.create_index(op.f("ix_pretrip_defects_pretrip_id"), "pretrip_defects", ["pretrip_id"], unique=False)


# -----------------------------------------------------------
# - Downgrade
# - Remove bus/day pre-trip inspection and defect tables
# -----------------------------------------------------------
def downgrade() -> None:
    op.drop_index(op.f("ix_pretrip_defects_pretrip_id"), table_name="pretrip_defects")
    op.drop_index(op.f("ix_pretrip_defects_id"), table_name="pretrip_defects")
    op.drop_table("pretrip_defects")

    op.drop_index(op.f("ix_pretrip_inspections_inspection_date"), table_name="pretrip_inspections")
    op.drop_index(op.f("ix_pretrip_inspections_bus_id"), table_name="pretrip_inspections")
    op.drop_index(op.f("ix_pretrip_inspections_id"), table_name="pretrip_inspections")
    op.drop_table("pretrip_inspections")
