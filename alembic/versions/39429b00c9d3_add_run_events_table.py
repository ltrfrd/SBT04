"""add run_events table

Revision ID: 39429b00c9d3
Revises: f216358c4479
Create Date: 2026-03-10 06:01:52.528776

"""
from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '39429b00c9d3'
down_revision = 'f216358c4479'
branch_labels = None
depends_on = None


# -----------------------------------------------------------
# Upgrade — create run_events table
# -----------------------------------------------------------
def upgrade() -> None:
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),          # Event ID
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),  # Related run
        sa.Column("stop_id", sa.Integer(), sa.ForeignKey("stops.id"), nullable=True), # Stop where event occurred
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=True),  # Student involved
        sa.Column("event_type", sa.String(), nullable=False),                 # ARRIVE | PICKUP | DROPOFF
        sa.Column("timestamp", sa.DateTime(), nullable=False),                # Event timestamp
    )


# -----------------------------------------------------------
# Downgrade — drop run_events table
# -----------------------------------------------------------
def downgrade() -> None:
    op.drop_table("run_events")