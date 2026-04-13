"""add bus yard id

Revision ID: 20260413_add_bus_yard_id
Revises: 20260413_backfill_driver_yards
Create Date: 2026-04-13 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260413_add_bus_yard_id"
down_revision = "20260413_backfill_driver_yards"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "buses") or _column_exists(inspector, "buses", "yard_id"):
        return

    with op.batch_alter_table("buses") as batch_op:
        batch_op.add_column(sa.Column("yard_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_buses_yard_id_yards",
            "yards",
            ["yard_id"],
            ["id"],
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "buses", "ix_buses_yard_id"):
        op.create_index("ix_buses_yard_id", "buses", ["yard_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "buses") or not _column_exists(inspector, "buses", "yard_id"):
        return

    if _index_exists(inspector, "buses", "ix_buses_yard_id"):
        op.drop_index("ix_buses_yard_id", table_name="buses")

    with op.batch_alter_table("buses") as batch_op:
        batch_op.drop_constraint("fk_buses_yard_id_yards", type_="foreignkey")
        batch_op.drop_column("yard_id")
