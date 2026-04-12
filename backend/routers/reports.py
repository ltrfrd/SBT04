# - Reports router
# - Expose reports endpoints and keep deprecated attendance aliases
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
from . import student_bus_absence  # Re-export planned absence router through reports layer

# -----------------------------------------------------------
# Utilities
# -----------------------------------------------------------
from backend.utils import reports_generator  # Reports utility functions
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
from backend.models.operator import Operator
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_record_or_404
from backend.utils.operator_scope import get_operator_scoped_route_or_404

from pydantic import BaseModel  # Small request body schema

templates = Jinja2Templates(directory="backend/templates")   # Templates directory

router = APIRouter(prefix="/reports", tags=["Reports"])
attendance_router = APIRouter(prefix="/attendance", tags=["Reports"])
# -----------------------------------------------------------
# School confirmation request body
# -----------------------------------------------------------
class SchoolConfirmationRequest(BaseModel):
    confirmed_by: str | None = None  # Optional school staff name

# -----------------------------------------------------------
# - Driver reports summary
# - Return reports payload for one driver
# -----------------------------------------------------------
@attendance_router.get(
    "/driver/{driver_id}",
    status_code=status.HTTP_200_OK,
    summary="Driver reports summary",
    description="Return reports and work summary for a driver.",
    response_description="Driver reports summary",
    deprecated=True,
)
@router.get(
    "/driver/{driver_id}",                                      # Endpoint path with driver id
    status_code=status.HTTP_200_OK,                             # HTTP 200 on success
    summary="Driver reports summary",                           # Swagger title
    description="Return reports and work summary for a driver.",  # Swagger description
    response_description="Driver reports summary",              # Swagger response text
)
def get_driver_reports(
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return work summary for one driver."""                   # Internal docstring
    reports_data = reports_generator.driver_summary(db, driver_id, operator_id=operator.id)
    if "error" in reports_data:
        raise HTTPException(status_code=404, detail=reports_data["error"])
    return reports_data


# -----------------------------------------------------------
# - Route reports summary
# - Return reports payload for one route
# -----------------------------------------------------------
@attendance_router.get(
    "/route/{route_id}",
    status_code=status.HTTP_200_OK,
    summary="Route reports summary",
    description="Return reports and work summary for a route.",
    response_description="Route reports summary",
    deprecated=True,
)
@router.get(
    "/route/{route_id}",                                        # Endpoint path with route id
    status_code=status.HTTP_200_OK,                             # HTTP 200 on success
    summary="Route reports summary",                            # Swagger title
    description="Return reports and work summary for a route.",  # Swagger description
    response_description="Route reports summary",               # Swagger response text
)
def get_route_reports(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return work summary for one route."""                    # Internal docstring
    reports_data = reports_generator.route_summary(db, route_id, operator_id=operator.id)
    if "error" in reports_data:
        raise HTTPException(status_code=404, detail=reports_data["error"])
    return reports_data

# -----------------------------------------------------------
# - Run reports summary
# - Return reports status for each student in a run
# -----------------------------------------------------------
@attendance_router.get(
    "/run/{run_id}",
    status_code=status.HTTP_200_OK,
    summary="Run reports summary",
    description="Return reports status for each student in a run.",
    response_description="Run reports summary",
    deprecated=True,
)
@router.get(
    "/run/{run_id}",                                           # Endpoint path with run id
    status_code=status.HTTP_200_OK,                            # HTTP 200 on success
    summary="Run reports summary",                             # Swagger title
    description="Return reports status for each student in a run.",  # Swagger description
    response_description="Run reports summary",                # Swagger response text
)
def get_run_reports(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return student reports status for a specific run."""
    run = db.query(Run).filter(Run.id == run_id).first()  # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")  # Preserve missing-resource behavior
    get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
        required_access="read",
    )

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

    reports_data = reports_generator.run_reports_summary(
        db,
        run,
        assignments,
        events,
        absence_lookup,
    )

    return {
        "route_number": run.route.route_number if run.route else None,  # Operational route identifier
        "run_type": run.run_type,                                       # Flexible run label
        "students": reports_data["students"],
        "totals": reports_data["totals"],
        "stop_totals": reports_data["stop_totals"],
    }


# -----------------------------------------------------------
# - Driver dispatch summary
# - Return dispatch work summary for a date range
# -----------------------------------------------------------
@attendance_router.get(
    "/payroll",
    status_code=status.HTTP_200_OK,
    summary="Driver dispatch summary",
    description="Return driver dispatch summary for the selected date range.",
    response_description="Driver dispatch summary",
    deprecated=True,
)
@router.get(
    "/payroll",                                                # Deprecated endpoint path
    status_code=status.HTTP_200_OK,                            # HTTP 200 on success
    summary="Driver dispatch summary",                         # Swagger title
    description="Deprecated alias. Return driver dispatch summary for the selected date range.",  # Swagger description
    response_description="Driver dispatch summary",            # Swagger response text
    deprecated=True,
)
@router.get(
    "/dispatch-summary",                                       # Canonical endpoint path
    status_code=status.HTTP_200_OK,                            # HTTP 200 on success
    summary="Driver dispatch summary",                         # Swagger title
    description="Return driver dispatch summary for the selected date range.",  # Swagger description
    response_description="Driver dispatch summary",            # Swagger response text
)
def get_driver_dispatch_summary(
    start: date,
    end: date,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return dispatch summary for all drivers within the given date range."""
    reports_data = reports_generator.dispatch_summary(db, start, end, operator_id=operator.id)
    if not reports_data:
        raise HTTPException(status_code=404, detail="No dispatch records found in range")  # Preserve empty-range behavior
    return {
        "date_range": {"start": start, "end": end},  # Requested date range
        "total_records": len(reports_data),
        "records": reports_data,
    }  # Preserve existing response payload shape

# -----------------------------------------------------------
# - Date reports summary
# - Return reports aggregation for one date
# -----------------------------------------------------------
@attendance_router.get(
    "/date/{target_date}",
    summary="Date reports summary",
    description="Return reports aggregation for a single date.",
    response_description="Date reports summary",
    deprecated=True,
)
@router.get(
    "/date/{target_date}",                                    # Endpoint path with target date
    summary="Date reports summary",                           # Swagger title
    description="Return reports aggregation for a single date.",  # Swagger description
    response_description="Date reports summary",              # Swagger response text
)
def get_date_reports(
    target_date: date,
    db: Session = Depends(get_db),                            # Database session
    operator: Operator = Depends(get_operator_context),
):
    return reports_generator.generate_reports(
        db=db,                                                # Pass DB session
        reports_type="date",
        start=target_date,                                    # Start date = target date
        end=target_date,                                      # End date = target date
        operator_id=operator.id,
    )

# -----------------------------------------------------------
# - School reports summary
# - Return reports aggregation for one school
# -----------------------------------------------------------
@attendance_router.get(
    "/school/{school_id}",
    summary="School reports summary",
    description="Return reports aggregation for a single school.",
    response_description="School reports summary",
    deprecated=True,
)
@router.get(
    "/school/{school_id}",                                    # Endpoint path with school id
    summary="School reports summary",                         # Swagger title
    description="Return reports aggregation for a single school.",  # Swagger description
    response_description="School reports summary",            # Swagger response text
)
def get_school_reports(
    school_id: int,                                           # Requested school ID
    db: Session = Depends(get_db),                            # Database session
    operator: Operator = Depends(get_operator_context),
):
    return reports_generator.generate_reports(
        db=db,                                                # Pass DB session
        reports_type="school",
        ref_id=school_id,                                     # School reference ID
        operator_id=operator.id,
    )

# -----------------------------------------------------------
# - Confirm school reports
# - Create or refresh school confirmation for one school/run pair
# -----------------------------------------------------------
@attendance_router.post(
    "/school/{school_id}/confirm/{run_id}",
    status_code=status.HTTP_200_OK,
    summary="Confirm school reports",
    description="Create or refresh school confirmation for a specific school and run.",
    response_description="School reports confirmation saved",
    deprecated=True,
)
@router.post(
    "/school/{school_id}/confirm/{run_id}",                   # Endpoint path with school + run ids
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="Confirm school reports",                         # Swagger title
    description="Create or refresh school confirmation for a specific school and run.",  # Swagger description
    response_description="School reports confirmation saved",  # Swagger response text
)
def confirm_school_reports(
    school_id: int,  # Requested school ID
    run_id: int,  # Requested run ID
    payload: SchoolConfirmationRequest,  # Optional confirmer
    db: Session = Depends(get_db),  # Database session
    operator: Operator = Depends(get_operator_context),
):
    school = get_operator_scoped_record_or_404(
        db=db,
        model=School,
        record_id=school_id,
        operator_id=operator.id,
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
    get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
        required_access="read",
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
        "message": "School reports confirmed",
        "school_id": verification.school_id,
        "run_id": verification.run_id,
        "confirmed_at": verification.confirmed_at,
        "confirmed_by": verification.confirmed_by,
    }
# -----------------------------------------------------------
# - Absences by date
# - Return planned bus absences for one date
# -----------------------------------------------------------
@attendance_router.get(
    "/absences/date/{target_date}",
    summary="Absences by date",
    description="Return planned bus absences for a single date.",
    response_description="Absence list for date",
    deprecated=True,
)
@router.get(
    "/absences/date/{target_date}",                            # Endpoint path with target date
    summary="Absences by date",                                # Swagger title
    description="Return planned bus absences for a single date.",  # Swagger description
    response_description="Absence list for date",              # Swagger response text
)
def get_absences_by_date(
    target_date: date,                                                                # Requested date
    db: Session = Depends(get_db),                                                    # Database session
    operator: Operator = Depends(get_operator_context),
):

    absences = (
        db.query(StudentBusAbsence)                                                   # Query planned absences
        .join(Student, Student.id == StudentBusAbsence.student_id)
        .options(joinedload(StudentBusAbsence.student))                               # Load student relation
        .filter(Student.operator_id == operator.id)
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
@attendance_router.get(
    "/absences/school/{school_id}",
    summary="Absences by school",
    description="Return planned bus absences for a single school.",
    response_description="Absence list for school",
    deprecated=True,
)
@router.get(
    "/absences/school/{school_id}",                          # Endpoint path with school id
    summary="Absences by school",                            # Swagger title
    description="Return planned bus absences for a single school.",  # Swagger description
    response_description="Absence list for school",          # Swagger response text
)
def get_absences_by_school(
    school_id: int,                                                                # Requested school
    db: Session = Depends(get_db),                                                 # Database session
    operator: Operator = Depends(get_operator_context),
):
    get_operator_scoped_record_or_404(
        db=db,
        model=School,
        record_id=school_id,
        operator_id=operator.id,
        detail="School not found",
    )

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
@attendance_router.get(
    "/absences/run/{run_id}",
    summary="Absences by run",
    description="Return planned bus absences for a single run.",
    response_description="Absence list for run",
    deprecated=True,
)
@router.get(
    "/absences/run/{run_id}",                               # Endpoint path with run id
    summary="Absences by run",                              # Swagger title
    description="Return planned bus absences for a single run.",  # Swagger description
    response_description="Absence list for run",            # Swagger response text
)
def get_absences_by_run(
    run_id: int,                                                                  # Requested run
    db: Session = Depends(get_db),                                                # Database session
    operator: Operator = Depends(get_operator_context),
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
    get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
        required_access="read",
    )
    if run.start_time is None:                                                    # Reject runs that have not started yet
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run has not started yet",
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
# - School reports by date
# - Return present or absent status for school students
# -----------------------------------------------------------
@attendance_router.get(
    "/school/{school_id}/attendance/{target_date}",
    status_code=status.HTTP_200_OK,
    summary="School reports by date",
    description="Return present or absent status for school students on one date.",
    response_description="School reports by date",
    deprecated=True,
)
@attendance_router.get(
    "/school/{school_id}/reports/{target_date}",
    status_code=status.HTTP_200_OK,
    summary="School reports by date",
    description="Return present or absent status for school students on one date.",
    response_description="School reports by date",
    deprecated=True,
)
@router.get(
    "/school/{school_id}/reports/{target_date}",
    status_code=status.HTTP_200_OK,                                              # HTTP 200 on success
    summary="School reports by date",                                            # Swagger title
    description="Return present or absent status for school students on one date.",  # Swagger description
    response_description="School reports by date",                               # Swagger response text
)
def get_school_reports_by_date(
    school_id: int,                                                              # Requested school
    target_date: date,                                                           # Requested date
    db: Session = Depends(get_db),                                               # Database session
    operator: Operator = Depends(get_operator_context),
):
    school = get_operator_scoped_record_or_404(
        db=db,
        model=School,
        record_id=school_id,
        operator_id=operator.id,
        detail="School not found",
    )

    if not school:                                                               # Validate school exists
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School not found",
        )

    runs = (
        db.query(Run)                                                            # Query runs
        .filter(Run.route.has(Route.schools.any(School.id == school_id)))        # Only runs whose route includes this school       
        .filter(Run.start_time >= target_date)                                   # On or after start of requested day
        .filter(Run.start_time < (target_date + timedelta(days=1)))              # Before next day
        .order_by(Run.start_time.asc(), Run.id.asc())                            # Stable ordering
        .all()                                                                   # Materialize list
    )

    results = []                                                                 # Final student reports rows

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
        "students": results,
    }

# -----------------------------------------------------------
# - School mobile reports checklist
# - Render mobile-friendly school reports route list
# -----------------------------------------------------------
@attendance_router.get(
    "/school/{school_id}/mobile",
    status_code=status.HTTP_200_OK,
    summary="School mobile reports checklist",
    description="Render the mobile school reports checklist for one school.",
    response_description="Rendered school mobile reports page",
    deprecated=True,
)
@router.get(
    "/school/{school_id}/mobile",                             # Mobile school reports page
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="School mobile reports checklist",                # Swagger title
    description="Render the mobile school reports checklist for one school.",  # Swagger description
    response_description="Rendered school mobile reports page",  # Swagger response text
)
def get_school_mobile_reports(
    school_id: int,                                           # Requested school
    request: Request,                                         # FastAPI request object
    db: Session = Depends(get_db),                            # Database session
    operator: Operator = Depends(get_operator_context),
):
    report_data = reports_generator.school_routes_summary(
        db=db,                                                 # Pass DB session
        school_id=school_id,                                   # Requested school
        operator_id=operator.id,
    )                                                          # Navigation payload

    if "error" in report_data:                                 # Reject unknown school requests
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report_data["error"],
        )

    return templates.TemplateResponse(
        request,
        "school_reports_routes.html",
        {
            "report": report_data,
        },
    )

# -----------------------------------------------------------
# - School route reports run list
# - Render runs for one selected school route
# -----------------------------------------------------------
@attendance_router.get(
    "/school/{school_id}/mobile/route/{route_id}",
    status_code=status.HTTP_200_OK,
    summary="School mobile route runs",
    description="Render the mobile list of runs for one selected school route.",
    response_description="Rendered school mobile route runs page",
    deprecated=True,
)
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
    operator: Operator = Depends(get_operator_context),
):
    report_data = reports_generator.school_route_runs_summary(
        db=db,                                                # Pass DB session
        school_id=school_id,                                  # Requested school
        route_id=route_id,                                    # Requested route
        operator_id=operator.id,
    )                                                         # Route runs payload

    if "error" in report_data:                                # Reject unknown route requests
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report_data["error"],
        )

    return templates.TemplateResponse(
        request,
        "school_reports_runs.html",
        {
            "report": report_data,
        },
    )                                                   # Return rendered page


# -----------------------------------------------------------
# - School single run reports
# - Render one selected run only
# -----------------------------------------------------------
@attendance_router.get(
    "/school/{school_id}/mobile/run/{run_id}",
    status_code=status.HTTP_200_OK,
    summary="School mobile single run",
    description="Render the mobile reports view for one selected run.",
    response_description="Rendered school mobile single run page",
    deprecated=True,
)
@router.get(
    "/school/{school_id}/mobile/run/{run_id}",                # Mobile school run page
    status_code=status.HTTP_200_OK,                           # HTTP 200 on success
    summary="School mobile single run",                       # Swagger title
    description="Render the mobile reports view for one selected run.",  # Swagger description
    response_description="Rendered school mobile single run page",  # Swagger response text
)
def get_school_mobile_single_run_reports(
    school_id: int,                                           # Requested school
    run_id: int,                                              # Requested run
    request: Request,                                         # FastAPI request object
    db: Session = Depends(get_db),                            # Database session
    operator: Operator = Depends(get_operator_context),
):
    report_data = reports_generator.school_single_run_summary(
        db=db,                                                # Pass DB session
        school_id=school_id,                                  # Requested school
        run_id=run_id,                                        # Requested run
        operator_id=operator.id,
    )                                                         # Single run payload

    if "error" in report_data:                                # Reject unknown run requests
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report_data["error"],
        )

    return templates.TemplateResponse(
        request,
        "school_mobile_report.html",
        {
            "report": report_data,
        },
    )                                             # Return rendered page
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
@attendance_router.post(
    "/school/student-status",
    status_code=status.HTTP_200_OK,
    summary="Update school student status",
    description="Update school-layer reports status for one assigned student.",
    response_description="School student status updated",
    deprecated=True,
)
@router.post(
    "/school/student-status",                               # Endpoint for school-side status updates
    status_code=status.HTTP_200_OK,                         # HTTP 200 on success
    summary="Update school student status",                 # Swagger title
    description="Update school-layer reports status for one assigned student.",  # Swagger description
    response_description="School student status updated",   # Swagger response text
)
def update_school_status(                                  # Handler function
    payload: StudentStatusUpdate,                          # Typed JSON body
    db: Session = Depends(get_db),                         # Database session dependency
    operator: Operator = Depends(get_operator_context),
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
    if not assignment.student or assignment.student.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Assignment not found")

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
            detail="Reports already confirmed for this run",
        )

    assignment.school_status = payload.status              # Save school-layer status

    db.commit()                                            # Persist change

    return {                                               # Response payload
        "message": "Status updated",
        "student_id": payload.student_id,
        "run_id": payload.run_id,
        "school_status": payload.status
    }    

get_driver_work_summary = get_driver_dispatch_summary
get_driver_attendance = get_driver_reports
get_route_attendance = get_route_reports
get_run_attendance = get_run_reports
get_date_attendance = get_date_reports
get_school_attendance = get_school_reports
confirm_school_attendance = confirm_school_reports
get_school_attendance_by_date = get_school_reports_by_date
get_school_mobile_attendance = get_school_mobile_reports
get_school_mobile_single_run = get_school_mobile_single_run_reports

student_bus_absence_router = student_bus_absence.router

__all__ = ["router", "attendance_router", "student_bus_absence_router"]

