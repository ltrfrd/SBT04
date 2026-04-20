from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import schemas
from backend.models.operator import Operator
from backend.utils.operator_scope import get_operator_context
from database import get_db


router = APIRouter(prefix="/operators", tags=["Operators"])


@router.get("/me", response_model=schemas.OperatorOut)
def get_current_operator(
    operator: Operator = Depends(get_operator_context),
):
    return operator


@router.get("/{operator_id}", response_model=schemas.OperatorOut)
def get_operator(
    operator_id: int,
    operator: Operator = Depends(get_operator_context),
):
    if operator.id != operator_id:
        raise HTTPException(status_code=404, detail="Operator not found")
    return operator


@router.put("/me", response_model=schemas.OperatorOut)
def update_current_operator(
    payload: schemas.OperatorUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    operator.name = payload.name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Operator name already exists")
    db.refresh(operator)
    return operator
