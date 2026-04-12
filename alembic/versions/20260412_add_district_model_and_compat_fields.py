"""add district model and compatibility ownership fields

Revision ID: 20260412_add_district_compat_fields
Revises: 20260411_rename_payroll_to_dispatch_records
Create Date: 2026-04-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260412_add_district_compat_fields"
down_revision = "20260411_rename_payroll_to_dispatch_records"
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

    if not _table_exists(inspector, "districts"):
        op.create_table(
            "districts",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("contact_info", sa.String(length=255), nullable=True),
        )
        op.create_index("ix_districts_id", "districts", ["id"], unique=False)
        op.create_index("ix_districts_name", "districts", ["name"], unique=True)

    for table_name in ("schools", "routes", "students"):
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, table_name) or _column_exists(inspector, table_name, "district_id"):
            continue

        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("district_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table_name}_district_id_districts",
                "districts",
                ["district_id"],
                ["id"],
                ondelete="SET NULL",
            )

        inspector = sa.inspect(bind)
        index_name = f"ix_{table_name}_district_id"
        if not _index_exists(inspector, table_name, index_name):
            op.create_index(index_name, table_name, ["district_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name in ("students", "routes", "schools"):
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, table_name) or not _column_exists(inspector, table_name, "district_id"):
            continue

        index_name = f"ix_{table_name}_district_id"
        if _index_exists(inspector, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)

        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(f"fk_{table_name}_district_id_districts", type_="foreignkey")
            batch_op.drop_column("district_id")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "districts"):
        if _index_exists(inspector, "districts", "ix_districts_name"):
            op.drop_index("ix_districts_name", table_name="districts")
        if _index_exists(inspector, "districts", "ix_districts_id"):
            op.drop_index("ix_districts_id", table_name="districts")
        op.drop_table("districts")
