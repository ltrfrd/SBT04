# ===========================================================
# backend/utils/auth.py — BST Authentication Utilities
# -----------------------------------------------------------
# ONLY session auth. No JWT. No conflicts.
# ===========================================================

from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from database import get_db
from backend.models import driver as driver_model


# -----------------------------------------------------------
# SESSION AUTH: GET CURRENT DRIVER
# -----------------------------------------------------------
def get_current_driver(
    request: Request, db: Session = Depends(get_db)
) -> driver_model.Driver:
    """Get logged-in driver from session."""
    driver_id = request.session.get("driver_id")
    if not driver_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


# -----------------------------------------------------------
# LOGIN / LOGOUT HELPERS
# -----------------------------------------------------------
def login_driver(request: Request, driver_id: int):
    """Set driver_id in session."""
    request.session["driver_id"] = driver_id


def logout_driver(request: Request):
    """Clear session."""
    request.session.pop("driver_id", None)
