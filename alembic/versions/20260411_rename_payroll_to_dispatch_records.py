"""rename payroll table to dispatch records

Revision ID: 20260411_rename_payroll_to_dispatch_records
Revises: 20260411_rename_company_to_operator
Create Date: 2026-04-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260411_rename_payroll_to_dispatch_records"
down_revision = "20260411_rename_company_to_operator"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "payrolls") and not _table_exists(inspector, "dispatch_records"):
        op.rename_table("payrolls", "dispatch_records")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "dispatch_records") and not _table_exists(inspector, "payrolls"):
        op.rename_table("dispatch_records", "payrolls")
