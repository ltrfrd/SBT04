"""drop direct school operator ownership

Revision ID: 20260414_drop_school_operator_ownership
Revises: 20260413_drop_driver_bus_operator_columns
Create Date: 2026-04-14 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260414_drop_school_operator_ownership"
down_revision = "20260413_drop_driver_bus_operator_columns"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _foreign_key_exists(inspector, table_name: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "schools"):
        return

    null_district_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM schools WHERE district_id IS NULL")
    ).scalar_one()
    if null_district_count:
        raise RuntimeError(
            "Cannot drop schools.operator_id while schools.district_id contains NULL values. "
            "Backfill every school into a district before running this migration."
        )

    with op.batch_alter_table("schools") as batch_op:
        batch_op.alter_column("district_id", existing_type=sa.Integer(), nullable=False)
        if _foreign_key_exists(inspector, "schools", "fk_schools_operator_id_operators"):
            batch_op.drop_constraint("fk_schools_operator_id_operators", type_="foreignkey")
        if _column_exists(inspector, "schools", "operator_id"):
            batch_op.drop_column("operator_id")

    inspector = sa.inspect(bind)
    if _index_exists(inspector, "schools", "ix_schools_operator_id"):
        op.drop_index("ix_schools_operator_id", table_name="schools")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "schools"):
        return

    with op.batch_alter_table("schools") as batch_op:
        batch_op.alter_column("district_id", existing_type=sa.Integer(), nullable=True)
        if not _column_exists(inspector, "schools", "operator_id"):
            batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_schools_operator_id_operators",
                "operators",
                ["operator_id"],
                ["id"],
                ondelete="CASCADE",
            )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "schools", "ix_schools_operator_id"):
        op.create_index("ix_schools_operator_id", "schools", ["operator_id"], unique=False)
