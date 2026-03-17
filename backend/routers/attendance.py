# -----------------------------------------------------------
# Attendance Router
# - Expose attendance-layer endpoints using the existing report behavior
# -----------------------------------------------------------
# -----------------------------------------------------------
# Standard library
# -----------------------------------------------------------
from datetime import date  # Date filter type
from datetime import timedelta # Date arithmetic

# -----------------------------------------------------------
# FastAPI
# -----------------------------------------------------------
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI components
from fastapi import Request                              # FastAPI request object for templates
from fastapi.templating import Jinja2Templates           # Template rendering system
# -----------------------------------------------------------
# Database
# -----------------------------------------------------------
from sqlalchemy.orm import Session, joinedload  # DB session + eager loading
from database import get_db  # Shared DB dependency

# -----------------------------------------------------------
# Routers
# -----------------------------------------------------------
from backend.routers import student_bus_absence  # Re-export planned absence router through attendance layer

# -----------------------------------------------------------
# Utilities
# -----------------------------------------------------------
from backend.utils import attendance_generator  # Attendance utility functions
from backend.utils.student_bus_absence import has_student_bus_absence  # Planned absence check
# -----------------------------------------------------------
# Models
# -----------------------------------------------------------
from backend.models.run import Run                              # Run model
from backend.models.run_event import RunEvent                   # Run event history
from backend.models.student import Student                      # Student model
from backend.models.school import School                        # School model
from backend.models.student_bus_absence import StudentBusAbsence  # Planned absence model
from backend.models.associations import StudentRunAssignment       # Runtime student assignments
from backend.models.route import Route                                    # Route model

templates = Jinja2Templates(directory="backend/templates")   # Templates directory

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

# -----------------------------------------------------------
# Absence report by date
# - Returns planned bus absences for a given date
# -----------------------------------------------------------
@router.get("/reports/absences/date/{target_date}")                                   # Absence visibility endpoint
def get_absences_by_date(
    target_date: date,                                                                # Requested date
    db: Session = Depends(get_db),                                                    # Database session
):

    absences = (
        db.query(StudentBusAbsence)                                                   # Query planned absences
        .options(joinedload(StudentBusAbsence.student))                               # Load student relation
        .filter(StudentBusAbsence.date == target_date)                                # Only this date
        .order_by(StudentBusAbsence.created_at.asc(), StudentBusAbsence.id.asc())     # Stable ordering
        .all()                                                                        # Materialize list
    )

    results = []                                                                      # Response container

    for absence in absences:                                                          # Build response rows
        results.append(
            {
                "absence_id": absence.id,                                             # Absence record ID
                "student_id": absence.student_id,                                     # Student ID
                "student_name": absence.student.name if absence.student else None,    # Student name
                "date": absence.date,                                                 # Absence date
                "run_type": absence.run_type,                                         # AM / PM
                "source": absence.source,                                             # Parent / school / system
                "created_at": absence.created_at,                                     # Creation timestamp
            }
        )

    return {
        "date": target_date,                                                          # Requested date
        "total_absences": len(results),                                               # Total absences
        "absences": results,                                                          # Absence list
    }

# -----------------------------------------------------------
# Absence report by school
# - Returns planned absences for students of a given school
# -----------------------------------------------------------
@router.get("/reports/absences/school/{school_id}")                               # School absence visibility
def get_absences_by_school(
    school_id: int,                                                                # Requested school
    db: Session = Depends(get_db),                                                 # Database session
):

    absences = (
        db.query(StudentBusAbsence)                                                # Query planned absences
        .join(Student, Student.id == StudentBusAbsence.student_id)                 # Join student
        .filter(Student.school_id == school_id)                                    # Only this school
        .options(joinedload(StudentBusAbsence.student))                            # Load student relation
        .order_by(StudentBusAbsence.date.asc(), StudentBusAbsence.id.asc())        # Stable ordering
        .all()                                                                     # Materialize list
    )

    results = []                                                                   # Response container

    for absence in absences:                                                       # Build response rows
        results.append(
            {
                "student_name": absence.student.name if absence.student else None, # Student name
                "date": absence.date,                                              # Absence date
                "run_type": absence.run_type,                                      # AM / PM
            }
        )

    return {
        "school_id": school_id,                                                    # Requested school
        "total_absences": len(results),                                            # Total rows
        "absences": results,                                                       # Absence list
    }

# -----------------------------------------------------------
# - Absence report by run
# - Returns planned absences for students assigned to a run
# -----------------------------------------------------------
@router.get("/reports/absences/run/{run_id}")                                    # Driver run absence visibility
def get_absences_by_run(
    run_id: int,                                                                  # Requested run
    db: Session = Depends(get_db),                                                # Database session
):

    run = (
        db.query(Run)                                                             # Load run
        .filter(Run.id == run_id)                                                 # Only this run
        .first()                                                                  # Materialize
    )

    if not run:                                                                   # Validate run
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    absences = (
        db.query(StudentBusAbsence)                                               # Query planned absences
        .join(Student, Student.id == StudentBusAbsence.student_id)                # Join student
        .join(StudentRunAssignment, StudentRunAssignment.student_id == Student.id)      # Join run assignment
        .options(
            joinedload(StudentBusAbsence.student)                                        # Load student relation
        )
        .filter(StudentRunAssignment.run_id == run_id)                            # Only this run
        .filter(StudentBusAbsence.date == run.start_time.date())                  # Only run date        .order_by(StudentBusAbsence.id.asc()) 
        .all()                                                                    # Materialize list
    )

    results = []                                                                  # Response container

    for absence in absences:                                                      # Build response rows
        results.append(
            {
                "student_name": absence.student.name if absence.student else None,            # Student name
                "stop_name": absence.student.stop.name if absence.student and absence.student.stop else None,  # Stop name
            }
        )

    return {
        "route_number": run.route.route_number if run.route else None,            # Route number
        "run_type": run.run_type,                                                 # AM / PM
        "date": run.start_time.date(),                                            # Run service date
        "total_absences": len(results),                                           # Total absences
        "absences": results,                                                      # Absence list
    }

# -----------------------------------------------------------
# School attendance by date
# - Returns present / absent status for school students
# -----------------------------------------------------------
@router.get("/school/{school_id}/attendance/{target_date}")                      # School attendance by date
def get_school_attendance_by_date(
    school_id: int,                                                              # Requested school
    target_date: date,                                                           # Requested date
    db: Session = Depends(get_db),                                               # Database session
):
    school = (
        db.query(School)                                                         # Load school
        .filter(School.id == school_id)                                          # Only this school
        .first()                                                                 # Materialize
    )

    if not school:                                                               # Validate school exists
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School not found",
        )

    runs = (
        db.query(Run)                                                            # Query runs
        .filter(Run.route.has(Route.schools.any(School.id == school_id)))        # Only runs whose route includes this school       
        .filter(Run.start_time < (target_date + timedelta(days=1)))              # Before next day
        .order_by(Run.start_time.asc(), Run.id.asc())                            # Stable ordering
        .all()                                                                   # Materialize list
    )

    results = []                                                                 # Final student attendance rows

    for run in runs:                                                             # Process each school run
        assignments = (
            db.query(StudentRunAssignment)                                       # Query runtime assignments
            .options(joinedload(StudentRunAssignment.student))                   # Load student relation
            .filter(StudentRunAssignment.run_id == run.id)                       # Only this run
            .order_by(StudentRunAssignment.id.asc())                             # Stable ordering
            .all()                                                               # Materialize list
        )

        for assignment in assignments:                                           # Build school-facing rows
            results.append(
                {
                    "student_name": assignment.student.name if assignment.student else None,  # Student name
                    "status": "present" if assignment.picked_up else "absent",                # School-facing status
                    "run_type": run.run_type,                                                  # AM / PM
                }
            )
    return {
        "school_name": school.name,                                             # School name
        "date": target_date,                                                    # Requested date
        "total_students": len(results),                                         # Total students evaluated
        "students": results,                                                    # Student attendance list
    }

# -----------------------------------------------------------
# School mobile attendance checklist
# - Mobile friendly page for school drop-off verification
# - Allows optional second confirmation of student arrival
# -----------------------------------------------------------
@router.get("/school/{school_id}/mobile")                     # Mobile school attendance page
def get_school_mobile_attendance(
    school_id: int,                                           # Requested school
    request: Request,                                         # FastAPI request object
    db: Session = Depends(get_db),                            # Database session
):

    report_data = attendance_generator.generate_attendance(   # Generate school attendance data
        db=db,                                                 # Pass DB session
        attendance_type="school",                              # School attendance mode
        ref_id=school_id,                                      # School reference
    )                                                          # Attendance payload

    return templates.TemplateResponse(                        # Render mobile HTML template
        "school_mobile_report.html",                           # Mobile template file
        {
            "request": request,                                # Required by Jinja templates
            "report": report_data,                             # School attendance data
        },
    )                                                          # Return rendered page
    

student_bus_absence_router = student_bus_absence.router  # Keep absence under attendance module ownership

__all__ = ["router", "student_bus_absence_router"]  # Export attendance router and absence compatibility router
