# -----------------------------------------------------------
# Attendance Router
# - Expose attendance-layer endpoints using the existing report behavior
# -----------------------------------------------------------
from datetime import date  # Date filter type

from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI components
from sqlalchemy.orm import Session, joinedload  # Database session type + eager loading

from database import get_db  # Shared DB dependency
from backend.routers import student_bus_absence  # Re-export planned absence router through attendance layer
from backend.utils import attendance_generator  # Attendance utility functions


router = APIRouter(
    prefix="/reports",  # Keep existing path stable during the rename phase
    tags=["Attendance"],  # Rename outward-facing API label
)


@router.get("/driver/{driver_id}", status_code=status.HTTP_200_OK)
def get_driver_attendance(driver_id: int, db: Session = Depends(get_db)):
    """Return work summary for one driver."""  # Behavior unchanged during rename
    attendance = attendance_generator.driver_summary(db, driver_id)  # Build driver attendance payload
    if "error" in attendance:
        raise HTTPException(status_code=404, detail=attendance["error"])  # Preserve missing-resource behavior
    return attendance


@router.get("/route/{route_id}", status_code=status.HTTP_200_OK)
def get_route_attendance(route_id: int, db: Session = Depends(get_db)):
    """Return detailed attendance summary for one route."""  # Outward wording updated only
    attendance = attendance_generator.route_summary(db, route_id)  # Build route attendance payload
    if "error" in attendance:
        raise HTTPException(status_code=404, detail=attendance["error"])  # Preserve missing-resource behavior
    return attendance


# -----------------------------------------------------------
# Run Attendance Report
# - Return attendance status for each student in a run
# -----------------------------------------------------------
@router.get("/run/{run_id}", status_code=status.HTTP_200_OK)
def get_run_attendance(run_id: int, db: Session = Depends(get_db)):
    """Return student attendance status for a specific run."""  # Attendance-layer view
    from backend.models.associations import StudentRunAssignment  # Runtime assignments
    from backend.models.run import Run  # Run model
    from backend.models.run_event import RunEvent  # Run event history
    from backend.utils.student_bus_absence import has_student_bus_absence  # Planned absence check

    run = db.query(Run).filter(Run.id == run_id).first()  # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")  # Preserve missing-resource behavior

    assignments = (
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),  # Preload student relation
            joinedload(StudentRunAssignment.stop),  # Preload stop relation
        )
        .filter(StudentRunAssignment.run_id == run_id)
        .all()
    )  # Load run assignments with related student/stop

    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .all()
    )  # Load run events

    absence_lookup = {}  # Cache planned absences by student

    for assignment in assignments:
        absence_lookup[assignment.student_id] = has_student_bus_absence(
            assignment.student_id,  # Student identifier
            run,  # Run object used by absence helper
            db,  # Database session
        )  # Determine whether student is planned absent

    attendance_data = attendance_generator.run_attendance_summary(
        db,
        run,
        assignments,
        events,
        absence_lookup,
    )  # Build attendance payload

    return {
        "route_number": run.route.route_number if run.route else None,  # Operational route identifier
        "run_type": run.run_type,                                       # AM / PM
        "students": attendance_data["students"],                        # Student attendance list
        "totals": attendance_data["totals"],                            # Run-level attendance totals
        "stop_totals": attendance_data["stop_totals"],                  # Stop-level attendance totals
    }


@router.get("/payroll", status_code=status.HTTP_200_OK)
def get_driver_work_summary(start: date, end: date, db: Session = Depends(get_db)):
    """Return payroll summary for all drivers within the given date range."""  # Behavior unchanged during rename
    attendance = attendance_generator.payroll_summary(db, start, end)  # Build payroll attendance payload
    if not attendance:
        raise HTTPException(status_code=404, detail="No payroll records found in range")  # Preserve empty-range behavior
    return {
        "date_range": {"start": start, "end": end},  # Requested date range
        "total_records": len(attendance),  # Number of summary rows
        "records": attendance,  # Summary payload
    }  # Preserve existing response payload shape

# -----------------------------------------------------------  # Attendance report by date
# Attendance report by date                                   # Dispatch daily attendance dashboard
# - Dispatch daily attendance dashboard                       # Read-only attendance aggregation
# -----------------------------------------------------------  # Section separator

@router.get("/date/{target_date}")                            # Daily attendance endpoint
def get_date_attendance(                                      # Return attendance for one date
    target_date: date,                                        # Requested attendance date
    db: Session = Depends(get_db),                            # Database session
):
    return attendance_generator.generate_attendance(          # Delegate to attendance generator
        db=db,                                                # Pass DB session
        attendance_type="date",                               # Request date attendance mode
        start=target_date,                                    # Start date = target date
        end=target_date,                                      # End date = target date
    )  # Daily attendance summary                             # Return one-day attendance data

# -----------------------------------------------------------  # Attendance report by school
# Attendance report by school                                 # School-level attendance dashboard
# - School-level attendance dashboard                         # Read-only attendance aggregation
# -----------------------------------------------------------  # Section separator

@router.get("/school/{school_id}")                            # School attendance endpoint
def get_school_attendance(                                    # Return attendance for one school
    school_id: int,                                           # Requested school ID
    db: Session = Depends(get_db),                            # Database session
):
    return attendance_generator.generate_attendance(          # Delegate to attendance generator
        db=db,                                                # Pass DB session
        attendance_type="school",                             # Request school attendance mode
        ref_id=school_id,                                     # School reference ID
    )  # School attendance summary                            # Return school attendance data

student_bus_absence_router = student_bus_absence.router  # Keep absence under attendance module ownership

__all__ = ["router", "student_bus_absence_router"]  # Export attendance router and absence compatibility router