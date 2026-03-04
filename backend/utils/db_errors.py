# =============================================================================
# backend/utils/db_errors.py
# -----------------------------------------------------------------------------
# Centralized helpers to translate SQLAlchemy IntegrityError into HTTP errors.
# Goal:
#   - Use structured error info when the DB/driver provides it (Postgres/MySQL)
#   - Minimal fallback for SQLite (message is the only signal available)
# =============================================================================

from __future__ import annotations  # Forward typing support

from fastapi import HTTPException, status  # HTTP error response
from sqlalchemy.exc import IntegrityError  # SQLAlchemy integrity exceptions
from sqlalchemy.orm import Session  # Session type


def raise_conflict_if_unique(
    db: Session,
    err: IntegrityError,
    *,
    constraint_name: str,
    sqlite_columns: tuple[str, ...],
    detail: str,
) -> None:
    """
    Raise HTTP 409 if the IntegrityError corresponds to a UNIQUE constraint violation.

    Args:
        db: SQLAlchemy session (used to detect dialect/driver)
        err: IntegrityError thrown by db.commit()
        constraint_name: The DB constraint name (works well on Postgres)
        sqlite_columns: Column list used in SQLite error message fallback
        detail: Message returned in HTTP 409

    Notes:
        - PostgreSQL (psycopg2) exposes:
            * err.orig.pgcode == "23505" (unique_violation)
            * err.orig.diag.constraint_name
        - SQLite does NOT expose constraint metadata reliably; it only provides text.
          So we use a minimal fallback that checks the specific UNIQUE failure columns.
    """
    dialect = db.get_bind().dialect.name  # e.g. "sqlite", "postgresql", "mysql"

    orig = getattr(err, "orig", None)  # Driver-level exception (if available)

    # -------------------------------------------------------------------------
    # PostgreSQL (psycopg2) — structured unique violation
    # -------------------------------------------------------------------------
    if dialect == "postgresql" and orig is not None:
        pgcode = getattr(orig, "pgcode", None)  # "23505" for unique_violation
        diag = getattr(orig, "diag", None)  # Has constraint_name
        diag_name = getattr(diag, "constraint_name", None) if diag else None

        if pgcode == "23505" and diag_name == constraint_name:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # -------------------------------------------------------------------------
    # MySQL (pymysql / mysqlclient) — structured unique violation codes
    # -------------------------------------------------------------------------
    if dialect == "mysql" and orig is not None:
        # Common MySQL duplicate-entry error code is 1062
        errno = getattr(orig, "errno", None)
        if errno == 1062:
            # MySQL doesn't reliably include constraint name across drivers,
            # so treat any 1062 as conflict for this endpoint.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # -------------------------------------------------------------------------
    # SQLite — minimal fallback (SQLite exposes only message text)
    # -------------------------------------------------------------------------
    if dialect == "sqlite":
        msg = str(orig or err)  # SQLite gives message via exception text
        # Example: "UNIQUE constraint failed: stops.route_id, stops.sequence"
        expected = ", ".join(f"stops.{c}" for c in sqlite_columns)
        if "UNIQUE constraint failed:" in msg and expected in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # If it wasn't the unique constraint we care about, do nothing.
