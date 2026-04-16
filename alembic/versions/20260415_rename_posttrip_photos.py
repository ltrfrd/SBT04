"""rename posttrip photos table and columns

Revision ID: 20260415_rename_posttrip_photos
Create Date: 2026-04-15 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260415_rename_posttrip_photos"
down_revision = "20260415_add_posttrip_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    legacy_table = "posttrip_evidence"
    legacy_type_column = "evidence_type"
    legacy_unique = "uq_posttrip_evidence_run_type"
    legacy_id_index = "ix_posttrip_evidence_id"
    legacy_inspection_index = "ix_posttrip_evidence_posttrip_inspection_id"
    legacy_run_index = "ix_posttrip_evidence_run_id"
    legacy_phase_index = "ix_posttrip_evidence_phase"
    legacy_type_index = "ix_posttrip_evidence_evidence_type"

    op.drop_index(legacy_id_index, table_name=legacy_table)
    op.drop_index(legacy_inspection_index, table_name=legacy_table)
    op.drop_index(legacy_run_index, table_name=legacy_table)
    op.drop_index(legacy_phase_index, table_name=legacy_table)
    op.drop_index(legacy_type_index, table_name=legacy_table)
    op.rename_table(legacy_table, "posttrip_photos")

    with op.batch_alter_table("posttrip_photos") as batch_op:
        batch_op.drop_constraint(legacy_unique, type_="unique")
        batch_op.alter_column(
            legacy_type_column,
            new_column_name="photo_type",
            existing_type=sa.String(length=50),
            existing_nullable=False,
        )
        batch_op.create_unique_constraint("uq_posttrip_photos_run_type", ["run_id", "photo_type"])

    op.create_index("ix_posttrip_photos_id", "posttrip_photos", ["id"], unique=False)
    op.create_index("ix_posttrip_photos_posttrip_inspection_id", "posttrip_photos", ["posttrip_inspection_id"], unique=False)
    op.create_index("ix_posttrip_photos_run_id", "posttrip_photos", ["run_id"], unique=False)
    op.create_index("ix_posttrip_photos_phase", "posttrip_photos", ["phase"], unique=False)
    op.create_index("ix_posttrip_photos_photo_type", "posttrip_photos", ["photo_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_posttrip_photos_photo_type", table_name="posttrip_photos")
    op.drop_index("ix_posttrip_photos_phase", table_name="posttrip_photos")
    op.drop_index("ix_posttrip_photos_run_id", table_name="posttrip_photos")
    op.drop_index("ix_posttrip_photos_posttrip_inspection_id", table_name="posttrip_photos")
    op.drop_index("ix_posttrip_photos_id", table_name="posttrip_photos")

    with op.batch_alter_table("posttrip_photos") as batch_op:
        batch_op.drop_constraint("uq_posttrip_photos_run_type", type_="unique")
        batch_op.alter_column(
            "photo_type",
            new_column_name="evidence_type",
            existing_type=sa.String(length=50),
            existing_nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_posttrip_evidence_run_type",
            ["run_id", "evidence_type"],
        )

    op.rename_table("posttrip_photos", "posttrip_evidence")

    op.create_index(
        "ix_posttrip_evidence_id",
        "posttrip_evidence",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_posttrip_evidence_posttrip_inspection_id",
        "posttrip_evidence",
        ["posttrip_inspection_id"],
        unique=False,
    )
    op.create_index(
        "ix_posttrip_evidence_run_id",
        "posttrip_evidence",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_posttrip_evidence_phase",
        "posttrip_evidence",
        ["phase"],
        unique=False,
    )
    op.create_index(
        "ix_posttrip_evidence_evidence_type",
        "posttrip_evidence",
        ["evidence_type"],
        unique=False,
    )
