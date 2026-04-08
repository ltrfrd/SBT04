"""add run schedule and dispatch alerts

Revision ID: 20260408_run_schedule_alerts
Revises: 20260408_route_bus_control
Create Date: 2026-04-08 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_run_schedule_alerts"
down_revision = "20260408_route_bus_control"
branch_labels = None
depends_on = None


# -----------------------------------------------------------
# - Upgrade
# - Add fixed run schedule fields and focused dispatch alerts
# -----------------------------------------------------------
def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("scheduled_start_time", sa.Time(), nullable=False, server_default=sa.text("'00:00:00'")))
        batch_op.add_column(sa.Column("scheduled_end_time", sa.Time(), nullable=False, server_default=sa.text("'00:00:00'")))

    with op.batch_alter_table("runs") as batch_op:
        batch_op.alter_column("scheduled_start_time", server_default=None)
        batch_op.alter_column("scheduled_end_time", server_default=None)

    op.create_table(
        "dispatch_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("alert_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("bus_id", sa.Integer(), nullable=True),
        sa.Column("route_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("pretrip_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["bus_id"], ["buses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["pretrip_id"], ["pretrip_inspections.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_dispatch_alerts_id"), "dispatch_alerts", ["id"], unique=False)
    op.create_index(op.f("ix_dispatch_alerts_alert_type"), "dispatch_alerts", ["alert_type"], unique=False)
    op.create_index(op.f("ix_dispatch_alerts_bus_id"), "dispatch_alerts", ["bus_id"], unique=False)
    op.create_index(op.f("ix_dispatch_alerts_route_id"), "dispatch_alerts", ["route_id"], unique=False)
    op.create_index(op.f("ix_dispatch_alerts_run_id"), "dispatch_alerts", ["run_id"], unique=False)
    op.create_index(op.f("ix_dispatch_alerts_pretrip_id"), "dispatch_alerts", ["pretrip_id"], unique=False)


# -----------------------------------------------------------
# - Downgrade
# - Remove focused dispatch alerts and fixed run schedule fields
# -----------------------------------------------------------
def downgrade() -> None:
    op.drop_index(op.f("ix_dispatch_alerts_pretrip_id"), table_name="dispatch_alerts")
    op.drop_index(op.f("ix_dispatch_alerts_run_id"), table_name="dispatch_alerts")
    op.drop_index(op.f("ix_dispatch_alerts_route_id"), table_name="dispatch_alerts")
    op.drop_index(op.f("ix_dispatch_alerts_bus_id"), table_name="dispatch_alerts")
    op.drop_index(op.f("ix_dispatch_alerts_alert_type"), table_name="dispatch_alerts")
    op.drop_index(op.f("ix_dispatch_alerts_id"), table_name="dispatch_alerts")
    op.drop_table("dispatch_alerts")

    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("scheduled_end_time")
        batch_op.drop_column("scheduled_start_time")
