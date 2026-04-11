"""phase 0 operator foundation and driver auth

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


DEFAULT_OPERATOR_NAME = "Default Operator"


def upgrade() -> None:
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
    )
    op.create_index("ix_operators_id", "operators", ["id"], unique=False)
    op.create_index("ix_operators_name", "operators", ["name"], unique=True)

    op.execute(
        sa.text("INSERT INTO operators (name) VALUES (:name)"),
        {"name": DEFAULT_OPERATOR_NAME},
    )
    bind = op.get_bind()
    default_operator_id = bind.execute(
        sa.text("SELECT id FROM operators WHERE name = :name"),
        {"name": DEFAULT_OPERATOR_NAME},
    ).scalar_one()

    with op.batch_alter_table("drivers") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pin_hash", sa.String(length=255), nullable=True))

    with op.batch_alter_table("buses") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("schools") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("routes") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))

    for table_name in ("drivers", "buses", "schools", "students", "routes"):
        op.execute(
            sa.text(f"UPDATE {table_name} SET operator_id = :operator_id WHERE operator_id IS NULL"),
            {"operator_id": default_operator_id},
        )

    with op.batch_alter_table("drivers") as batch_op:
        batch_op.alter_column("operator_id", nullable=False)
        batch_op.create_index("ix_drivers_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key("fk_drivers_operator_id_operators", "operators", ["operator_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("buses") as batch_op:
        batch_op.alter_column("operator_id", nullable=False)
        batch_op.create_index("ix_buses_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key("fk_buses_operator_id_operators", "operators", ["operator_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("schools") as batch_op:
        batch_op.alter_column("operator_id", nullable=False)
        batch_op.create_index("ix_schools_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key("fk_schools_operator_id_operators", "operators", ["operator_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("students") as batch_op:
        batch_op.alter_column("operator_id", nullable=False)
        batch_op.create_index("ix_students_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key("fk_students_operator_id_operators", "operators", ["operator_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("routes") as batch_op:
        batch_op.alter_column("operator_id", nullable=False)
        batch_op.create_index("ix_routes_operator_id", ["operator_id"], unique=False)
        batch_op.create_foreign_key("fk_routes_operator_id_operators", "operators", ["operator_id"], ["id"], ondelete="CASCADE")

    op.create_table(
        "operator_route_access",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("access_level", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("route_id", "operator_id", name="uq_operator_route_access_route_operator"),
    )
    op.create_index("ix_operator_route_access_id", "operator_route_access", ["id"], unique=False)
    op.create_index("ix_operator_route_access_route_id", "operator_route_access", ["route_id"], unique=False)
    op.create_index("ix_operator_route_access_operator_id", "operator_route_access", ["operator_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_operator_route_access_operator_id", table_name="operator_route_access")
    op.drop_index("ix_operator_route_access_route_id", table_name="operator_route_access")
    op.drop_index("ix_operator_route_access_id", table_name="operator_route_access")
    op.drop_table("operator_route_access")

    with op.batch_alter_table("routes") as batch_op:
        batch_op.drop_constraint("fk_routes_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_routes_operator_id")
        batch_op.drop_column("operator_id")

    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_constraint("fk_students_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_students_operator_id")
        batch_op.drop_column("operator_id")

    with op.batch_alter_table("schools") as batch_op:
        batch_op.drop_constraint("fk_schools_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_schools_operator_id")
        batch_op.drop_column("operator_id")

    with op.batch_alter_table("buses") as batch_op:
        batch_op.drop_constraint("fk_buses_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_buses_operator_id")
        batch_op.drop_column("operator_id")

    with op.batch_alter_table("drivers") as batch_op:
        batch_op.drop_constraint("fk_drivers_operator_id_operators", type_="foreignkey")
        batch_op.drop_index("ix_drivers_operator_id")
        batch_op.drop_column("pin_hash")
        batch_op.drop_column("operator_id")

    op.drop_index("ix_operators_name", table_name="operators")
    op.drop_index("ix_operators_id", table_name="operators")
    op.drop_table("operators")

