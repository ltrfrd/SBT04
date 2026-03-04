# ===========================================================
# backend/utils/report_generator.py — BST Report Generator
# -----------------------------------------------------------
# Centralized utilities for generating summaries:
# - Driver work summary (total runs, total charter hours)
# - Route summary (schools, students, stops)
# - Payroll overview (approved/unapproved)
# ===========================================================

from sqlalchemy.orm import Session  # Provides DB session interface
from datetime import date  # Used for payroll date filtering
from backend.models import (
    driver as driver_model,
    route as route_model,
    run as run_model,
    payroll as payroll_model,
)


# -----------------------------------------------------------
# DRIVER REPORT
# -----------------------------------------------------------
def driver_summary(db: Session, driver_id: int) -> dict:
    """Generate a work summary for a single driver."""
    drv = db.get(driver_model.Driver, driver_id)  # Fetch driver
    if not drv:
        return {"error": "Driver not found"}

    # Count all completed runs for this driver
    total_runs = (
        db.query(run_model.Run).filter(run_model.Run.driver_id == driver_id).count()
    )

    # Collect all charter hour entries for this driver
    total_charter_hours = (
        db.query(payroll_model.Payroll)
        .filter(payroll_model.Payroll.driver_id == driver_id)
        .with_entities(payroll_model.Payroll.charter_hours)
        .all()
    )

    # Sum valid hour values (ignore None)
    total_hours = sum(float(h[0]) for h in total_charter_hours if h[0])

    # Count approved vs pending payroll records
    approved = (
        db.query(payroll_model.Payroll)
        .filter(
            payroll_model.Payroll.driver_id == driver_id,
            payroll_model.Payroll.approved.is_(True),
        )
        .count()
    )

    pending = (
        db.query(payroll_model.Payroll)
        .filter(
            payroll_model.Payroll.driver_id == driver_id,
            payroll_model.Payroll.approved.is_(False),
        )
        .count()
    )

    # Return structured summary
    return {
        "driver_id": driver_id,
        "driver_name": drv.name,
        "total_runs": total_runs,
        "charter_hours": round(total_hours, 2),
        "approved_days": approved,
        "pending_days": pending,
    }


# -----------------------------------------------------------
# ROUTE REPORT
# -----------------------------------------------------------
def route_summary(db: Session, route_id: int) -> dict:
    """Generate a detailed summary for one route."""
    r = db.get(route_model.Route, route_id)  # Fetch route record
    if not r:
        return {"error": "Route not found"}

    # Extract all schools linked to this route
    schools_list = [{"id": s.id, "name": s.name} for s in r.schools]

    # Extract stops with ID, order, and type (pickup/dropoff)
    stops_list = [
        {"id": st.id, "sequence": st.sequence, "type": st.type.value} for st in r.stops
    ]

    # Extract all students assigned to this route
    students_list = [{"id": s.id, "name": s.name, "grade": s.grade} for s in r.students]

    # Count total runs recorded for this route
    total_runs = (
        db.query(run_model.Run).filter(run_model.Run.route_id == route_id).count()
    )

    # Return combined summary
    return {
        "route_id": route_id,
        "unit_number": r.unit_number,
        "num_runs": r.num_runs,
        "driver_id": r.driver_id,
        "schools": schools_list,
        "stops": stops_list,
        "students": students_list,
        "total_runs": total_runs,
    }


# -----------------------------------------------------------
# PAYROLL SUMMARY (Department view)
# -----------------------------------------------------------
def payroll_summary(db: Session, start: date, end: date) -> list:
    """Return payroll report between two dates for all drivers."""
    # Query payroll records between two specific dates
    records = (
        db.query(payroll_model.Payroll)
        .filter(
            payroll_model.Payroll.work_date >= start,
            payroll_model.Payroll.work_date <= end,
        )
        .all()
    )

    summary = []
    # Format each record as a dictionary
    for r in records:
        summary.append(
            {
                "driver_id": r.driver_id,
                "work_date": r.work_date,
                "charter_hours": float(r.charter_hours or 0),
                "approved": r.approved,
            }
        )
    return summary


# -----------------------------------------------------------
# GLOBAL DISPATCHER (Optional unified interface)
# -----------------------------------------------------------
def generate_report(
    db: Session,
    report_type: str,
    ref_id: int = None,
    start: date = None,
    end: date = None,
):
    """Generic entry point for any report type."""
    # Route calls to their respective functions
    if report_type == "driver" and ref_id:
        return driver_summary(db, ref_id)
    elif report_type == "route" and ref_id:
        return route_summary(db, ref_id)
    elif report_type == "payroll" and start and end:
        return payroll_summary(db, start, end)
    else:
        return {"error": "Invalid report type or parameters"}
