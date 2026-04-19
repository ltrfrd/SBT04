# ===========================================================
# backend/routers/yard.py - FleetOS Yard Router
# ===========================================================

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from backend.models.operator import Operator
from backend.models.yard import Yard
from backend.utils.operator_scope import get_operator_context


router = APIRouter(prefix="/yards", tags=["Yards"])


class YardCreate(BaseModel):
    name: str


class YardOut(BaseModel):
    id: int
    name: str
    operator_id: int

    model_config = {"from_attributes": True}


@router.post("/", response_model=YardOut, status_code=status.HTTP_201_CREATED)
def create_yard(
    payload: YardCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    yard = Yard(name=payload.name, operator_id=operator.id)
    db.add(yard)
    db.commit()
    db.refresh(yard)
    return yard


@router.get("/", response_model=List[YardOut])
def list_yards(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return db.query(Yard).filter(Yard.operator_id == operator.id).all()


@router.get("/{yard_id}", response_model=YardOut)
def get_yard(
    yard_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    yard = db.query(Yard).filter(Yard.id == yard_id, Yard.operator_id == operator.id).first()
    if not yard:
        raise HTTPException(status_code=404, detail="Yard not found")
    return yard
