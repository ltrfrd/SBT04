"""route run stop school simplification

Revision ID: 20260330_route_stop_school
Revises: 39429b00c9d3
Create Date: 2026-03-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260330_route_stop_school"
down_revision = "39429b00c9d3"
branch_labels = None
depends_on = None


# -----------------------------------------------------------
# Upgrade
# Remove school_code and add school-aware stop context
# -----------------------------------------------------------
def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("schools") as batch_op:
        batch_op.drop_column("school_code")
        batch_op.alter_column("address", existing_type=sa.String(length=255), nullable=True)

    with op.batch_alter_table("stops") as batch_op:
        batch_op.add_column(sa.Column("school_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_stops_school_id_schools",
            "schools",
            ["school_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind.execute(
        sa.text(
            """
            UPDATE runs
            SET run_type = UPPER(TRIM(run_type))
            WHERE run_type IS NOT NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE stops
            SET type = CASE
                WHEN UPPER(REPLACE(REPLACE(TRIM(type), '-', '_'), ' ', '_')) = 'PICKUP' THEN 'PICKUP'
                WHEN UPPER(REPLACE(REPLACE(TRIM(type), '-', '_'), ' ', '_')) = 'DROPOFF' THEN 'DROPOFF'
                WHEN UPPER(REPLACE(REPLACE(TRIM(type), '-', '_'), ' ', '_')) = 'SCHOOL_ARRIVE' THEN 'SCHOOL_ARRIVE'
                WHEN UPPER(REPLACE(REPLACE(TRIM(type), '-', '_'), ' ', '_')) = 'SCHOOL_DEPART' THEN 'SCHOOL_DEPART'
                ELSE UPPER(TRIM(type))
            END
            WHERE type IS NOT NULL
            """
        )
    )


# -----------------------------------------------------------
# Downgrade
# Restore school_code and remove school-aware stop context
# -----------------------------------------------------------
def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE stops
            SET type = CASE
                WHEN type = 'PICKUP' THEN 'pickup'
                WHEN type = 'DROPOFF' THEN 'dropoff'
                ELSE LOWER(type)
            END
            WHERE type IS NOT NULL
            """
        )
    )

    with op.batch_alter_table("stops") as batch_op:
        batch_op.drop_constraint("fk_stops_school_id_schools", type_="foreignkey")
        batch_op.drop_column("school_id")

    with op.batch_alter_table("schools") as batch_op:
        batch_op.add_column(sa.Column("school_code", sa.String(), nullable=True))
        batch_op.alter_column("address", existing_type=sa.String(length=255), nullable=False)
