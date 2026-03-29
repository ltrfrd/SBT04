# - Attendance router
# - Expose attendance endpoints while keeping /reports compatibility
# -----------------------------------------------------------
from datetime import date, datetime, timezone   # Date filter type # UTC timestamp for confirmation save
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
from backend.models.school_attendance_verification import SchoolAttendanceVerification  # Confirmation model

from pydantic import BaseModel  # Small request body schema

templates = Jinja2Templates(directory="backend/templates")   # Templates directory

router = APIRouter(
    prefix="/reports",  # Keep existing path stable during the rename phase
    tags=["Attendance"],  # Rename outward-facing API label
)
# -----------------------------------------------------------
# School confirmation request body
# -----------------------------------------------------------
class SchoolConfirmationRequest(BaseModel):
    confirmed_by: str | None = None  # Optional school staff name

# -----------------------------------------------------------
# - Driver attendance summary
# - Return attendance payload for one driver
# -----------------------------------------------------------
@router.get(
    "/driver/{driver_id}",                                      # Endpoint path with driver id
    status_code=status.HTTP_200_OK,                             # HTTP 200 on success
    summary="Driver attendance summary",                        # Swagger title
    description="Return attendance and work summary for a driver.",  # Swagger description
    response_description="Driver attendance summary",           # Swagger response text
)
def get_driver_attendance(driver_id: int, db: Session = Depends(get_db)):
    """Return work summary for one driver."""                   # Internal docstring
    attendance = attendance_generator.driver_summary(db, driver_id)  # Build driver attendance payload
    if "error" in attendance:                                       # Preserve missing-resource behavior
        raise HTTPException(status_code=404, detail=attendance["error"])
    return attendance                                               # Return attendance payload


# -----------------------------------------------------------
# - Route attendance summary
# - Return attendance payload for one route
# -----------------------------------------------------------
@router.get(
    "/route/{route_id}",                                        # Endpoint path with route id
    status_code=status.HTTP_200_OK,                             # HTTP 200 on success
    summary="Route attendance summary",                         # Swagger title
    description="Return attendance and work summary for a route.",  # Swagger description
    response_description="Route attendance summary",            # Swagger response text
)
def get_route_attendance(route_id: int, db: Session = Depends(get_db)):
    """Return work summary for one route."""                    # Internal docstring
    attendance = attendance_generator.route_summary(db, route_id)  # Build route attendance payload
    if "error" in attendance:                                      # Preserve missing-resource behavior
        raise HTTPException(status_code=404, detail=attendance["error"])
    return attendance                                              # Return attendance payload

# -----------------------------------------------------------
# - Run attendance summary
# - Return attendance status for each student in a run
# -----------------------------------------------------------
@router.get(
    "/run/{run_id}",                                           # Endpoint path with run id
    status_code=status.HTTP_200_OK,                            # HTTP 200 on success
    summary="Run attendance summary",                          # Swagger title
    description="Return attendance status for each student in a run.",  # Swagger description
    response_description="Run attendance summary",             # Swagger response text
)
def get_run_attendance(run_id: int, db: Session = Depends(get_db)):
    """Return student attendance status for a specific run."""  # Internal docstring
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
        "run_type": run.run_type,                                       # Flexible run label
        "students": attendance_data["students"],                        # Student attendance list
        "totals": attendance_data["totals"],                            # Run-level attendance totals
        "stop_totals": attendance_data["stop_totals"],                  # Stop-level attendance totals
    }


# -----------------------------------------------------------
# - Driver work summary
# - Return payroll-style summary for a date range
# -----------------------------------------------------------
@router.get(
    "/payroll",                                                # Endpoint path
    status_code=status.HTTP_200_OK,                            # HTTP 200 on success
    summary="Driver work summary",                             # Swagger title
    description="Return driver work summary for the selected date range.",  # Swagger description
    response_description="Driver work summary",                # Swagger response text
)
def get_driver_work_summary(start: date, end: date, db: Session = Depends(get_db)):
    """Return payroll summary for all drivers within the given date range."""  # Internal docstring
    attendance = attendance_generator.payroll_summary(db, start, end)  # Build payroll attendance payload
    if not attendance:
        raise HTTPException(status_code=404, detail="No payroll records found in range")  # Preserve empty-range behavior
    return {
        "date_range": {"start": start, "end": end},  # Requested date range
        "total_records": len(attendance),  # Number of summary rows
        "records": attendance,  # Summary payload
    }  # Preserve existing response payload shape

# -----------------------------------------------------------
# - Date attendance summary
# - Return attendance aggregation for one date
# -----------------------------------------------------------

@router.get(
    "/date/{target_date}",                                    # Endpoint path with target date
    summary="Date attendance summary",                        # Swagger title
    description="Return attendance aggregation for a single date.",  # Swagger description
    response_description="Date attendance summary",           # Swagger response text
)
def get_date_attendance(
    target_date: date,                                        # Requested attendance date
    db: Session = Depends(get_db),                            # Database session
):
    return attendance_generator.generate_attendance(          # Delegate to attendance generator
        db=db,                                                # Pass DB session
        attendance_type="date",                               # Request date attendance mode
        start=target_date,                                    # Start date = target date
        end=target_date,                                      # End date = target date
    )  # Daily attendance summary                             # Return one-day attendance data

# -----------------------------------------------------------
# - School attendance summary
# - Return attendance aggregation for one school
# -----------------------------------------------------------
@router.get(
    "/school/{school_id}",                                    # Endpoint path with school id
    summary="School attendance summary",                      # Swagger title
    description="Return attendance aggregation for a single school.",  # Swagger description
    response_description="School attendance summary",         # Swagger response text
)
def get_school_attendance(
    school_id: int,                                           # Requested school ID
    db: Session = Depends(get_db),                            # Database session
):
    return attendance_generator.generate_attendance(          # Delegate to attendance generator
        db=db,                                                # Pass DB session
        attendance_type="school",                             # Request school attendance mode
        ref_id=school_id,                                     # School reference ID
    )  # School attendance summary                            # Return school attendance data

# -----------------------------------------------------------
# - Confirm school attendance
# - Create or refresh school confirmation for one school/run pair
# -----------------------------------------------------------
@router.post(
    "/school/{school_id}/confirm/{run_id}",                   # Endpoint path with school + run ids
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="Confirm school attendance",                      # Swagger title
    description="Create or refresh school confirmation for a specific school and run.",  # Swagger description
    response_description="School attendance confirmation saved",  # Swagger response text
)
def confirm_school_attendance(
    school_id: int,  # Requested school ID
    run_id: int,  # Requested run ID
    payload: SchoolConfirmationRequest,  # Optional confirmer
    db: Session = Depends(get_db),  # Database session
):
    school = (
        db.query(School)
        .filter(School.id == school_id)
        .first()
    )
    if not school:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School not found",
        )

    run = (
        db.query(Run)
        .options(joinedload(Run.route).joinedload(Route.schools))
        .filter(Run.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    route_school_ids = {s.id for s in run.route.schools} if run.route else set()
    if school_id not in route_school_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="School is not assigned to this run route",
        )

    verification = (
        db.query(SchoolAttendanceVerification)
        .filter(
            SchoolAttendanceVerification.school_id == school_id,
            SchoolAttendanceVerification.run_id == run_id,
        )
        .first()
    )

    now = datetime.now(timezone.utc)  # Save UTC confirmation time

    if verification:
        verification.confirmed_at = now  # Refresh confirmation time
        verification.confirmed_by = payload.confirmed_by  # Update confirmer
    else:
        verification = SchoolAttendanceVerification(
            school_id=school_id,  # Save school reference
            run_id=run_id,  # Save run reference
            confirmed_at=now,  # Save timestamp
            confirmed_by=payload.confirmed_by,  # Save optional confirmer
        )
        db.add(verification)

    db.commit()
    db.refresh(verification)

    return {
        "message": "School attendance confirmed",
        "school_id": verification.school_id,
        "run_id": verification.run_id,
        "confirmed_at": verification.confirmed_at,
        "confirmed_by": verification.confirmed_by,
    }
# -----------------------------------------------------------
# - Absences by date
# - Return planned bus absences for one date
# -----------------------------------------------------------
@router.get(
    "/absences/date/{target_date}",                            # Endpoint path with target date
    summary="Absences by date",                                # Swagger title
    description="Return planned bus absences for a single date.",  # Swagger description
    response_description="Absence list for date",              # Swagger response text
)
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
                "run_type": absence.run_type,                                         # Flexible run label
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
# - Absences by school
# - Return planned absences for one school
# -----------------------------------------------------------
@router.get(
    "/absences/school/{school_id}",                          # Endpoint path with school id
    summary="Absences by school",                            # Swagger title
    description="Return planned bus absences for a single school.",  # Swagger description
    response_description="Absence list for school",          # Swagger response text
)
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
                "run_type": absence.run_type,                                      # Flexible run label
            }
        )

    return {
        "school_id": school_id,                                                    # Requested school
        "total_absences": len(results),                                            # Total rows
        "absences": results,                                                       # Absence list
    }

# -----------------------------------------------------------
# - Absences by run
# - Return planned absences for one run
# -----------------------------------------------------------
@router.get(
    "/absences/run/{run_id}",                               # Endpoint path with run id
    summary="Absences by run",                              # Swagger title
    description="Return planned bus absences for a single run.",  # Swagger description
    response_description="Absence list for run",            # Swagger response text
)
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
        .filter(StudentBusAbsence.date == run.start_time.date())                  # Only run date
        .order_by(StudentBusAbsence.id.asc())                                     # Stable ordering
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
        "run_type": run.run_type,                                                 # Flexible run label
        "date": run.start_time.date(),                                            # Run service date
        "total_absences": len(results),                                           # Total absences
        "absences": results,                                                      # Absence list
    }

# -----------------------------------------------------------
# - School attendance by date
# - Return present or absent status for school students
# -----------------------------------------------------------
@router.get(
    "/school/{school_id}/attendance/{target_date}",                              # Endpoint path with school + date
    status_code=status.HTTP_200_OK,                                              # HTTP 200 on success
    summary="School attendance by date",                                         # Swagger title
    description="Return present or absent status for school students on one date.",  # Swagger description
    response_description="School attendance by date",                            # Swagger response text
)
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
                    "run_type": run.run_type,                                                  # Flexible run label
                }
            )
    return {
        "school_name": school.name,                                             # School name
        "date": target_date,                                                    # Requested date
        "total_students": len(results),                                         # Total students evaluated
        "students": results,                                                    # Student attendance list
    }

# -----------------------------------------------------------
# - School mobile attendance checklist
# - Render mobile-friendly school attendance route list
# -----------------------------------------------------------
@router.get(
    "/school/{school_id}/mobile",                             # Mobile school attendance page
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="School mobile attendance checklist",             # Swagger title
    description="Render the mobile school attendance checklist for one school.",  # Swagger description
    response_description="Rendered school mobile attendance page",  # Swagger response text
)
def get_school_mobile_attendance(
    school_id: int,                                           # Requested school
    request: Request,                                         # FastAPI request object
    db: Session = Depends(get_db),                            # Database session
):
    report_data = attendance_generator.school_routes_summary(  # Generate school route list
        db=db,                                                 # Pass DB session
        school_id=school_id,                                   # Requested school
    )                                                          # Navigation payload

    if "error" in report_data:                                 # Reject unknown school requests
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report_data["error"],
        )

    return templates.TemplateResponse(                        # Render mobile HTML template
        "school_attendance_routes.html",                       # Route landing template file
        {
            "request": request,                                # Required by Jinja templates
            "report": report_data,                             # School attendance data
        },
    )                                                          # Return rendered page


# -----------------------------------------------------------
# - School route attendance run list
# - Render runs for one selected school route
# -----------------------------------------------------------
@router.get(
    "/school/{school_id}/mobile/route/{route_id}",            # Mobile school route page
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="School mobile route runs",                       # Swagger title
    description="Render the mobile list of runs for one selected school route.",  # Swagger description
    response_description="Rendered school mobile route runs page",  # Swagger response text
)
def get_school_mobile_route_runs(
    school_id: int,                                           # Requested school
    route_id: int,                                            # Requested route
    request: Request,                                         # FastAPI request object
    db: Session = Depends(get_db),                            # Database session
):
    report_data = attendance_generator.school_route_runs_summary(
        db=db,                                                # Pass DB session
        school_id=school_id,                                  # Requested school
        route_id=route_id,                                    # Requested route
    )                                                         # Route runs payload

    if "error" in report_data:                                # Reject unknown route requests
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report_data["error"],
        )

    return templates.TemplateResponse(                        # Render route run list template
        "school_attendance_runs.html",                        # Route run list template file
        {
            "request": request,                               # Required by Jinja templates
            "report": report_data,                            # Route runs payload
        },
    )                                                         # Return rendered page


# -----------------------------------------------------------
# - School single run attendance report
# - Render one selected run only
# -----------------------------------------------------------
@router.get(
    "/school/{school_id}/mobile/run/{run_id}",                # Mobile school run page
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="School mobile single run",                       # Swagger title
    description="Render the mobile attendance report for one selected run.",  # Swagger description
    response_description="Rendered school mobile single run page",  # Swagger response text
)
def get_school_mobile_single_run(
    school_id: int,                                           # Requested school
    run_id: int,                                              # Requested run
    request: Request,                                         # FastAPI request object
    db: Session = Depends(get_db),                            # Database session
):
    report_data = attendance_generator.school_single_run_summary(
        db=db,                                                # Pass DB session
        school_id=school_id,                                  # Requested school
        run_id=run_id,                                        # Requested run
    )                                                         # Single run payload

    if "error" in report_data:                                # Reject unknown run requests
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report_data["error"],
        )

    return templates.TemplateResponse(                        # Render single-run template
        "school_mobile_report.html",                          # Single run report template
        {
            "request": request,                               # Required by Jinja templates
            "report": report_data,                            # Single run payload
        },
    )                                                         # Return rendered page
# -------------------------------------------------------------------------
# Request Schema - School Student Status Update
# -------------------------------------------------------------------------
class StudentStatusUpdate(BaseModel):                      # Pydantic model for request body
    student_id: int                                        # Student ID
    run_id: int                                            # Run ID
    status: str                                            # "present" or "absent"


# -------------------------------------------------------------------------
# School updates student status (layered, non-driver)
# -------------------------------------------------------------------------
@router.post(
    "/school/student-status",                               # Endpoint for school-side status updates
    status_code=status.HTTP_200_OK,                         # HTTP 200 on success
    summary="Update school student status",                 # Swagger title
    description="Update school-layer attendance status for one assigned student.",  # Swagger description
    response_description="School student status updated",   # Swagger response text
)
def update_school_status(                                  # Handler function
    payload: StudentStatusUpdate,                          # Typed JSON body
    db: Session = Depends(get_db)                          # Database session dependency
):
    if payload.status not in ["present", "absent"]:        # Validate allowed values
        raise HTTPException(                               # Reject bad request
            status_code=400,
            detail="Invalid payload"
        )

    assignment = (
        db.query(StudentRunAssignment)                     # Query assignment record
        .options(joinedload(StudentRunAssignment.student)) # Load student for school verification
        .filter(
            StudentRunAssignment.student_id == payload.student_id,   # Match student
            StudentRunAssignment.run_id == payload.run_id            # Match run
        )
        .first()
    )                                                     # Get first match

    if not assignment:                                     # If no record found
        raise HTTPException(
            status_code=404,
            detail="Assignment not found"
        )

    school_id = assignment.student.school_id if assignment.student else None   # Resolve owning school
    verification = None                                                        # Default no confirmation

    if school_id is not None:                                                  # Check school/run confirmation
        verification = (
            db.query(SchoolAttendanceVerification)
            .filter(
                SchoolAttendanceVerification.school_id == school_id,            # Match school
                SchoolAttendanceVerification.run_id == payload.run_id,          # Match run
            )
            .first()
        )

    if verification:                                                           # Lock updates after confirmation
        raise HTTPException(
            status_code=400,
            detail="Attendance already confirmed for this run",
        )

    assignment.school_status = payload.status              # Save school-layer status

    db.commit()                                            # Persist change

    return {                                               # Response payload
        "message": "Status updated",
        "student_id": payload.student_id,
        "run_id": payload.run_id,
        "school_status": payload.status
    }    

student_bus_absence_router = student_bus_absence.router  # Keep absence under attendance module ownership

__all__ = ["router", "student_bus_absence_router"]  # Export attendance router and absence compatibility router
