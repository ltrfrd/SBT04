"""rename company structures to operator

Revision ID: 20260411_rename_company_to_operator
Revises: 20260410_phase0_company_auth
Create Date: 2026-04-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260411_rename_company_to_operator"
down_revision = "20260410_phase0_company_auth"
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

    if _table_exists(inspector, "companies") and not _table_exists(inspector, "operators"):
        op.rename_table("companies", "operators")
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "operators"):
        if _index_exists(inspector, "operators", "ix_companies_id"):
            op.drop_index("ix_companies_id", table_name="operators")
        if not _index_exists(inspector, "operators", "ix_operators_id"):
            op.create_index("ix_operators_id", "operators", ["id"], unique=False)
        if _index_exists(inspector, "operators", "ix_companies_name"):
            op.drop_index("ix_companies_name", table_name="operators")
        if not _index_exists(inspector, "operators", "ix_operators_name"):
            op.create_index("ix_operators_name", "operators", ["name"], unique=True)

    for table_name in ("drivers", "buses", "schools", "students", "routes"):
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, table_name) or not _column_exists(inspector, table_name, "company_id"):
            continue

        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "company_id",
                new_column_name="operator_id",
                existing_type=sa.Integer(),
                existing_nullable=False,
            )

        inspector = sa.inspect(bind)
        old_index = f"ix_{table_name}_company_id"
        new_index = f"ix_{table_name}_operator_id"
        if _index_exists(inspector, table_name, old_index):
            op.drop_index(old_index, table_name=table_name)
        if not _index_exists(inspector, table_name, new_index):
            op.create_index(new_index, table_name, ["operator_id"], unique=False)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "buses"):
        with op.batch_alter_table("buses") as batch_op:
            try:
                batch_op.drop_constraint("uq_bus_company_unit_number", type_="unique")
            except ValueError:
                pass
            try:
                batch_op.drop_constraint("uq_bus_company_license_plate", type_="unique")
            except ValueError:
                pass
            try:
                batch_op.create_unique_constraint("uq_bus_operator_unit_number", ["operator_id", "unit_number"])
            except ValueError:
                pass
            try:
                batch_op.create_unique_constraint("uq_bus_operator_license_plate", ["operator_id", "license_plate"])
            except ValueError:
                pass

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "company_route_access") and not _table_exists(inspector, "operator_route_access"):
        op.rename_table("company_route_access", "operator_route_access")
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "operator_route_access") and _column_exists(inspector, "operator_route_access", "company_id"):
        with op.batch_alter_table("operator_route_access") as batch_op:
            batch_op.alter_column(
                "company_id",
                new_column_name="operator_id",
                existing_type=sa.Integer(),
                existing_nullable=False,
            )
            try:
                batch_op.drop_constraint("uq_company_route_access_route_company", type_="unique")
            except ValueError:
                pass
            try:
                batch_op.create_unique_constraint(
                    "uq_operator_route_access_route_operator",
                    ["route_id", "operator_id"],
                )
            except ValueError:
                pass

        inspector = sa.inspect(bind)
        if _index_exists(inspector, "operator_route_access", "ix_company_route_access_company_id"):
            op.drop_index("ix_company_route_access_company_id", table_name="operator_route_access")
        if not _index_exists(inspector, "operator_route_access", "ix_operator_route_access_operator_id"):
            op.create_index("ix_operator_route_access_operator_id", "operator_route_access", ["operator_id"], unique=False)
        if _index_exists(inspector, "operator_route_access", "ix_company_route_access_route_id"):
            op.drop_index("ix_company_route_access_route_id", table_name="operator_route_access")
        if not _index_exists(inspector, "operator_route_access", "ix_operator_route_access_route_id"):
            op.create_index("ix_operator_route_access_route_id", "operator_route_access", ["route_id"], unique=False)
        if _index_exists(inspector, "operator_route_access", "ix_company_route_access_id"):
            op.drop_index("ix_company_route_access_id", table_name="operator_route_access")
        if not _index_exists(inspector, "operator_route_access", "ix_operator_route_access_id"):
            op.create_index("ix_operator_route_access_id", "operator_route_access", ["id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "operator_route_access") and _column_exists(inspector, "operator_route_access", "operator_id"):
        with op.batch_alter_table("operator_route_access") as batch_op:
            batch_op.alter_column(
                "operator_id",
                new_column_name="company_id",
                existing_type=sa.Integer(),
                existing_nullable=False,
            )
            try:
                batch_op.drop_constraint("uq_operator_route_access_route_operator", type_="unique")
            except ValueError:
                pass
            try:
                batch_op.create_unique_constraint(
                    "uq_company_route_access_route_company",
                    ["route_id", "company_id"],
                )
            except ValueError:
                pass

        inspector = sa.inspect(bind)
        if _index_exists(inspector, "operator_route_access", "ix_operator_route_access_operator_id"):
            op.drop_index("ix_operator_route_access_operator_id", table_name="operator_route_access")
        if not _index_exists(inspector, "operator_route_access", "ix_company_route_access_company_id"):
            op.create_index("ix_company_route_access_company_id", "operator_route_access", ["company_id"], unique=False)
        if _index_exists(inspector, "operator_route_access", "ix_operator_route_access_route_id"):
            op.drop_index("ix_operator_route_access_route_id", table_name="operator_route_access")
        if not _index_exists(inspector, "operator_route_access", "ix_company_route_access_route_id"):
            op.create_index("ix_company_route_access_route_id", "operator_route_access", ["route_id"], unique=False)
        if _index_exists(inspector, "operator_route_access", "ix_operator_route_access_id"):
            op.drop_index("ix_operator_route_access_id", table_name="operator_route_access")
        if not _index_exists(inspector, "operator_route_access", "ix_company_route_access_id"):
            op.create_index("ix_company_route_access_id", "operator_route_access", ["id"], unique=False)

        inspector = sa.inspect(bind)
        if _table_exists(inspector, "operator_route_access") and not _table_exists(inspector, "company_route_access"):
            op.rename_table("operator_route_access", "company_route_access")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "buses"):
        with op.batch_alter_table("buses") as batch_op:
            try:
                batch_op.drop_constraint("uq_bus_operator_unit_number", type_="unique")
            except ValueError:
                pass
            try:
                batch_op.drop_constraint("uq_bus_operator_license_plate", type_="unique")
            except ValueError:
                pass
            try:
                batch_op.create_unique_constraint("uq_bus_company_unit_number", ["company_id", "unit_number"])
            except ValueError:
                pass
            try:
                batch_op.create_unique_constraint("uq_bus_company_license_plate", ["company_id", "license_plate"])
            except ValueError:
                pass

    for table_name in ("drivers", "buses", "schools", "students", "routes"):
        inspector = sa.inspect(bind)
        if not _table_exists(inspector, table_name) or not _column_exists(inspector, table_name, "operator_id"):
            continue

        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "operator_id",
                new_column_name="company_id",
                existing_type=sa.Integer(),
                existing_nullable=False,
            )

        inspector = sa.inspect(bind)
        old_index = f"ix_{table_name}_operator_id"
        new_index = f"ix_{table_name}_company_id"
        if _index_exists(inspector, table_name, old_index):
            op.drop_index(old_index, table_name=table_name)
        if not _index_exists(inspector, table_name, new_index):
            op.create_index(new_index, table_name, ["company_id"], unique=False)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "operators"):
        if _index_exists(inspector, "operators", "ix_operators_id"):
            op.drop_index("ix_operators_id", table_name="operators")
        if not _index_exists(inspector, "operators", "ix_companies_id"):
            op.create_index("ix_companies_id", "operators", ["id"], unique=False)
        if _index_exists(inspector, "operators", "ix_operators_name"):
            op.drop_index("ix_operators_name", table_name="operators")
        if not _index_exists(inspector, "operators", "ix_companies_name"):
            op.create_index("ix_companies_name", "operators", ["name"], unique=True)

        inspector = sa.inspect(bind)
        if _table_exists(inspector, "operators") and not _table_exists(inspector, "companies"):
            op.rename_table("operators", "companies")
