"""add yards table

Revision ID: 20260413_add_yards_table
Revises: 20260412_add_route_cascade_identity_fields
Create Date: 2026-04-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260413_add_yards_table"
down_revision = "20260412_add_route_cascade_identity_fields"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "yards"):
        return

    op.create_table(
        "yards",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"]),
    )
    op.create_index("ix_yards_id", "yards", ["id"], unique=False)
    op.create_index("ix_yards_operator_id", "yards", ["operator_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "yards"):
        return

    if _index_exists(inspector, "yards", "ix_yards_operator_id"):
        op.drop_index("ix_yards_operator_id", table_name="yards")
    if _index_exists(inspector, "yards", "ix_yards_id"):
        op.drop_index("ix_yards_id", table_name="yards")
    op.drop_table("yards")
