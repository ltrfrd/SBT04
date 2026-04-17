"""prepare route and student district batch a transition

Revision ID: 20260416_route_student_district_batch_a
Revises: 20260415_rename_posttrip_photos
Create Date: 2026-04-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "20260416_route_student_district_batch_a"
down_revision = "20260415_rename_posttrip_photos"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _foreign_key_name(inspector, table_name: str, column_name: str, referred_table: str) -> str | None:
    for foreign_key in inspector.get_foreign_keys(table_name):
        constrained_columns = foreign_key.get("constrained_columns") or []
        if constrained_columns == [column_name] and foreign_key.get("referred_table") == referred_table:
            return foreign_key.get("name")
    return None


def _single_distinct_values(bind, sql: str, params: dict[str, object]) -> list[int]:
    rows = bind.execute(sa.text(sql), params).fetchall()
    values = []
    for row in rows:
        value = row[0]
        if value is None:
            continue
        values.append(int(value))
    return values


def _backfill_route_districts(bind) -> None:
    route_ids = [
        int(row[0])
        for row in bind.execute(
            sa.text(
                """
                SELECT id
                FROM routes
                WHERE district_id IS NULL
                ORDER BY id
                """
            )
        )
    ]

    for route_id in route_ids:
        inferred_values = []

        for source_name, sql in (
            (
                "linked schools",
                """
                SELECT DISTINCT schools.district_id
                FROM route_schools
                JOIN schools ON schools.id = route_schools.school_id
                WHERE route_schools.route_id = :route_id
                ORDER BY schools.district_id
                """,
            ),
            (
                "linked students",
                """
                SELECT DISTINCT schools.district_id
                FROM students
                JOIN schools ON schools.id = students.school_id
                WHERE students.route_id = :route_id
                ORDER BY schools.district_id
                """,
            ),
            (
                "linked school stops",
                """
                SELECT DISTINCT schools.district_id
                FROM stops
                JOIN schools ON schools.id = stops.school_id
                WHERE stops.route_id = :route_id
                ORDER BY schools.district_id
                """,
            ),
        ):
            values = _single_distinct_values(bind, sql, {"route_id": route_id})
            if len(values) > 1:
                raise RuntimeError(
                    f"Cannot backfill routes.district_id for route {route_id}: "
                    f"{source_name} point to multiple districts {values}."
                )
            if values:
                inferred_values.append((source_name, values[0]))

        distinct_district_ids = sorted({district_id for _, district_id in inferred_values})
        if len(distinct_district_ids) > 1:
            raise RuntimeError(
                f"Cannot backfill routes.district_id for route {route_id}: "
                f"planning relationships disagree across sources {inferred_values}."
            )
        if not distinct_district_ids:
            raise RuntimeError(
                f"Cannot backfill routes.district_id for route {route_id}: "
                "no linked school, student, or school-stop district could be inferred safely."
            )

        bind.execute(
            sa.text(
                """
                UPDATE routes
                SET district_id = :district_id
                WHERE id = :route_id
                """
            ),
            {"route_id": route_id, "district_id": distinct_district_ids[0]},
        )


def _validate_student_district_consistency(bind) -> None:
    conflicting_rows = bind.execute(
        sa.text(
            """
            SELECT students.id, schools.district_id, routes.district_id
            FROM students
            JOIN schools ON schools.id = students.school_id
            JOIN routes ON routes.id = students.route_id
            WHERE students.route_id IS NOT NULL
              AND routes.district_id IS NOT NULL
              AND schools.district_id != routes.district_id
            ORDER BY students.id
            """
        )
    ).fetchall()
    if conflicting_rows:
        first_row = conflicting_rows[0]
        raise RuntimeError(
            "Cannot backfill students.district_id because a student's school district "
            f"disagrees with its linked route district. Example student {first_row[0]}: "
            f"school district {first_row[1]}, route district {first_row[2]}."
        )


def _backfill_student_districts(bind) -> None:
    _validate_student_district_consistency(bind)

    bind.execute(
        sa.text(
            """
            UPDATE students
            SET district_id = (
                SELECT schools.district_id
                FROM schools
                WHERE schools.id = students.school_id
            )
            WHERE district_id IS NULL
            """
        )
    )

    remaining_null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM students WHERE district_id IS NULL")
    ).scalar_one()
    if remaining_null_count:
        raise RuntimeError(
            "Cannot complete student district backfill because some students still have NULL district_id "
            "after using their linked school district."
        )


def _make_operator_nullable(bind, inspector, table_name: str, fk_index_name: str) -> None:
    if not _table_exists(inspector, table_name) or not _column_exists(inspector, table_name, "operator_id"):
        return

    fk_name = _foreign_key_name(inspector, table_name, "operator_id", "operators")
    with op.batch_alter_table(table_name) as batch_op:
        if fk_name is not None:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.alter_column("operator_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            f"fk_{table_name}_operator_id_operators",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="SET NULL",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, table_name, fk_index_name):
        op.create_index(fk_index_name, table_name, ["operator_id"], unique=False)


def _restore_operator_not_null(bind, inspector, table_name: str) -> None:
    if not _table_exists(inspector, table_name) or not _column_exists(inspector, table_name, "operator_id"):
        return

    null_operator_count = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE operator_id IS NULL")
    ).scalar_one()
    if null_operator_count:
        raise RuntimeError(
            f"Cannot downgrade {table_name}.operator_id to NOT NULL while NULL operator references exist."
        )

    fk_name = _foreign_key_name(inspector, table_name, "operator_id", "operators")
    with op.batch_alter_table(table_name) as batch_op:
        if fk_name is not None:
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.alter_column("operator_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            f"fk_{table_name}_operator_id_operators",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "routes") and _column_exists(inspector, "routes", "district_id"):
        _backfill_route_districts(bind)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "students") and _column_exists(inspector, "students", "district_id"):
        _backfill_student_districts(bind)

    inspector = sa.inspect(bind)
    _make_operator_nullable(bind, inspector, "routes", "ix_routes_operator_id")

    inspector = sa.inspect(bind)
    _make_operator_nullable(bind, inspector, "students", "ix_students_operator_id")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _restore_operator_not_null(bind, inspector, "students")

    inspector = sa.inspect(bind)
    _restore_operator_not_null(bind, inspector, "routes")
