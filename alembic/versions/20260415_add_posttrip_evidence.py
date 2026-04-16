"""add posttrip evidence table

Revision ID: 20260415_add_posttrip_evidence
Revises: 20260414_drop_school_operator_ownership
Create Date: 2026-04-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260415_add_posttrip_evidence"
down_revision = "20260414_drop_school_operator_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "posttrip_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("posttrip_inspection_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="camera"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("captured_lat", sa.Float(), nullable=True),
        sa.Column("captured_lng", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["posttrip_inspection_id"], ["posttrip_inspections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "evidence_type", name="uq_posttrip_evidence_run_type"),
    )
    op.create_index(op.f("ix_posttrip_evidence_id"), "posttrip_evidence", ["id"], unique=False)
    op.create_index(op.f("ix_posttrip_evidence_posttrip_inspection_id"), "posttrip_evidence", ["posttrip_inspection_id"], unique=False)
    op.create_index(op.f("ix_posttrip_evidence_run_id"), "posttrip_evidence", ["run_id"], unique=False)
    op.create_index(op.f("ix_posttrip_evidence_phase"), "posttrip_evidence", ["phase"], unique=False)
    op.create_index(op.f("ix_posttrip_evidence_evidence_type"), "posttrip_evidence", ["evidence_type"], unique=False)

    with op.batch_alter_table("posttrip_evidence") as batch_op:
        batch_op.alter_column("source", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_posttrip_evidence_evidence_type"), table_name="posttrip_evidence")
    op.drop_index(op.f("ix_posttrip_evidence_phase"), table_name="posttrip_evidence")
    op.drop_index(op.f("ix_posttrip_evidence_run_id"), table_name="posttrip_evidence")
    op.drop_index(op.f("ix_posttrip_evidence_posttrip_inspection_id"), table_name="posttrip_evidence")
    op.drop_index(op.f("ix_posttrip_evidence_id"), table_name="posttrip_evidence")
    op.drop_table("posttrip_evidence")
