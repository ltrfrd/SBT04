"""phase 0 company foundation and driver auth

Revision ID: 20260410_phase0_company_auth
Revises: 20260409_pretrip_checklist
Create Date: 2026-04-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260410_phase0_company_auth"
down_revision = "20260409_pretrip_checklist"
branch_labels = None
depends_on = None


DEFAULT_COMPANY_NAME = "Default Company"


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
    )
    op.create_index("ix_companies_id", "companies", ["id"], unique=False)
    op.create_index("ix_companies_name", "companies", ["name"], unique=True)

    op.execute(
        sa.text("INSERT INTO companies (name) VALUES (:name)"),
        {"name": DEFAULT_COMPANY_NAME},
    )
    bind = op.get_bind()
    default_company_id = bind.execute(
        sa.text("SELECT id FROM companies WHERE name = :name"),
        {"name": DEFAULT_COMPANY_NAME},
    ).scalar_one()

    with op.batch_alter_table("drivers") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pin_hash", sa.String(length=255), nullable=True))

    with op.batch_alter_table("buses") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("schools") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("routes") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))

    for table_name in ("drivers", "buses", "schools", "students", "routes"):
        op.execute(
            sa.text(f"UPDATE {table_name} SET company_id = :company_id WHERE company_id IS NULL"),
            {"company_id": default_company_id},
        )

    with op.batch_alter_table("drivers") as batch_op:
        batch_op.alter_column("company_id", nullable=False)
        batch_op.create_index("ix_drivers_company_id", ["company_id"], unique=False)
        batch_op.create_foreign_key("fk_drivers_company_id_companies", "companies", ["company_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("buses") as batch_op:
        batch_op.alter_column("company_id", nullable=False)
        batch_op.create_index("ix_buses_company_id", ["company_id"], unique=False)
        batch_op.create_foreign_key("fk_buses_company_id_companies", "companies", ["company_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("schools") as batch_op:
        batch_op.alter_column("company_id", nullable=False)
        batch_op.create_index("ix_schools_company_id", ["company_id"], unique=False)
        batch_op.create_foreign_key("fk_schools_company_id_companies", "companies", ["company_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("students") as batch_op:
        batch_op.alter_column("company_id", nullable=False)
        batch_op.create_index("ix_students_company_id", ["company_id"], unique=False)
        batch_op.create_foreign_key("fk_students_company_id_companies", "companies", ["company_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("routes") as batch_op:
        batch_op.alter_column("company_id", nullable=False)
        batch_op.create_index("ix_routes_company_id", ["company_id"], unique=False)
        batch_op.create_foreign_key("fk_routes_company_id_companies", "companies", ["company_id"], ["id"], ondelete="CASCADE")

    op.create_table(
        "company_route_access",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("access_level", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("route_id", "company_id", name="uq_company_route_access_route_company"),
    )
    op.create_index("ix_company_route_access_id", "company_route_access", ["id"], unique=False)
    op.create_index("ix_company_route_access_route_id", "company_route_access", ["route_id"], unique=False)
    op.create_index("ix_company_route_access_company_id", "company_route_access", ["company_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_company_route_access_company_id", table_name="company_route_access")
    op.drop_index("ix_company_route_access_route_id", table_name="company_route_access")
    op.drop_index("ix_company_route_access_id", table_name="company_route_access")
    op.drop_table("company_route_access")

    with op.batch_alter_table("routes") as batch_op:
        batch_op.drop_constraint("fk_routes_company_id_companies", type_="foreignkey")
        batch_op.drop_index("ix_routes_company_id")
        batch_op.drop_column("company_id")

    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_constraint("fk_students_company_id_companies", type_="foreignkey")
        batch_op.drop_index("ix_students_company_id")
        batch_op.drop_column("company_id")

    with op.batch_alter_table("schools") as batch_op:
        batch_op.drop_constraint("fk_schools_company_id_companies", type_="foreignkey")
        batch_op.drop_index("ix_schools_company_id")
        batch_op.drop_column("company_id")

    with op.batch_alter_table("buses") as batch_op:
        batch_op.drop_constraint("fk_buses_company_id_companies", type_="foreignkey")
        batch_op.drop_index("ix_buses_company_id")
        batch_op.drop_column("company_id")

    with op.batch_alter_table("drivers") as batch_op:
        batch_op.drop_constraint("fk_drivers_company_id_companies", type_="foreignkey")
        batch_op.drop_index("ix_drivers_company_id")
        batch_op.drop_column("pin_hash")
        batch_op.drop_column("company_id")

    op.drop_index("ix_companies_name", table_name="companies")
    op.drop_index("ix_companies_id", table_name="companies")
    op.drop_table("companies")
