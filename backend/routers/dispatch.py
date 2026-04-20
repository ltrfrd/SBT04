# ===========================================================
# backend/routers/dispatch.py — BST Dispatch Router
# -----------------------------------------------------------
# View dispatch summaries and record daily charter hours.
# ===========================================================
from datetime import date, time  # For date/time fields
from typing import List  # List typing

from fastapi import APIRouter, Depends, HTTPException, Query, status  # FastAPI helpers
from sqlalchemy.orm import Session  # DB session

from backend import schemas  # Dispatch schemas
from backend.models.operator import Operator
from backend.models import dispatch as dispatch_model  # Dispatch module model
from backend.models import driver as driver_model  # Validate driver link
from backend.models.yard import Yard
from database import get_db  # DB dependency
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_dispatcher_or_404
from backend.utils.operator_scope import get_operator_scoped_driver_or_404


# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(prefix="/dispatch", tags=["Dispatch"])


# -----------------------------------------------------------
# Execution Dispatch Endpoints
# -----------------------------------------------------------
# -----------------------------------------------------------
# POST /dispatch/charter
# - Driver submits daily charter hours
# -----------------------------------------------------------
@router.post(
    "/charter", response_model=schemas.DispatchOut, status_code=status.HTTP_201_CREATED
)
# -----------------------------------------------------------
# - Charter submission with Swagger guidance
# - Clean date and time input documentation
# -----------------------------------------------------------
def log_charter_hours(
    driver_id: int,                                                 # Driver who did the charter
    charter_start: time = Query(
        ...,
        description="HH:MM (24-hour format)",                       # Simple start time format
        examples=["08:00"],                                         # Simple Swagger example
    ),
    charter_end: time = Query(
        ...,
        description="HH:MM (24-hour format)",                       # Simple end time format
        examples=["16:00"],                                         # Simple Swagger example
    ),
    work_date: date = Query(
        ...,
        description="YYYY-MM-DD",                                   # Simple date format
        examples=["2026-03-23"],                                    # Valid Swagger example
    ),
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Drivers submit charter start/end; hours auto-calculated."""
    get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    record = dispatch_model.DispatchRecord(                         # Create dispatch-backed work record
        driver_id=driver_id,
        work_date=work_date,                                        # Save submitted work date
        charter_start=charter_start,
        charter_end=charter_end,
    )
    record.charter_hours = record.calculate_charter_hours            # Compute hours
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

# -----------------------------------------------------------
# GET /dispatch
# - List all dispatch entries
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.DispatchOut])
def get_all_dispatch_records(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return all dispatch records."""
    return (
        db.query(dispatch_model.DispatchRecord)
        .join(driver_model.Driver, driver_model.Driver.id == dispatch_model.DispatchRecord.driver_id)
        .join(driver_model.Driver.yard)
        .filter(Yard.operator_id == operator.id)
        .all()
    )


# -----------------------------------------------------------
# GET /dispatch/driver/{driver_id}
# - Driver's personal summary
# -----------------------------------------------------------
@router.get("/driver/{driver_id}", response_model=List[schemas.DispatchOut])
def get_driver_dispatch_records(
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return all dispatch records for a driver."""
    get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )
    return (
        db.query(dispatch_model.DispatchRecord)
        .filter(dispatch_model.DispatchRecord.driver_id == driver_id)
        .all()
    )


# -----------------------------------------------------------
# - Approve a dispatch record
# - Keep DB model compatibility unchanged
# -----------------------------------------------------------
@router.put("/{dispatch_id}/approve", response_model=schemas.DispatchOut)
def approve_dispatch_record(
    dispatch_id: int,
    payload: schemas.DispatchApprovalRequest,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Approve a dispatch record as a dispatcher."""
    record = db.get(dispatch_model.DispatchRecord, dispatch_id)
    if not record:
        raise HTTPException(status_code=404, detail="Dispatch record not found")

    dispatcher = get_operator_scoped_dispatcher_or_404(
        db=db,
        dispatcher_id=payload.dispatcher_id,
        operator_id=operator.id,
        detail="Dispatcher not found",
    )
    driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=record.driver_id,
        operator_id=operator.id,
        detail="Dispatch record not found",
    )
    if driver.yard_id is None:
        raise HTTPException(status_code=400, detail="Driver is missing yard assignment")
    if dispatcher.yard_id != driver.yard_id:
        raise HTTPException(
            status_code=403,
            detail="Dispatcher cannot approve records outside assigned yard",
        )
    if record.approved:
        if record.approved_by_dispatcher_id == dispatcher.id:
            return record
        raise HTTPException(status_code=409, detail="Dispatch record already approved")

    record.approved = True
    record.approved_by_dispatcher_id = dispatcher.id
    db.commit()
    db.refresh(record)
    return record

