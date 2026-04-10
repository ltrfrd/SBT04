"""add posttrip inspections

Revision ID: 20260409_posttrip_inspections
Revises: 20260408_pretrip_license_plate
Create Date: 2026-04-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260409_posttrip_inspections"
down_revision = "20260408_pretrip_license_plate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posttrip_inspections",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("bus_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("phase1_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase1_completed_at", sa.DateTime(), nullable=True),
        sa.Column("phase1_no_students_remaining", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase1_belongings_checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase1_checked_sign_hung", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase2_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase2_completed_at", sa.DateTime(), nullable=True),
        sa.Column("phase2_pending_since", sa.DateTime(), nullable=True),
        sa.Column("phase2_status", sa.String(length=50), nullable=False, server_default="not_started"),
        sa.Column("phase2_full_internal_recheck", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase2_checked_to_cleared_switched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phase2_rear_button_triggered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exterior_status", sa.String(length=20), nullable=True),
        sa.Column("exterior_description", sa.Text(), nullable=True),
        sa.Column("last_driver_activity_at", sa.DateTime(), nullable=True),
        sa.Column("last_known_lat", sa.Float(), nullable=True),
        sa.Column("last_known_lng", sa.Float(), nullable=True),
        sa.Column("last_location_update_at", sa.DateTime(), nullable=True),
        sa.Column("neglect_flagged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bus_id"], ["buses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", name="uq_posttrip_inspection_run"),
    )
    op.create_index(op.f("ix_posttrip_inspections_id"), "posttrip_inspections", ["id"], unique=False)
    op.create_index(op.f("ix_posttrip_inspections_run_id"), "posttrip_inspections", ["run_id"], unique=True)
    op.create_index(op.f("ix_posttrip_inspections_bus_id"), "posttrip_inspections", ["bus_id"], unique=False)
    op.create_index(op.f("ix_posttrip_inspections_route_id"), "posttrip_inspections", ["route_id"], unique=False)
    op.create_index(op.f("ix_posttrip_inspections_driver_id"), "posttrip_inspections", ["driver_id"], unique=False)

    with op.batch_alter_table("posttrip_inspections") as batch_op:
        batch_op.alter_column("phase1_completed", server_default=None)
        batch_op.alter_column("phase1_no_students_remaining", server_default=None)
        batch_op.alter_column("phase1_belongings_checked", server_default=None)
        batch_op.alter_column("phase1_checked_sign_hung", server_default=None)
        batch_op.alter_column("phase2_completed", server_default=None)
        batch_op.alter_column("phase2_status", server_default=None)
        batch_op.alter_column("phase2_full_internal_recheck", server_default=None)
        batch_op.alter_column("phase2_checked_to_cleared_switched", server_default=None)
        batch_op.alter_column("phase2_rear_button_triggered", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_posttrip_inspections_driver_id"), table_name="posttrip_inspections")
    op.drop_index(op.f("ix_posttrip_inspections_route_id"), table_name="posttrip_inspections")
    op.drop_index(op.f("ix_posttrip_inspections_bus_id"), table_name="posttrip_inspections")
    op.drop_index(op.f("ix_posttrip_inspections_run_id"), table_name="posttrip_inspections")
    op.drop_index(op.f("ix_posttrip_inspections_id"), table_name="posttrip_inspections")
    op.drop_table("posttrip_inspections")
