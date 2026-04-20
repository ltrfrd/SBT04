from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import schemas
from backend.models.dispatcher import Dispatcher
from backend.models.operator import Operator
from backend.models.yard import Yard
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_dispatcher_or_404
from backend.utils.operator_scope import get_operator_scoped_yard_or_404
from database import get_db


router = APIRouter(prefix="/dispatchers", tags=["Dispatchers"])

def _validate_dispatcher_uniqueness(
    *,
    db: Session,
    email: str | None = None,
    exclude_id: int | None = None,
) -> None:
    if email is None:
        return

    query = db.query(Dispatcher).filter(Dispatcher.email == email)
    if exclude_id is not None:
        query = query.filter(Dispatcher.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=409, detail="Dispatcher email already exists")


@router.post(
    "/",
    response_model=schemas.DispatcherOut,
    status_code=status.HTTP_201_CREATED,
)
def create_dispatcher(
    payload: schemas.DispatcherCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    get_operator_scoped_yard_or_404(
        db=db,
        yard_id=payload.yard_id,
        operator_id=operator.id,
        detail="Yard not found",
    )
    _validate_dispatcher_uniqueness(db=db, email=str(payload.email))

    dispatcher = Dispatcher(**payload.model_dump())
    db.add(dispatcher)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Dispatcher could not be created")
    db.refresh(dispatcher)
    return dispatcher


@router.get("/", response_model=List[schemas.DispatcherOut])
def list_dispatchers(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return (
        db.query(Dispatcher)
        .join(Dispatcher.yard)
        .filter(Yard.operator_id == operator.id)
        .order_by(Dispatcher.name.asc(), Dispatcher.id.asc())
        .all()
    )


@router.get("/{dispatcher_id}", response_model=schemas.DispatcherOut)
def get_dispatcher(
    dispatcher_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return _get_operator_scoped_dispatcher_or_404(
        db=db,
        dispatcher_id=dispatcher_id,
        operator_id=operator.id,
        detail="Dispatcher not found",
    )


@router.put("/{dispatcher_id}", response_model=schemas.DispatcherOut)
def update_dispatcher(
    dispatcher_id: int,
    payload: schemas.DispatcherUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    dispatcher = _get_operator_scoped_dispatcher_or_404(
        db=db,
        dispatcher_id=dispatcher_id,
        operator_id=operator.id,
        detail="Dispatcher not found",
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

    _validate_dispatcher_uniqueness(
        db=db,
        email=update_data.get("email"),
        exclude_id=dispatcher.id,
    )

    for key, value in update_data.items():
        setattr(dispatcher, key, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Dispatcher could not be updated")
    db.refresh(dispatcher)
    return dispatcher


@router.delete("/{dispatcher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dispatcher(
    dispatcher_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    dispatcher = _get_operator_scoped_dispatcher_or_404(
        db=db,
        dispatcher_id=dispatcher_id,
        operator_id=operator.id,
        detail="Dispatcher not found",
    )
    db.delete(dispatcher)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Dispatcher cannot be deleted while referenced by dispatch approvals",
        )
    return None
