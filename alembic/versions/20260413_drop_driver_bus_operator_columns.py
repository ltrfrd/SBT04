"""drop legacy driver and bus operator ownership columns

Revision ID: 20260413_drop_driver_bus_operator_columns
Revises: 20260413_backfill_bus_yards
Create Date: 2026-04-13 22:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260413_drop_driver_bus_operator_columns"
down_revision = "20260413_backfill_bus_yards"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _unique_exists(inspector, table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in inspector.get_unique_constraints(table_name)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "drivers") and _column_exists(inspector, "drivers", "operator_id"):
        with op.batch_alter_table("drivers") as batch_op:
            batch_op.drop_column("operator_id")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "buses") and _column_exists(inspector, "buses", "operator_id"):
        with op.batch_alter_table("buses") as batch_op:
            if _unique_exists(inspector, "buses", "uq_bus_operator_unit_number"):
                batch_op.drop_constraint("uq_bus_operator_unit_number", type_="unique")
            if _unique_exists(inspector, "buses", "uq_bus_operator_license_plate"):
                batch_op.drop_constraint("uq_bus_operator_license_plate", type_="unique")
            if not _unique_exists(inspector, "buses", "uq_bus_yard_unit_number"):
                batch_op.create_unique_constraint("uq_bus_yard_unit_number", ["yard_id", "unit_number"])
            if not _unique_exists(inspector, "buses", "uq_bus_yard_license_plate"):
                batch_op.create_unique_constraint("uq_bus_yard_license_plate", ["yard_id", "license_plate"])
            batch_op.drop_column("operator_id")

        inspector = sa.inspect(bind)
        if _index_exists(inspector, "buses", "ix_buses_operator_id"):
            op.drop_index("ix_buses_operator_id", table_name="buses")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "drivers") and not _column_exists(inspector, "drivers", "operator_id"):
        with op.batch_alter_table("drivers") as batch_op:
            batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_drivers_operator_id_operators",
                "operators",
                ["operator_id"],
                ["id"],
                ondelete="CASCADE",
            )
        op.create_index("ix_drivers_operator_id", "drivers", ["operator_id"], unique=False)
        bind.execute(
            sa.text(
                """
                UPDATE drivers
                SET operator_id = (
                    SELECT yards.operator_id
                    FROM yards
                    WHERE yards.id = drivers.yard_id
                )
                WHERE yard_id IS NOT NULL
                """
            )
        )

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "buses") and not _column_exists(inspector, "buses", "operator_id"):
        with op.batch_alter_table("buses") as batch_op:
            if _unique_exists(inspector, "buses", "uq_bus_yard_unit_number"):
                batch_op.drop_constraint("uq_bus_yard_unit_number", type_="unique")
            if _unique_exists(inspector, "buses", "uq_bus_yard_license_plate"):
                batch_op.drop_constraint("uq_bus_yard_license_plate", type_="unique")
            batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_buses_operator_id_operators",
                "operators",
                ["operator_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_unique_constraint("uq_bus_operator_unit_number", ["operator_id", "unit_number"])
            batch_op.create_unique_constraint("uq_bus_operator_license_plate", ["operator_id", "license_plate"])
        op.create_index("ix_buses_operator_id", "buses", ["operator_id"], unique=False)
        bind.execute(
            sa.text(
                """
                UPDATE buses
                SET operator_id = (
                    SELECT yards.operator_id
                    FROM yards
                    WHERE yards.id = buses.yard_id
                )
                WHERE yard_id IS NOT NULL
                """
            )
        )
