from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import schemas
from backend.models.operator import Operator
from backend.models.yard import Yard
from backend.models.yard_supervisor import YardSupervisor
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_yard_or_404
from database import get_db


router = APIRouter(prefix="/yard-supervisors", tags=["Yard Supervisors"])


def _get_operator_scoped_yard_supervisor_or_404(
    *,
    db: Session,
    yard_supervisor_id: int,
    operator_id: int,
    detail: str,
) -> YardSupervisor:
    yard_supervisor = (
        db.query(YardSupervisor)
        .join(YardSupervisor.yard)
        .filter(YardSupervisor.id == yard_supervisor_id)
        .filter(Yard.operator_id == operator_id)
        .first()
    )
    if not yard_supervisor:
        raise HTTPException(status_code=404, detail=detail)
    return yard_supervisor


def _validate_yard_supervisor_uniqueness(
    *,
    db: Session,
    yard_id: int | None = None,
    email: str | None = None,
    exclude_id: int | None = None,
) -> None:
    if yard_id is not None:
        query = db.query(YardSupervisor).filter(YardSupervisor.yard_id == yard_id)
        if exclude_id is not None:
            query = query.filter(YardSupervisor.id != exclude_id)
        if query.first():
            raise HTTPException(status_code=409, detail="Yard already has a supervisor")

    if email is not None:
        query = db.query(YardSupervisor).filter(YardSupervisor.email == email)
        if exclude_id is not None:
            query = query.filter(YardSupervisor.id != exclude_id)
        if query.first():
            raise HTTPException(status_code=409, detail="Supervisor email already exists")


@router.post(
    "/",
    response_model=schemas.YardSupervisorOut,
    status_code=status.HTTP_201_CREATED,
)
def create_yard_supervisor(
    payload: schemas.YardSupervisorCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    get_operator_scoped_yard_or_404(
        db=db,
        yard_id=payload.yard_id,
        operator_id=operator.id,
        detail="Yard not found",
    )
    _validate_yard_supervisor_uniqueness(
        db=db,
        yard_id=payload.yard_id,
        email=str(payload.email),
    )

    yard_supervisor = YardSupervisor(**payload.model_dump())
    db.add(yard_supervisor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supervisor could not be created")
    db.refresh(yard_supervisor)
    return yard_supervisor


@router.get("/", response_model=List[schemas.YardSupervisorOut])
def list_yard_supervisors(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return (
        db.query(YardSupervisor)
        .join(YardSupervisor.yard)
        .filter(Yard.operator_id == operator.id)
        .order_by(YardSupervisor.name.asc(), YardSupervisor.id.asc())
        .all()
    )


@router.get("/{yard_supervisor_id}", response_model=schemas.YardSupervisorOut)
def get_yard_supervisor(
    yard_supervisor_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return _get_operator_scoped_yard_supervisor_or_404(
        db=db,
        yard_supervisor_id=yard_supervisor_id,
        operator_id=operator.id,
        detail="Yard supervisor not found",
    )


@router.put("/{yard_supervisor_id}", response_model=schemas.YardSupervisorOut)
def update_yard_supervisor(
    yard_supervisor_id: int,
    payload: schemas.YardSupervisorUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    yard_supervisor = _get_operator_scoped_yard_supervisor_or_404(
        db=db,
        yard_supervisor_id=yard_supervisor_id,
        operator_id=operator.id,
        detail="Yard supervisor not found",
    )

    update_data = payload.model_dump(exclude_unset=True)
    target_yard_id = update_data.get("yard_id")
    if target_yard_id is not None:
        get_operator_scoped_yard_or_404(
            db=db,
            yard_id=target_yard_id,
            operator_id=operator.id,
            detail="Yard not found",
        )

    _validate_yard_supervisor_uniqueness(
        db=db,
        yard_id=target_yard_id,
        email=update_data.get("email"),
        exclude_id=yard_supervisor.id,
    )

    for key, value in update_data.items():
        setattr(yard_supervisor, key, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supervisor could not be updated")
    db.refresh(yard_supervisor)
    return yard_supervisor


@router.delete("/{yard_supervisor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_yard_supervisor(
    yard_supervisor_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    yard_supervisor = _get_operator_scoped_yard_supervisor_or_404(
        db=db,
        yard_supervisor_id=yard_supervisor_id,
        operator_id=operator.id,
        detail="Yard supervisor not found",
    )
    db.delete(yard_supervisor)
    db.commit()
    return None
