"""backfill buses into operator yards

Revision ID: 20260413_backfill_bus_yards
Revises: 20260413_add_bus_yard_id
Create Date: 2026-04-13 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260413_backfill_bus_yards"
down_revision = "20260413_add_bus_yard_id"
branch_labels = None
depends_on = None


DEFAULT_YARD_NAME = "Main Yard"


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if (
        not _table_exists(inspector, "buses")
        or not _table_exists(inspector, "yards")
        or not _column_exists(inspector, "buses", "yard_id")
        or not _column_exists(inspector, "buses", "operator_id")
        or not _column_exists(inspector, "yards", "operator_id")
    ):
        return

    operator_ids = [
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT DISTINCT operator_id
                FROM buses
                WHERE yard_id IS NULL
                  AND operator_id IS NOT NULL
                ORDER BY operator_id
                """
            )
        )
    ]

    for operator_id in operator_ids:
        yard_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM yards
                WHERE operator_id = :operator_id
                ORDER BY id
                LIMIT 1
                """
            ),
            {"operator_id": operator_id},
        ).scalar()

        if yard_id is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO yards (name, operator_id)
                    VALUES (:name, :operator_id)
                    """
                ),
                {"name": DEFAULT_YARD_NAME, "operator_id": operator_id},
            )
            yard_id = bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM yards
                    WHERE operator_id = :operator_id
                    ORDER BY id
                    LIMIT 1
                    """
                ),
                {"operator_id": operator_id},
            ).scalar()

        if yard_id is None:
            continue

        bind.execute(
            sa.text(
                """
                UPDATE buses
                SET yard_id = :yard_id
                WHERE operator_id = :operator_id
                  AND yard_id IS NULL
                """
            ),
            {"yard_id": yard_id, "operator_id": operator_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "buses") or not _column_exists(inspector, "buses", "yard_id"):
        return

    bind.execute(sa.text("UPDATE buses SET yard_id = NULL WHERE yard_id IS NOT NULL"))
