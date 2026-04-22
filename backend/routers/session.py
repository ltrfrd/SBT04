# ===========================================================
# backend/routers/session.py - Session Router
# -----------------------------------------------------------
# Session clearing endpoint only.
# ===========================================================

from fastapi import APIRouter, Request


router = APIRouter()


@router.post("/session/logout")
def clear_operator_session(request: Request):
    request.session.pop("driver_id", None)
    request.session.pop("operator_id", None)
    return {"message": "Session cleared"}
