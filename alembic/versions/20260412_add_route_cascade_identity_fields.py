"""add route cascade identity fields

Revision ID: 20260412_add_route_cascade_identity_fields
Revises: 20260412_add_district_compat_fields
Create Date: 2026-04-12 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260412_add_route_cascade_identity_fields"
down_revision = "20260412_add_district_compat_fields"
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

    if _table_exists(inspector, "runs") and not _column_exists(inspector, "runs", "district_id"):
        with op.batch_alter_table("runs") as batch_op:
            batch_op.add_column(sa.Column("district_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_runs_district_id_districts",
                "districts",
                ["district_id"],
                ["id"],
                ondelete="SET NULL",
            )
        inspector = sa.inspect(bind)
        if not _index_exists(inspector, "runs", "ix_runs_district_id"):
            op.create_index("ix_runs_district_id", "runs", ["district_id"], unique=False)

    for column_name, fk_name, target_table, index_name in (
        ("route_id", "fk_stops_route_id_routes", "routes", "ix_stops_route_id"),
        ("district_id", "fk_stops_district_id_districts", "districts", "ix_stops_district_id"),
    ):
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, "stops") or _column_exists(inspector, "stops", column_name):
            continue

        with op.batch_alter_table("stops") as batch_op:
            batch_op.add_column(sa.Column(column_name, sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                fk_name,
                target_table,
                [column_name],
                ["id"],
                ondelete="SET NULL",
            )

        inspector = sa.inspect(bind)
        if not _index_exists(inspector, "stops", index_name):
            op.create_index(index_name, "stops", [column_name], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for column_name, fk_name, index_name in (
        ("district_id", "fk_stops_district_id_districts", "ix_stops_district_id"),
        ("route_id", "fk_stops_route_id_routes", "ix_stops_route_id"),
    ):
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, "stops") or not _column_exists(inspector, "stops", column_name):
            continue

        if _index_exists(inspector, "stops", index_name):
            op.drop_index(index_name, table_name="stops")

        with op.batch_alter_table("stops") as batch_op:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.drop_column(column_name)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "runs") and _column_exists(inspector, "runs", "district_id"):
        if _index_exists(inspector, "runs", "ix_runs_district_id"):
            op.drop_index("ix_runs_district_id", table_name="runs")

        with op.batch_alter_table("runs") as batch_op:
            batch_op.drop_constraint("fk_runs_district_id_districts", type_="foreignkey")
            batch_op.drop_column("district_id")
