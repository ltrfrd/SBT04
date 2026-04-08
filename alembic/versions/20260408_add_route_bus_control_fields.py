"""add route bus control fields

Revision ID: 20260408_route_bus_control
Revises: 20260408_pretrip_foundation
Create Date: 2026-04-08 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260408_route_bus_control"
down_revision = "20260408_pretrip_foundation"
branch_labels = None
depends_on = None


# -----------------------------------------------------------
# - Upgrade
# - Add primary/active route bus control fields
# -----------------------------------------------------------
def upgrade() -> None:
    with op.batch_alter_table("routes") as batch_op:
        batch_op.add_column(sa.Column("primary_bus_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("active_bus_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("clearance_note", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_routes_primary_bus_id_buses",
            "buses",
            ["primary_bus_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_routes_active_bus_id_buses",
            "buses",
            ["active_bus_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE routes
            SET primary_bus_id = bus_id,
                active_bus_id = bus_id
            WHERE bus_id IS NOT NULL
            """
        )
    )                                                          # Preserve current route bus state across the new fields


# -----------------------------------------------------------
# - Downgrade
# - Remove primary/active route bus control fields
# -----------------------------------------------------------
def downgrade() -> None:
    with op.batch_alter_table("routes") as batch_op:
        batch_op.drop_constraint("fk_routes_active_bus_id_buses", type_="foreignkey")
        batch_op.drop_constraint("fk_routes_primary_bus_id_buses", type_="foreignkey")
        batch_op.drop_column("clearance_note")
        batch_op.drop_column("active_bus_id")
        batch_op.drop_column("primary_bus_id")
