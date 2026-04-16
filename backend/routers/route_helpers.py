from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import run as run_model
from backend.models.associations import RouteDriverAssignment
from backend.models.driver import Driver
from backend.models.route import Route
from backend.schemas.route import (
    RouteCreate,
    RouteDetailOut,
    RouteDetailRunOut,
    RouteDetailStopOut,
    RouteDetailStudentOut,
    RouteDriverAssignmentOut,
    RouteOut,
    RouteSchoolOut,
)
from backend.schemas.stop import RunStopCreate
from backend.utils.operator_scope import get_driver_operator_id
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.operator_scope import get_route_access_level
from backend.utils.planning_scope import get_schools_for_route_attachment_or_404
from backend.utils.planning_scope import validate_route_school_links
from backend.utils.route_driver_assignment import get_active_route_driver_assignments
from backend.utils.route_driver_assignment import get_primary_route_driver_assignments
from backend.utils.route_driver_assignment import resolve_primary_route_driver_assignment
from backend.utils.route_driver_assignment import resolve_route_driver_assignment


def _route_identity_query(
    *,
    db: Session,
    route_number: str,
    district_id: int | None,
    operator_id: int,
):
    query = db.query(Route).filter(Route.route_number == route_number)
    if district_id is not None:
        return query.filter(Route.district_id == district_id)
    return query.filter(Route.district_id.is_(None)).filter(Route.operator_id == operator_id)


def _get_conflicting_route_or_none(
    *,
    db: Session,
    route_number: str,
    district_id: int | None,
    operator_id: int,
    exclude_route_id: int | None = None,
) -> Route | None:
    query = _route_identity_query(
        db=db,
        route_number=route_number,
        district_id=district_id,
        operator_id=operator_id,
    )
    if exclude_route_id is not None:
        query = query.filter(Route.id != exclude_route_id)
    return query.first()


# -----------------------------------------------------------
# - Route serializer
# - Return stable route summary payloads with assignment context
# -----------------------------------------------------------
def _serialize_route(route: Route) -> RouteOut:
    active_driver_id = None  # Default when no active driver resolves
    active_driver_name = None  # Default when no active driver resolves
    primary_driver_id = None  # Default when no primary driver resolves
    primary_driver_name = None  # Default when no primary driver resolves

    try:
        active_assignment = resolve_route_driver_assignment(route)  # Resolve current operational route driver
        active_driver_id = active_assignment.driver_id  # Resolved driver identifier
        active_driver_name = active_assignment.driver.name if active_assignment.driver else None  # Resolved driver name
    except ValueError:
        pass  # Leave unresolved route driver fields empty

    try:
        primary_assignment = resolve_primary_route_driver_assignment(route)  # Resolve default/base route driver
        primary_driver_id = primary_assignment.driver_id  # Resolved primary driver identifier
        primary_driver_name = primary_assignment.driver.name if primary_assignment.driver else None  # Resolved primary driver name
    except ValueError:
        pass  # Leave unresolved primary driver fields empty

    runs_count = len(route.runs)  # Total runs linked to this route
    active_runs_count = sum(  # Count only active operational runs
        1
        for run in route.runs
        if run.start_time is not None and run.end_time is None
    )
    total_stops_count = sum(len(run.stops) for run in route.runs)  # Count all stops across route runs
    total_students_count = len({  # Count distinct runtime students across all route runs
        assignment.student_id
        for run in route.runs
        for assignment in run.student_assignments
    })

    return RouteOut(
        id=route.id,
        route_number=route.route_number,
        bus_id=route.bus_id,
        primary_bus_id=route.primary_bus_id,
        active_bus_id=route.active_bus_id,
        primary_bus_unit_number=route.primary_bus.unit_number if route.primary_bus else None,
        active_bus_unit_number=route.active_bus.unit_number if route.active_bus else None,
        clearance_note=route.clearance_note,
        school_ids=[school.id for school in sorted(route.schools, key=lambda school: (school.name, school.id))],
        school_names=[school.name for school in sorted(route.schools, key=lambda school: (school.name, school.id))],
        schools_count=len(route.schools),
        active_driver_id=active_driver_id,
        active_driver_name=active_driver_name,
        primary_driver_id=primary_driver_id,
        primary_driver_name=primary_driver_name,
        runs_count=runs_count,
        active_runs_count=active_runs_count,
        total_stops_count=total_stops_count,
        total_students_count=total_students_count,
    )


# -----------------------------------------------------------
# - Route detail serializer
# - Return the full nested route detail payload
# -----------------------------------------------------------
def _serialize_route_detail(route: Route) -> RouteDetailOut:
    active_driver_id = None  # Default when no active driver resolves
    active_driver_name = None  # Default when no active driver resolves
    primary_driver_id = None  # Default when no primary driver resolves
    primary_driver_name = None  # Default when no primary driver resolves

    try:
        active_assignment = resolve_route_driver_assignment(route)  # Resolve current operational route driver
        active_driver_id = active_assignment.driver_id  # Resolved driver identifier
        active_driver_name = active_assignment.driver.name if active_assignment.driver else None  # Resolved driver name
    except ValueError:
        pass  # Leave unresolved route driver fields empty

    try:
        primary_assignment = resolve_primary_route_driver_assignment(route)  # Resolve default/base route driver
        primary_driver_id = primary_assignment.driver_id  # Resolved primary driver identifier
        primary_driver_name = primary_assignment.driver.name if primary_assignment.driver else None  # Resolved primary driver name
    except ValueError:
        pass  # Leave unresolved primary driver fields empty

    ordered_runs = sorted(  # Keep detail output stable and newest-first
        route.runs,
        key=lambda run: (run.start_time or datetime.min, run.id),
        reverse=True,
    )

    serialized_runs = []  # Final run detail rows

    for run in ordered_runs:
        ordered_stops = sorted(  # Stable stop order per run
            run.stops,
            key=lambda stop: (
                stop.sequence if stop.sequence is not None else 999999,
                stop.id,
            ),
        )

        stop_student_counts = {}  # stop_id -> runtime student count
        for assignment in run.student_assignments:
            if assignment.stop_id is None:
                continue
            stop_student_counts[assignment.stop_id] = stop_student_counts.get(assignment.stop_id, 0) + 1

        serialized_stops = [
            RouteDetailStopOut(
                stop_id=stop.id,
                sequence=stop.sequence,
                type=stop.type.value if hasattr(stop.type, "value") else str(stop.type),
                name=stop.name,
                school_id=stop.school_id,
                address=stop.address,
                planned_time=stop.planned_time,
                student_count=stop_student_counts.get(stop.id, 0),
            )
            for stop in ordered_stops
        ]

        ordered_assignments = sorted(  # Stable student order by assigned stop then row id
            run.student_assignments,
            key=lambda assignment: (
                assignment.stop.sequence if assignment.stop and assignment.stop.sequence is not None else 999999,
                assignment.student.name if assignment.student else "",
                assignment.id,
            ),
        )

        serialized_students = []
        for assignment in ordered_assignments:
            if not assignment.student:
                continue

            serialized_students.append(
                RouteDetailStudentOut(
                    student_id=assignment.student.id,
                    student_name=assignment.student.name,
                    school_id=assignment.student.school_id,
                    school_name=assignment.student.school.name if assignment.student.school else None,
                    stop_id=assignment.stop_id,
                    stop_sequence=assignment.stop.sequence if assignment.stop else None,
                    stop_name=assignment.stop.name if assignment.stop else None,
                )
            )

        serialized_runs.append(
            RouteDetailRunOut(
                run_id=run.id,
                run_type=run.run_type,
                scheduled_start_time=run.scheduled_start_time,
                scheduled_end_time=run.scheduled_end_time,
                start_time=run.start_time,
                end_time=run.end_time,
                driver_id=run.driver_id,
                driver_name=run.driver.name if run.driver else None,
                is_planned=run.start_time is None,
                is_active=run.start_time is not None and run.end_time is None,
                is_completed=run.is_completed,
                stops=serialized_stops,
                students=serialized_students,
            )
        )

    return RouteDetailOut(
        id=route.id,
        route_number=route.route_number,
        bus_id=route.bus_id,
        primary_bus_id=route.primary_bus_id,
        active_bus_id=route.active_bus_id,
        primary_bus_unit_number=route.primary_bus.unit_number if route.primary_bus else None,
        active_bus_unit_number=route.active_bus.unit_number if route.active_bus else None,
        clearance_note=route.clearance_note,
        schools=[
            RouteSchoolOut(
                school_id=school.id,
                school_name=school.name,
            )
            for school in sorted(route.schools, key=lambda school: (school.name, school.id))
        ],
        active_driver_id=active_driver_id,
        active_driver_name=active_driver_name,
        primary_driver_id=primary_driver_id,
        primary_driver_name=primary_driver_name,
        driver_assignments=[
            RouteDriverAssignmentOut(
                id=assignment.id,
                route_id=assignment.route_id,
                driver_id=assignment.driver_id,
                driver_name=assignment.driver.name if assignment.driver else None,
                active=assignment.active,
                is_primary=assignment.is_primary,
            )
            for assignment in sorted(
                route.driver_assignments,
                key=lambda assignment: (not assignment.active, not assignment.is_primary, assignment.id),
            )
        ],
        runs=serialized_runs,
    )


def create_route_record(
    *,
    route: RouteCreate,
    db: Session,
    operator_id: int,
    district_id: int | None = None,
) -> Route:
    payload = route.model_dump(exclude_unset=True)  # Read validated route payload
    payload_district_id = payload.get("district_id")
    payload.pop("district_id", None)
    school_ids = payload.pop("school_ids", [])  # Separate school assignment ids
    effective_district_id = district_id if district_id is not None else payload_district_id

    existing_route = _get_conflicting_route_or_none(
        db=db,
        route_number=payload["route_number"],
        district_id=effective_district_id,
        operator_id=operator_id,
    )
    if existing_route:
        raise HTTPException(
            status_code=409,  # Conflict for duplicate route number
            detail="Route number already exists",
        )

    db_route = Route(
        **payload,
        district_id=effective_district_id,
        operator_id=operator_id,
    )  # Create route after uniqueness check
    db.add(db_route)  # Add route to session
    db.flush()  # Allocate route id before school linking

    if school_ids:
        schools = get_schools_for_route_attachment_or_404(
            db=db,
            school_ids=school_ids,
        )
        validate_route_school_links(
            route_district_id=effective_district_id,
            route_operator_id=operator_id,
            schools=schools,
        )
        db_route.schools = schools  # Attach requested schools

    return db_route


# -----------------------------------------------------------
# - Assign driver to route
# - Enforce primary/default and active/current route-driver rules
# -----------------------------------------------------------
def _assert_route_driver_assignment_integrity(route: Route) -> None:
    active_assignments = get_active_route_driver_assignments(route)  # Operational assignments
    if len(active_assignments) > 1:
        raise HTTPException(status_code=409, detail="Route has multiple active driver assignments")

    primary_assignments = get_primary_route_driver_assignments(route)  # Default/base assignments
    if len(primary_assignments) > 1:
        raise HTTPException(status_code=409, detail="Route has multiple primary driver assignments")


def _get_route_assignment_for_driver(
    route: Route,
    driver_id: int,
) -> RouteDriverAssignment | None:
    for assignment in route.driver_assignments:
        if assignment.driver_id == driver_id:
            return assignment
    return None


def _get_primary_route_assignment(route: Route) -> RouteDriverAssignment | None:
    primary_assignments = get_primary_route_driver_assignments(route)  # Default/base assignments only
    if not primary_assignments:
        return None
    if len(primary_assignments) > 1:
        raise HTTPException(status_code=409, detail="Route has multiple primary driver assignments")
    return primary_assignments[0]


def _assign_driver_to_route(
    route: Route,
    driver_id: int,
    db: Session,
) -> RouteDriverAssignment:
    driver = db.get(Driver, driver_id)  # Validate driver exists
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    driver_operator_id = get_driver_operator_id(driver)
    if driver_operator_id != route.operator_id and get_route_access_level(route, driver_operator_id) != "operate":
        raise HTTPException(status_code=400, detail="Driver is not allowed for this route")

    _assert_route_driver_assignment_integrity(route)  # Fail safely on invalid legacy active/primary state

    primary_assignment = _get_primary_route_assignment(route)  # Resolve existing default/base driver when present
    existing_assignment = _get_route_assignment_for_driver(route, driver_id)  # Reuse existing route history row when safe

    active_assignments = get_active_route_driver_assignments(route)
    for assignment in active_assignments:
        assignment.active = False  # Only one active driver allowed

    if existing_assignment is not None:
        existing_assignment.active = True  # Selected existing driver becomes current operator
        if primary_assignment is None:
            existing_assignment.is_primary = True  # Establish first safe default/base owner when missing
        db.flush()
        return existing_assignment

    new_assignment = RouteDriverAssignment(
        route_id=route.id,
        driver_id=driver_id,
        active=True,
        is_primary=primary_assignment is None,
    )

    db.add(new_assignment)
    db.flush()

    return new_assignment


# -----------------------------------------------------------
# - Route-run stop creation helper
# - Create a stop inside a selected route and run context pair
# -----------------------------------------------------------
def _create_route_run_stop(
    *,
    route_id: int,
    run_id: int,
    payload: RunStopCreate,
    db: Session,
    operator,
):
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    run = db.get(run_model.Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.route_id != route.id:
        raise HTTPException(status_code=400, detail="Run does not belong to route")

    return stop_router.create_run_stop(
        run_id=run.id,
        payload=payload,
        db=db,
    )
