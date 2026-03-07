from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _sqlite_unique_columns(msg: str) -> tuple[str, ...]:
    marker = "UNIQUE constraint failed:"
    if marker not in msg:
        return ()

    _, rhs = msg.split(marker, 1)
    raw_cols = [piece.strip() for piece in rhs.split(",") if piece.strip()]
    return tuple(item.rsplit(".", 1)[-1] for item in raw_cols)


def raise_conflict_if_unique(
    db: Session,
    err: IntegrityError,
    *,
    constraint_name: str,
    sqlite_columns: tuple[str, ...],
    detail: str,
) -> None:
    dialect = db.get_bind().dialect.name
    orig = getattr(err, "orig", None)

    if dialect == "postgresql" and orig is not None:
        pgcode = getattr(orig, "pgcode", None)
        diag = getattr(orig, "diag", None)
        diag_name = getattr(diag, "constraint_name", None) if diag else None
        if pgcode == "23505" and diag_name == constraint_name:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    if dialect == "mysql" and orig is not None:
        errno = getattr(orig, "errno", None)
        if errno == 1062:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    if dialect == "sqlite":
        msg = str(orig or err)
        cols = _sqlite_unique_columns(msg)
        if cols == sqlite_columns:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

