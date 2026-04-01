# ===========================================================
# backend/routers/auth.py - SBT Auth Router
# -----------------------------------------------------------
# Session login/logout endpoints extracted from app bootstrap
# ===========================================================

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from backend.models import driver as driver_model
from backend.utils.auth import login_driver, logout_driver


router = APIRouter()


# -----------------------------------------------------------
# LOGIN / LOGOUT ENDPOINTS
# -----------------------------------------------------------
@router.post("/login")
def login(payload: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    driver_id = int(payload["driver_id"])
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    login_driver(request, driver_id)
    return {"message": "Logged in", "driver_id": driver_id}


@router.post("/logout")
def logout(request: Request):
    """Clears current driver session."""
    logout_driver(request)
    return {"message": "Logged out"}
