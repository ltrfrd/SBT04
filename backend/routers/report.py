# ===========================================================
# backend/routers/report.py — BST Reports Router
# -----------------------------------------------------------
# Exposes API endpoints for driver, route, and payroll reports.
# Uses backend/utils/report_generator.py functions.
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI components
from sqlalchemy.orm import Session  # DB session
from datetime import date  # For date filtering
from database import get_db  # DB dependency
from backend.utils import report_generator  # Import generator functions

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/reports",  # Base path for all reporting endpoints
    tags=["Reports"],  # Swagger section title
)


# -----------------------------------------------------------
# GET /reports/driver/{driver_id} → Driver summary
# -----------------------------------------------------------
@router.get("/driver/{driver_id}", status_code=status.HTTP_200_OK)
def get_driver_report(driver_id: int, db: Session = Depends(get_db)):
    """Return work summary for one driver."""
    report = report_generator.driver_summary(db, driver_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report


# -----------------------------------------------------------
# GET /reports/route/{route_id} → Route summary
# -----------------------------------------------------------
@router.get("/route/{route_id}", status_code=status.HTTP_200_OK)
def get_route_report(route_id: int, db: Session = Depends(get_db)):
    """Return detailed report for one route."""
    report = report_generator.route_summary(db, route_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report


# -----------------------------------------------------------
# GET /reports/payroll?start=YYYY-MM-DD&end=YYYY-MM-DD → Payroll report
# -----------------------------------------------------------
@router.get("/payroll", status_code=status.HTTP_200_OK)
def get_payroll_report(start: date, end: date, db: Session = Depends(get_db)):
    """
    Return payroll summary for all drivers within the given date range.
    Example: /reports/payroll?start=2025-01-01&end=2025-01-31
    """
    report = report_generator.payroll_summary(db, start, end)
    if not report:
        raise HTTPException(status_code=404, detail="No payroll records found in range")
    return {
        "date_range": {"start": start, "end": end},
        "total_records": len(report),
        "records": report,
    }


# -----------------------------------------------------------
# Export router explicitly
# -----------------------------------------------------------
__all__ = ["router"]
