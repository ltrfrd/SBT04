# ===========================================================
# backend/utils/auth.py — BST Authentication Utilities
# -----------------------------------------------------------
# ONLY session auth. No JWT. No conflicts.
# ===========================================================

from fastapi import Request, HTTPException, status, Depends
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from database import get_db
from backend.models import driver as driver_model

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


# -----------------------------------------------------------
# SESSION AUTH: GET CURRENT DRIVER
# -----------------------------------------------------------
def get_current_driver(
    request: Request, db: Session = Depends(get_db)
) -> driver_model.Driver:
    """Get logged-in driver from session."""
    driver_id = request.session.get("driver_id")
    operator_id = request.session.get("operator_id")
    if not driver_id or not operator_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    driver = db.get(driver_model.Driver, driver_id)
    if not driver or driver.operator_id != operator_id:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


# -----------------------------------------------------------
# LOGIN / LOGOUT HELPERS
# -----------------------------------------------------------
def hash_driver_pin(pin: str) -> str:
    return pwd_context.hash(pin)


def verify_driver_pin(pin: str, pin_hash: str | None) -> bool:
    if not pin_hash:
        return False
    return pwd_context.verify(pin, pin_hash)


def authenticate_driver(db: Session, driver_id: int, pin: str) -> driver_model.Driver | None:
    driver = db.get(driver_model.Driver, driver_id)
    if not driver or not verify_driver_pin(pin, driver.pin_hash):
        return None
    return driver


def login_driver(request: Request, driver: driver_model.Driver):
    """Set driver and operator in session."""
    request.session["driver_id"] = driver.id
    request.session["operator_id"] = driver.operator_id


def logout_driver(request: Request):
    """Clear session."""
    request.session.pop("driver_id", None)
    request.session.pop("operator_id", None)

