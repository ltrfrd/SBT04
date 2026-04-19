# - Reports router
# - Expose reports endpoints
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
from backend.models.yard import Yard
from backend.models import SchoolAttendanceVerification  # Confirmation model
from backend.models.operator import Operator
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_record_or_404
from backend.utils.planning_scope import (
    execution_route_filter,
    execution_student_filter,
    get_operator_yard_ids,
    get_route_for_execution_or_404,
    get_school_for_execution_or_404,
    operator_has_yard_route_assignments,
    yards_accessible_route_filter,
    yards_accessible_student_filter,
)

from pydantic import BaseModel  # Small request body schema

templates = Jinja2Templates(directory="backend/templates")   # Templates directory

router = APIRouter(prefix="/reports", tags=["Reports"])
# -----------------------------------------------------------
# School confirmation request body
# -----------------------------------------------------------
class SchoolConfirmationRequest(BaseModel):
    confirmed_by: str | None = None  # Optional school staff name


def _get_execution_yard_ids(
    *,
    db: Session,
    operator_id: int,
) -> list[int]:
    return get_operator_yard_ids(db=db, operator_id=operator_id)


def _get_active_execution_yard_ids(
    *,
    db: Session,
    operator_id: int,
) -> list[int] | None:
    if not operator_has_yard_route_assignments(db=db, operator_id=operator_id):
        return None
    return _get_execution_yard_ids(db=db, operator_id=operator_id)


def _get_execution_student_filter(
    *,
    db: Session,
    operator_id: int,
):
    if operator_has_yard_route_assignments(db=db, operator_id=operator_id):
        return yards_accessible_student_filter(_get_execution_yard_ids(db=db, operator_id=operator_id))
    return execution_student_filter(db=db, operator_id=operator_id)


def _get_execution_route_filter(
    *,
    db: Session,
    operator_id: int,
):
    if operator_has_yard_route_assignments(db=db, operator_id=operator_id):
        return yards_accessible_route_filter(_get_execution_yard_ids(db=db, operator_id=operator_id))
    return execution_route_filter(db=db, operator_id=operator_id)


def _build_absence_row(*, absence, stop_name: str | None = None) -> dict:
    return {
        "student_id": absence.student_id,
        "student_name": absence.student.name if absence.student else None,
        "date": absence.date,
        "run_type": absence.run_type,
        "status": "planned_absent",
        "source": absence.source,
        "stop_name": stop_name,
    }


def _build_absence_response(*, context_type: str, context_value, absences: list[dict]) -> dict:
    return {
        "context": {
            "type": context_type,
            "value": context_value,
        },
        "total_absences": len(absences),
        "absences": absences,
    }


def _serialize_school_report_summary(summary: dict, target_date: date | None = None) -> dict:
    return {
        "school_id": summary["school_id"],
        "school_name": summary["school_name"],
        "date": target_date,
        "total_routes": summary.get("total_routes", 0),
        "routes": summary.get("routes", []),
    }

# -----------------------------------------------------------
# - Driver reports summary
# - Return reports payload for one driver
# -----------------------------------------------------------
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
    """Return work summary for one route."""
    get_route_for_execution_or_404(db=db, route_id=route_id, operator_id=operator.id)
    reports_data = reports_generator.route_summary_execution(db, route_id)
    if "error" in reports_data:
        raise HTTPException(status_code=404, detail=reports_data["error"])
    return reports_data


# -----------------------------------------------------------
# - School-scope run reports
# - Return reports status for each student in a run
# -----------------------------------------------------------
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
    get_route_for_execution_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
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
# - Yard time cards
# - Return grouped driver time cards for a date range
# -----------------------------------------------------------
@router.get(
    "/time-cards/all",                                         # Yard-scope endpoint path
    status_code=status.HTTP_200_OK,                            # HTTP 200 on success
    summary="Yard time cards",                                 # Swagger title
    description="Return yard-scoped driver time cards for the selected date range.",  # Swagger description
    response_description="Grouped driver time cards",          # Swagger response text
)
def get_yard_time_cards(
    yard_id: int,
    start: date,
    end: date,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Return grouped driver time cards for one yard within the given date range."""
    yard = get_operator_scoped_record_or_404(
        db=db,
        model=Yard,
        record_id=yard_id,
        operator_id=operator.id,
        detail="Yard not found",
    )
    reports_data = reports_generator.dispatch_summary(
        db,
        yard_id=yard.id,
        start=start,
        end=end,
        operator_id=operator.id,
    )
    if not reports_data:
        raise HTTPException(status_code=404, detail="No dispatch records found in range")  # Preserve empty-range behavior
    return {
        "yard_id": yard.id,
        "date_range": {"start": start, "end": end},  # Requested date range
        "total_drivers": len(reports_data),
        "drivers": reports_data,
    }  # Yard-scoped grouped time card payload


# -----------------------------------------------------------
# - School-scope reports
# - Return reports aggregation for one date
# -----------------------------------------------------------
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
    yard_ids = _get_active_execution_yard_ids(db=db, operator_id=operator.id)
    get_school_for_execution_or_404(
        db=db,
        operator_id=operator.id,
        school_id=school_id,
        detail="School not found",
    )
    reports_data = reports_generator.generate_reports(
        db=db,                                                # Pass DB session
        reports_type="school",
        ref_id=school_id,                                     # School reference ID
        yard_ids=yard_ids,
    )
    return _serialize_school_report_summary(reports_data)

# -----------------------------------------------------------
# - Confirm school reports
# - Create or refresh school confirmation for one school/run pair
# -----------------------------------------------------------
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
    school = get_school_for_execution_or_404(
        db=db,
        operator_id=operator.id,
        school_id=school_id,
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
    get_route_for_execution_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
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
    student_filter = _get_execution_student_filter(db=db, operator_id=operator.id)

    absences = (
        db.query(StudentBusAbsence)                                                   # Query planned absences
        .join(Student, Student.id == StudentBusAbsence.student_id)
        .options(joinedload(StudentBusAbsence.student))                               # Load student relation
        .filter(student_filter)
        .filter(StudentBusAbsence.date == target_date)                                # Only this date
        .order_by(StudentBusAbsence.created_at.asc(), StudentBusAbsence.id.asc())     # Stable ordering
        .all()                                                                        # Materialize list
    )

    results = []                                                                      # Response container

    for absence in absences:                                                          # Build response rows
        results.append(
            _build_absence_row(absence=absence)
        )

    return _build_absence_response(
        context_type="date",
        context_value=target_date,
        absences=results,
    )

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
    operator: Operator = Depends(get_operator_context),
):
    student_filter = _get_execution_student_filter(db=db, operator_id=operator.id)
    get_school_for_execution_or_404(
        db=db,
        operator_id=operator.id,
        school_id=school_id,
        detail="School not found",
    )

    absences = (
        db.query(StudentBusAbsence)                                                # Query planned absences
        .join(Student, Student.id == StudentBusAbsence.student_id)                 # Join student
        .filter(Student.school_id == school_id)                                    # Only this school
        .filter(student_filter)
        .options(joinedload(StudentBusAbsence.student))                            # Load student relation
        .order_by(StudentBusAbsence.date.asc(), StudentBusAbsence.id.asc())        # Stable ordering
        .all()                                                                     # Materialize list
    )

    results = []                                                                   # Response container

    for absence in absences:                                                       # Build response rows
        results.append(
            _build_absence_row(absence=absence)
        )

    return _build_absence_response(
        context_type="school",
        context_value=school_id,
        absences=results,
    )

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
    get_route_for_execution_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
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
            _build_absence_row(
                absence=absence,
                stop_name=absence.student.stop.name if absence.student and absence.student.stop else None,
            )
        )

    return _build_absence_response(
        context_type="run",
        context_value=run_id,
        absences=results,
    )

# -----------------------------------------------------------
# - School reports by date
# - Return present or absent status for school students
# -----------------------------------------------------------
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
    route_filter = _get_execution_route_filter(db=db, operator_id=operator.id)
    school = get_school_for_execution_or_404(
        db=db,
        operator_id=operator.id,
        school_id=school_id,
        detail="School not found",
    )

    runs = (
        db.query(Run)                                                            # Query runs
        .join(Route, Route.id == Run.route_id)
        .filter(Run.route.has(Route.schools.any(School.id == school_id)))        # Only runs whose route includes this school       
        .filter(route_filter)
        .filter(Run.start_time >= target_date)                                   # On or after start of requested day
        .filter(Run.start_time < (target_date + timedelta(days=1)))              # Before next day
        .order_by(Run.start_time.asc(), Run.id.asc())                            # Stable ordering
        .all()                                                                   # Materialize list
    )

    routes_map = {}

    for run in runs:                                                             # Process each school run
        assignments = (
            db.query(StudentRunAssignment)                                       # Query runtime assignments
            .options(joinedload(StudentRunAssignment.student))                   # Load student relation
            .filter(StudentRunAssignment.run_id == run.id)                       # Only this run
            .order_by(StudentRunAssignment.id.asc())                             # Stable ordering
            .all()                                                               # Materialize list
        )

        route = run.route
        route_id = route.id if route else None
        if route_id not in routes_map:
            routes_map[route_id] = {
                "route_id": route_id,
                "route_number": route.route_number if route else None,
                "total_runs": 0,
                "runs": [],
            }

        students = []
        for assignment in assignments:                                           # Build school-facing rows
            students.append(
                {
                    "student_id": assignment.student_id,
                    "student_name": assignment.student.name if assignment.student else None,  # Student name
                    "status": "present" if assignment.picked_up else "absent",                # School-facing status
                }
            )
        routes_map[route_id]["runs"].append(
            {
                "run_id": run.id,
                "run_type": run.run_type,
                "date": run.start_time.date() if run.start_time else target_date,
                "students": students,
                "total_students": len(students),
                "total_present": sum(1 for student in students if student["status"] == "present"),
                "total_absent": sum(1 for student in students if student["status"] == "absent"),
            }
        )
        routes_map[route_id]["total_runs"] += 1

    routes = sorted(
        routes_map.values(),
        key=lambda route: route.get("route_number") or "",
    )
    for route_data in routes:
        route_data["runs"].sort(
            key=lambda run_data: (run_data.get("date") or target_date, run_data.get("run_type") or "")
        )

    return {
        "school_id": school.id,
        "school_name": school.name,                                             # School name
        "date": target_date,                                                    # Requested date
        "total_routes": len(routes),
        "routes": routes,
    }

# -----------------------------------------------------------
# - School mobile reports checklist
# - Render mobile-friendly school reports route list
# -----------------------------------------------------------
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
    yard_ids = _get_active_execution_yard_ids(db=db, operator_id=operator.id)
    report_data = reports_generator.school_routes_summary(
        db=db,                                                 # Pass DB session
        school_id=school_id,                                   # Requested school
        yard_ids=yard_ids,
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
    yard_ids = _get_active_execution_yard_ids(db=db, operator_id=operator.id)
    report_data = reports_generator.school_route_runs_summary(
        db=db,                                                # Pass DB session
        school_id=school_id,                                  # Requested school
        route_id=route_id,                                    # Requested route
        yard_ids=yard_ids,
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
    yard_ids = _get_active_execution_yard_ids(db=db, operator_id=operator.id)
    report_data = reports_generator.school_single_run_summary(
        db=db,                                                # Pass DB session
        school_id=school_id,                                  # Requested school
        run_id=run_id,                                        # Requested run
        yard_ids=yard_ids,
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
class SchoolStatusUpdate(BaseModel):                       # Canonical request body for path-driven school status updates
    status: str                                            # "present" or "absent"


# -------------------------------------------------------------------------
# School status update helper
# Reuse one validation path across canonical and compatibility endpoints
# -------------------------------------------------------------------------
def update_school_status_for_assignment(
    *,
    run_id: int,
    student_id: int,
    status_value: str,
    db: Session,
    operator: Operator,
):
    if status_value not in ["present", "absent"]:          # Validate allowed values
        raise HTTPException(
            status_code=400,
            detail="Invalid payload",
        )

    assignment = (
        db.query(StudentRunAssignment)                     # Query assignment record
        .options(
            joinedload(StudentRunAssignment.student),      # Load student for operator + school verification
            joinedload(StudentRunAssignment.run).joinedload(Run.route),  # Load run route for shared access validation
        )
        .filter(
            StudentRunAssignment.student_id == student_id, # Match student
            StudentRunAssignment.run_id == run_id,         # Match run
        )
        .first()
    )

    if not assignment:                                     # If no record found
        raise HTTPException(
            status_code=404,
            detail="Assignment not found",
        )
    if not assignment.student:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if not assignment.run or not assignment.run.route:
        raise HTTPException(status_code=404, detail="Assignment not found")

    get_route_for_execution_or_404(
        db=db,
        route_id=assignment.run.route_id,
        operator_id=operator.id,
    )                                                       # Enforce route-level operator visibility

    school_id = assignment.student.school_id if assignment.student else None   # Resolve owning school
    verification = None                                                        # Default no confirmation

    if school_id is not None:                                                  # Check school/run confirmation
        verification = (
            db.query(SchoolAttendanceVerification)
            .filter(
                SchoolAttendanceVerification.school_id == school_id,            # Match school
                SchoolAttendanceVerification.run_id == run_id,                  # Match run
            )
            .first()
        )

    if verification:                                                           # Lock updates after confirmation
        raise HTTPException(
            status_code=400,
            detail="Reports already confirmed for this run",
        )

    assignment.school_status = status_value                                    # Save school-layer status

    db.commit()                                                                # Persist change

    return {
        "message": "Status updated",
        "student_id": student_id,
        "run_id": run_id,
        "school_status": status_value,
    }


student_bus_absence_router = student_bus_absence.router

__all__ = ["router", "student_bus_absence_router"]

