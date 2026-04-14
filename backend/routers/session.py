# ===========================================================
# backend/routers/session.py - Transitional Session Router
# -----------------------------------------------------------
# Temporary operator-session injection for legacy cleanup.
# ===========================================================

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from backend.models.operator import Operator


router = APIRouter()


class OperatorSessionRequest(BaseModel):
    operator_id: int


@router.post("/session/operator")
def set_operator_session(
    payload: OperatorSessionRequest = Body(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    operator = db.get(Operator, payload.operator_id)
    if not operator:
        raise HTTPException(status_code=404, detail="Operator not found")

    # Transitional/dev-only session bootstrap. This preserves the existing
    # session["operator_id"] contract used by operator-scoped endpoints.
    request.session["operator_id"] = operator.id
    request.session.pop("driver_id", None)
    return {
        "message": "Operator session set",
        "operator_id": operator.id,
    }


@router.post("/session/logout")
def clear_operator_session(request: Request):
    request.session.pop("driver_id", None)
    request.session.pop("operator_id", None)
    return {"message": "Session cleared"}
