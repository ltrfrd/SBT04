# ===========================================================
# backend/routers/payroll.py — BST Payroll Router
# -----------------------------------------------------------
# View payroll summaries and record daily charter hours.
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI helpers
from sqlalchemy.orm import Session  # DB session
from typing import List  # List typing
from datetime import date, time  # For date/time fields
from database import get_db  # DB dependency
from backend import schemas  # Payroll schemas
from backend.models import payroll as payroll_model  # Payroll model
from backend.models import driver as driver_model  # Validate driver link

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(prefix="/payroll", tags=["Payroll"])


# -----------------------------------------------------------
# POST /payroll/charter → Driver submits daily charter hours
# -----------------------------------------------------------
@router.post(
    "/charter", response_model=schemas.PayrollOut, status_code=status.HTTP_201_CREATED
)
def log_charter_hours(
    driver_id: int,  # Driver who did the charter
    work_date: date,  # Date of charter
    charter_start: time,  # Start time
    charter_end: time,  # End time
    db: Session = Depends(get_db),
):
    """Drivers submit charter start/end; hours auto-calculated."""
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    # Create record; hours auto-computed via property
    record = payroll_model.Payroll(
        driver_id=driver_id,
        work_date=work_date,
        charter_start=charter_start,
        charter_end=charter_end,
    )
    record.charter_hours = record.calculate_charter_hours  # Compute hours
    db.add(record)
    db.commit()
    db.refresh(record)
    return record  # Return full PayrollOut


# -----------------------------------------------------------
# GET /payroll → List all payroll entries (for department)
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.PayrollOut])
def get_all_payroll(db: Session = Depends(get_db)):
    """Payroll department retrieves every entry."""
    return db.query(payroll_model.Payroll).all()


# -----------------------------------------------------------
# GET /payroll/driver/{driver_id} → Driver’s personal summary
# -----------------------------------------------------------
@router.get("/driver/{driver_id}", response_model=List[schemas.PayrollOut])
def get_driver_payroll(driver_id: int, db: Session = Depends(get_db)):
    """List all payroll entries for one driver."""
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return (
        db.query(payroll_model.Payroll)
        .filter(payroll_model.Payroll.driver_id == driver_id)
        .all()
    )


# -----------------------------------------------------------
# PUT /payroll/{id}/approve → Payroll verification
# -----------------------------------------------------------
@router.put("/{payroll_id}/approve", response_model=schemas.PayrollOut)
def approve_payroll(payroll_id: int, db: Session = Depends(get_db)):
    """Payroll department marks a record as approved."""
    record = db.get(payroll_model.Payroll, payroll_id)
    if not record:
        raise HTTPException(status_code=404, detail="Payroll record not found")
    record.approved = True
    db.commit()
    db.refresh(record)
    return record
