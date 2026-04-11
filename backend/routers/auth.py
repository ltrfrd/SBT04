# ===========================================================
# backend/routers/auth.py - SBT Auth Router
# -----------------------------------------------------------
# Session login/logout endpoints extracted from app bootstrap
# ===========================================================

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from backend.utils.auth import authenticate_driver, login_driver, logout_driver


router = APIRouter()


# -----------------------------------------------------------
# LOGIN / LOGOUT ENDPOINTS
# -----------------------------------------------------------
@router.post("/login")
def login(payload: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    driver_id = int(payload["driver_id"])
    pin = str(payload.get("pin", "")).strip()
    driver = authenticate_driver(db, driver_id, pin)
    if not driver:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    login_driver(request, driver)
    return {
        "message": "Logged in",
        "driver_id": driver.id,
        "operator_id": driver.operator_id,
    }


@router.post("/logout")
def logout(request: Request):
    """Clears current driver session."""
    logout_driver(request)
    return {"message": "Logged out"}

