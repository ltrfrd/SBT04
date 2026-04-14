from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db

from backend import schemas
from backend.models.associations import RouteDriverAssignment
from backend.models.bus import Bus
from backend.models.operator import Operator, OperatorRouteAccess
from backend.models.driver import Driver
from backend.models.route import Route
from backend.models.school import School
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import StudentRunAssignment
from backend.schemas.route import (
    RouteCreate,
    RouteDetailOut,
    RouteDetailRunOut,
    RouteDetailStopOut,
    RouteDetailStudentOut,
    RouteDriverAssignmentCreate,
    RouteDriverAssignmentOut,
    RouteOut,
    RouteRestorePrimaryBus,
    RouteSchoolOut,
)
from backend.schemas.run import RouteRunCreate, RunUpdate
from backend.schemas.stop import RunStopCreate, StopOut, StopUpdate
from backend.utils.planning_scope import (
    accessible_route_filter,
    get_route_run_or_404,
    get_route_stop_or_404,
    get_route_student_or_404,
    get_schools_for_route_attachment_or_404,
    validate_route_school_alignment,
    validate_route_school_links,
)
from backend.utils.route_driver_assignment import (
    get_active_route_driver_assignments,
    get_primary_route_driver_assignments,
    resolve_primary_route_driver_assignment,
    resolve_route_driver_assignment,
)
from backend.utils.operator_scope import create_operator_route_access
from backend.utils.operator_scope import get_bus_operator_id
from backend.utils.operator_scope import ensure_route_owner
from backend.utils.operator_scope import get_driver_operator_id
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.operator_scope import get_route_access_level
from datetime import datetime, timezone

router = APIRouter(prefix="/routes", tags=["Routes"])


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

# -----------------------------------------------------------
# - Create route without driver assignment
# - Document duplicate route_number conflict in Swagger
# -----------------------------------------------------------
@router.post(
    "/",                                                          # Keep route collection path stable
    response_model=RouteOut,                                     # Successful response model
    summary="Create route",                                      # Clear Swagger title
    description=(                                                # Explain real route creation flow
        "Create a route with route_number and optional school_ids only. "
        "Bus assignment is handled separately. "
        "Driver assignment is also handled separately. "
        "Route numbers must be unique."
    ),
    response_description="Created route",                        # Swagger success text
    responses={
        409: {                                                   # Duplicate route_number response
            "description": "Route number already exists",
            "content": {
                "application/json": {
                    "example": {"detail": "Route number already exists"}
                }
            },
        }
    },
)
def create_route(
    route: RouteCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    db_route = create_route_record(
        route=route,
        db=db,
        operator_id=operator.id,
    )
    db.commit()                                                  # Persist route and optional schools
    db.refresh(db_route)                                         # Reload committed route
    return _serialize_route(db_route)                            # Return route summary


def create_route_record(
    *,
    route: RouteCreate,
    db: Session,
    operator_id: int,
    district_id: int | None = None,
) -> Route:
    payload = route.model_dump(exclude_unset=True)               # Read validated route payload
    if district_id is not None:
        payload.pop("district_id", None)
    school_ids = payload.pop("school_ids", [])                   # Separate school assignment ids
    effective_district_id = district_id if district_id is not None else payload.get("district_id")

    existing_route = _get_conflicting_route_or_none(
        db=db,
        route_number=payload["route_number"],
        district_id=effective_district_id,
        operator_id=operator_id,
    )
    if existing_route:
        raise HTTPException(
            status_code=409,                                     # Conflict for duplicate route number
            detail="Route number already exists",
        )

    db_route = Route(
        **payload,
        district_id=effective_district_id,
        operator_id=operator_id,
    )           # Create route after uniqueness check
    db.add(db_route)                                             # Add route to session
    db.flush()                                                   # Allocate route id before school linking

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
# - List routes
# - Return route summaries for navigation and selection
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[RouteOut],
    summary="List routes",
    description="Return lightweight route summaries with school, driver, run, stop, and student counts for navigation.",
    response_description="Route summary list",
)
def get_routes(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    routes = (
        db.query(Route)
        .options(
            selectinload(Route.schools),                         # Load school summary fields
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),  # Load active driver context
            selectinload(Route.runs).selectinload(run_model.Run.stops),  # Load stop counts per run
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments),  # Load runtime student counts
        )
        .filter(accessible_route_filter(operator.id))
        .order_by(Route.route_number.asc(), Route.id.asc())      # Keep route list stable
        .all()
    )
    return [_serialize_route(route) for route in routes]         # Return summary collection

# -----------------------------------------------------------
# - Get route detail
# - Return full nested route details for one selected route
# -----------------------------------------------------------
@router.get(
    "/{route_id}",
    response_model=RouteDetailOut,
    summary="Get route detail",
    description="Return one route with nested schools, driver assignments, runs, stops, and runtime student details.",
    response_description="Route detail",
)
def get_route(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = (
        db.query(Route)
        .options(
            selectinload(Route.schools),
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),
            selectinload(Route.runs).selectinload(run_model.Run.driver),
            selectinload(Route.runs).selectinload(run_model.Run.stops),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),
        )
        .filter(Route.id == route_id)
        .filter(accessible_route_filter(operator.id))
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return _serialize_route_detail(route)                       # Return full route detail payload


# -----------------------------------------------------------
# - Update route
# - Modify one route while preserving uniqueness rules
# -----------------------------------------------------------
@router.put(
    "/{route_id}",
    response_model=RouteOut,
    summary="Update route",
    description=(
        "Update one route with route_number and optional school_ids only. "
        "Bus assignment is handled separately. "
        "Driver assignment remains separate."
    ),
    response_description="Updated route",
)
def update_route(
    route_id: int,
    route_in: RouteCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = (
        db.query(Route)
        .options(
            joinedload(Route.schools),
            joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver),
        )
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    ensure_route_owner(route, operator.id)

    update_data = route_in.model_dump(exclude_unset=True)
    school_ids = update_data.pop("school_ids", None)
    schools = None
    # -----------------------------------------------------------
    # - Protect route_number uniqueness on update
    # - Exclude current route from duplicate detection
    # -----------------------------------------------------------
    new_route_number = update_data.get("route_number", route.route_number)          # Proposed route number from request
    target_district_id = update_data.get("district_id", route.district_id)

    if (
        new_route_number != route.route_number
        or target_district_id != route.district_id
    ):
        existing_route = _get_conflicting_route_or_none(
            db=db,
            route_number=new_route_number,
            district_id=target_district_id,
            operator_id=operator.id,
            exclude_route_id=route_id,
        )

        if existing_route:                                                          # Duplicate route number found
            raise HTTPException(
                status_code=409,
                detail="Route number already exists",
            )
    for key, value in update_data.items():
        setattr(route, key, value)

    if school_ids is not None:
        schools = get_schools_for_route_attachment_or_404(
            db=db,
            school_ids=school_ids,
        )

    validate_route_school_links(
        route_district_id=target_district_id,
        route_operator_id=route.operator_id,
        schools=schools if schools is not None else list(route.schools),
    )

    if school_ids is not None:
        route.schools = schools

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


# -----------------------------------------------------------
# - Route-context run creation
# - Create a planned run inside the selected route context
# -----------------------------------------------------------
@router.post(
    "/{route_id}/runs",
    response_model=schemas.RunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create run inside route",
    description=(
        "Primary workflow-first run creation path. "
        "Create a planned run inside the selected route context without sending route_id in the body. "
        "When exactly one active route-driver assignment exists, the planned run inherits that active driver. "
        "Primary/default assignment does not control operational run resolution by itself."
    ),
    response_description="Created run",
)
def create_route_run(
    route_id: int,
    payload: RouteRunCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import run as run_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )

    new_run = run_router._create_planned_run(                   # Reuse shared run creation rules
        route=route,                                            # Parent route context
        run_type=payload.run_type,                              # Normalized run label
        scheduled_start_time=payload.scheduled_start_time,      # Fixed planned start time
        scheduled_end_time=payload.scheduled_end_time,          # Fixed planned end time
        db=db,                                                  # Shared DB session
    )
    db.commit()
    db.refresh(new_run)
    return run_router._serialize_run(new_run)


# -----------------------------------------------------------
# - List planned runs inside route
# - Return all planned runs for the selected route context
# -----------------------------------------------------------
@router.get(
    "/{route_id}/runs",
    response_model=List[schemas.RunOut],
    summary="List runs inside route",
    description="Return all planned runs that belong to the selected route.",
    response_description="Route runs",
)
def get_route_runs(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import run as run_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    runs = (
        db.query(run_model.Run)
        .filter(run_model.Run.route_id == route.id)
        .order_by(run_model.Run.id.asc())
        .all()
    )
    return [run_router._serialize_run(run) for run in runs]


# -----------------------------------------------------------
# - Update planned run inside route
# - Modify one planned run while enforcing route path ownership
# -----------------------------------------------------------
@router.put(
    "/{route_id}/runs/{run_id}",
    response_model=schemas.RunOut,
    summary="Update run inside route",
    description="Update one planned run under the selected route context. The path route_id is authoritative.",
    response_description="Updated run",
)
def update_route_run(
    route_id: int,
    run_id: int,
    payload: RunUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import run as run_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    run = get_route_run_or_404(route_id=route.id, run_id=run_id, db=db)

    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be updated")

    run_router._assert_unique_route_run_type(
        route_id=route.id,
        normalized_run_type=payload.run_type,
        db=db,
        exclude_run_id=run.id,
    )
    run.run_type = payload.run_type
    if payload.scheduled_start_time is not None:
        run.scheduled_start_time = payload.scheduled_start_time
    if payload.scheduled_end_time is not None:
        run.scheduled_end_time = payload.scheduled_end_time

    db.commit()
    db.refresh(run)
    return run_router._serialize_run(run)


# -----------------------------------------------------------
# - Delete planned run inside route
# - Remove one planned run while enforcing route path ownership
# -----------------------------------------------------------
@router.delete(
    "/{route_id}/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete run inside route",
    description="Delete one planned run under the selected route context. The path route_id is authoritative.",
    response_description="Run deleted",
)
def delete_route_run(
    route_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    run = get_route_run_or_404(route_id=route.id, run_id=run_id, db=db)

    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be deleted")

    db.delete(run)
    db.commit()
    return None


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
    operator: Operator,
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


# -----------------------------------------------------------
# - Create stop inside route run
# - Attach one planned stop under a route-owned run using path context only
# -----------------------------------------------------------
@router.post(
    "/{route_id}/runs/{run_id}/stops",
    response_model=StopOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create stop inside route run",
    description="Primary path-driven stop creation workflow. Create a planned stop under the selected route and run context without sending internal run_id in the body.",
    response_description="Created stop",
)
def create_route_run_stop(
    route_id: int,
    run_id: int,
    payload: RunStopCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return _create_route_run_stop(
        route_id=route_id,
        run_id=run_id,
        payload=payload,
        db=db,
        operator=operator,
    )


# -----------------------------------------------------------
# - List planned stops inside route
# - Return all stops that inherit the route context
# -----------------------------------------------------------
@router.get(
    "/{route_id}/stops",
    response_model=List[StopOut],
    summary="List stops inside route",
    description="Return all planned stops that belong to the selected route.",
    response_description="Route stops",
)
def get_route_stops(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    return (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.route_id == route.id)
        .order_by(stop_model.Stop.run_id.asc(), stop_model.Stop.sequence.asc(), stop_model.Stop.id.asc())
        .all()
    )


# -----------------------------------------------------------
# - Update stop inside route
# - Modify one planned stop while enforcing route path ownership
# -----------------------------------------------------------
@router.put(
    "/{route_id}/stops/{stop_id}",
    response_model=StopOut,
    summary="Update stop inside route",
    description="Update one planned stop under the selected route context. The stop may not be moved across runs through this route-level endpoint.",
    response_description="Updated stop",
)
def update_route_stop(
    route_id: int,
    stop_id: int,
    payload: StopUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    stop = get_route_stop_or_404(route_id=route.id, stop_id=stop_id, db=db)

    updated_stop = stop_router._update_stop_record(
        stop=stop,
        payload=schemas.RunStopUpdate(
            sequence=payload.sequence,
            type=payload.type,
            name=payload.name,
            school_id=payload.school_id,
            address=payload.address,
            planned_time=payload.planned_time,
            latitude=payload.latitude,
            longitude=payload.longitude,
        ),
        db=db,
        authoritative_run_id=stop.run_id,
    )
    db.commit()
    db.refresh(updated_stop)
    return updated_stop


# -----------------------------------------------------------
# - Delete stop inside route
# - Remove one planned stop while enforcing route path ownership
# -----------------------------------------------------------
@router.delete(
    "/{route_id}/stops/{stop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete stop inside route",
    description="Delete one planned stop under the selected route context and normalize the remaining run sequence order.",
    response_description="Stop deleted",
)
def delete_route_stop(
    route_id: int,
    stop_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    stop = get_route_stop_or_404(route_id=route.id, stop_id=stop_id, db=db)

    run_id = stop.run_id
    db.delete(stop)
    db.flush()
    stop_router.normalize_run_sequences(db, run_id)
    db.commit()
    return None


# -----------------------------------------------------------
# - Create student inside route
# - Attach one planning student record directly to route context
# -----------------------------------------------------------
@router.post(
    "/{route_id}/students",
    response_model=schemas.StudentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create student inside route",
    description="Route-scoped planning helper. This is not the preferred initial student setup workflow. Preferred workflow is POST /runs/{run_id}/stops/{stop_id}/students so run and stop context stay authoritative.",
    response_description="Created student",
)
def create_route_student(
    route_id: int,
    payload: schemas.StudentCompatibilityCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import student as student_router  # Local import avoids circular import at module load time

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[selectinload(Route.schools)],
    )
    school = db.get(School, payload.school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    _, stop = student_router._validate_compatibility_student_create_target(
        school=school,
        student_district_id=route.district_id,
        route_id=route.id,
        stop_id=payload.stop_id,
        operator_id=operator.id,
        db=db,
    )

    new_student = student_model.Student(
        name=payload.name,
        grade=payload.grade,
        school_id=school.id,
        route_id=route.id,
        stop_id=stop.id if stop is not None else None,
        district_id=route.district_id,
        operator_id=operator.id,
    )
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


# -----------------------------------------------------------
# - List students inside route
# - Return all planning-side students linked directly to route
# -----------------------------------------------------------
@router.get(
    "/{route_id}/students",
    response_model=List[schemas.StudentOut],
    summary="List students inside route",
    description="Return all planning-side student records linked directly to the selected route.",
    response_description="Route students",
)
def get_route_students(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    return (
        db.query(student_model.Student)
        .filter(student_model.Student.route_id == route.id)
        .order_by(student_model.Student.name.asc(), student_model.Student.id.asc())
        .all()
    )


# -----------------------------------------------------------
# - Remove student from route
# - Clear direct route-planning linkage under route context
# -----------------------------------------------------------
@router.delete(
    "/{route_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove student from route",
    description="Remove one student from the selected route planning context without deleting the student record entirely.",
    response_description="Student removed from route",
)
def delete_route_student(
    route_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    student = get_route_student_or_404(route_id=route.id, student_id=student_id, db=db)

    student.route_id = None
    if student.stop_id is not None:
        stop = db.get(stop_model.Stop, student.stop_id)
        stop_route_id = stop.route_id if stop and stop.route_id is not None else stop.run.route_id if stop and stop.run else None
        if stop_route_id == route.id:
            student.stop_id = None

    db.commit()
    return None


# -----------------------------------------------------------
# - Delete route
# - Remove one route by id
# -----------------------------------------------------------
@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)
    db.delete(route)
    db.commit()
    return None


# -----------------------------------------------------------
# - List route schools
# - Return the schools linked to one route
# -----------------------------------------------------------
@router.get("/{route_id}/schools", response_model=List[dict])
def get_route_schools(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    return [{"id": s.id, "name": s.name, "address": s.address} for s in route.schools]


# -----------------------------------------------------------
# - Assign bus to route
# - Set the current bus pointer for route context
# -----------------------------------------------------------
@router.post(
    "/{route_id}/assign_bus/{bus_id}",
    response_model=RouteOut,
    summary="Assign bus to route",
    description="Assign one current bus to the route without changing route setup or runtime workflow behavior.",
    response_description="Updated route with assigned bus",
)
def assign_bus_to_route(
    route_id: int,
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus_operator_id = get_bus_operator_id(bus)
    if bus_operator_id != route.operator_id and get_route_access_level(route, bus_operator_id) != "operate":
        raise HTTPException(status_code=400, detail="Bus is not allowed for this route")

    route.active_bus_id = bus.id                               # Assign the active operational bus
    route.bus_id = bus.id                                      # Keep compatibility-facing bus pointer aligned
    if route.primary_bus_id is None:
        route.primary_bus_id = bus.id                          # First assigned bus also becomes the primary/default bus
    db.commit()
    db.refresh(route)
    return _serialize_route(route)


# -----------------------------------------------------------
# - Set primary bus for route
# - Update the default/base route bus safely
# -----------------------------------------------------------
@router.post(
    "/{route_id}/set_primary_bus/{bus_id}",
    response_model=RouteOut,
    summary="Set primary bus for route",
    description="Set the default/base bus for a route. If no active bus exists yet, active bus and compatibility bus_id are aligned to the same bus.",
    response_description="Updated route with primary bus",
)
def set_primary_bus_for_route(
    route_id: int,
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus_operator_id = get_bus_operator_id(bus)
    if bus_operator_id != route.operator_id and get_route_access_level(route, bus_operator_id) != "operate":
        raise HTTPException(status_code=400, detail="Bus is not allowed for this route")

    route.primary_bus_id = bus.id                              # Set the default/base route bus
    if route.active_bus_id is None:
        route.active_bus_id = bus.id                           # Fill missing active bus from the new primary
        route.bus_id = bus.id                                  # Keep compatibility bus pointer aligned

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


# -----------------------------------------------------------
# - Set active bus for route
# - Update the operational bus while preserving compatibility
# -----------------------------------------------------------
@router.post(
    "/{route_id}/set_active_bus/{bus_id}",
    response_model=RouteOut,
    summary="Set active bus for route",
    description="Set the current operational bus for a route and keep the legacy compatibility bus_id aligned.",
    response_description="Updated route with active bus",
)
def set_active_bus_for_route(
    route_id: int,
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus_operator_id = get_bus_operator_id(bus)
    if bus_operator_id != route.operator_id and get_route_access_level(route, bus_operator_id) != "operate":
        raise HTTPException(status_code=400, detail="Bus is not allowed for this route")

    route.active_bus_id = bus.id                               # Set the current operational bus
    route.bus_id = bus.id                                      # Keep compatibility bus pointer aligned

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


# -----------------------------------------------------------
# - Restore primary bus
# - Move the active bus back to the default/base bus
# -----------------------------------------------------------
@router.post(
    "/{route_id}/restore_primary_bus",
    response_model=RouteOut,
    summary="Restore primary bus for route",
    description="Restore the active operational bus back to the route's primary/default bus and optionally record a clearance note.",
    response_description="Updated route with restored primary bus",
)
def restore_primary_bus_for_route(
    route_id: int,
    payload: RouteRestorePrimaryBus | None = None,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    if route.primary_bus_id is None:
        raise HTTPException(status_code=400, detail="Route has no primary bus to restore")

    route.active_bus_id = route.primary_bus_id                 # Restore active bus from the primary/default bus
    route.bus_id = route.primary_bus_id                        # Keep compatibility bus pointer aligned
    route.clearance_note = payload.clearance_note if payload else None  # Store optional dispatch/operator note

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


# -----------------------------------------------------------
# - Unassign bus from route
# - Clear the current bus pointer for route context
# -----------------------------------------------------------
@router.delete(
    "/{route_id}/unassign_bus",
    response_model=RouteOut,
    summary="Unassign bus from route",
    description="Clear the current bus assignment from the route without changing route setup or runtime workflow behavior.",
    response_description="Updated route without assigned bus",
)
def unassign_bus_from_route(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    route.active_bus_id = None                                 # Clear active operational bus
    route.bus_id = None                                        # Clear compatibility-facing bus pointer
    db.commit()
    db.refresh(route)
    return _serialize_route(route)


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
    driver = db.get(Driver, driver_id)                           # Validate driver exists
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    driver_operator_id = get_driver_operator_id(driver)
    if driver_operator_id != route.operator_id and get_route_access_level(route, driver_operator_id) != "operate":
        raise HTTPException(status_code=400, detail="Driver is not allowed for this route")

    _assert_route_driver_assignment_integrity(route)             # Fail safely on invalid legacy active/primary state

    primary_assignment = _get_primary_route_assignment(route)    # Resolve existing default/base driver when present
    existing_assignment = _get_route_assignment_for_driver(route, driver_id)  # Reuse existing route history row when safe

    # -----------------------------------------------------------
    # Deactivate all current active assignments
    # Active remains the only operational source of truth
    # -----------------------------------------------------------
    active_assignments = get_active_route_driver_assignments(route)

    for assignment in active_assignments:
        assignment.active = False                                # Only one active driver allowed

    # -----------------------------------------------------------
    # Reuse existing assignment row when safe
    # Preserve primary/default meaning separately from active/current
    # -----------------------------------------------------------
    if existing_assignment is not None:
        existing_assignment.active = True                        # Selected existing driver becomes current operator
        if primary_assignment is None:
            existing_assignment.is_primary = True                # Establish first safe default/base owner when missing
        db.flush()
        return existing_assignment

    # -----------------------------------------------------------
    # Create new assignment row
    # First route driver becomes both primary and active
    # Later replacement drivers become active without replacing primary
    # -----------------------------------------------------------
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
# - Assign one active driver to a route
# - Swagger should describe the real assignment workflow
# -----------------------------------------------------------
@router.post(
    "/{route_id}/assign_driver/{driver_id}",                     # Route + driver selected from path
    response_model=RouteDriverAssignmentOut,                     # Return the activated assignment
    summary="Assign driver to route",                            # Clear Swagger title
    description=(                                                # Explain current route-driver workflow
        "Assign a driver to a route using separate primary/default and active/current semantics. "
        "The first route-driver assignment becomes both primary and active. "
        "Later assignments may activate a temporary replacement driver without removing the existing primary assignment. "
        "Operational run logic continues to follow the single active/current assignment only. No request body is required."
    ),
    response_description="The activated route-driver assignment",  # Swagger response text
)
def assign_driver_to_route(
    route_id: int,
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )
    ensure_route_owner(route, operator.id)

    assignment = _assign_driver_to_route(route, driver_id, db)

    db.commit()
    db.refresh(assignment)

    return RouteDriverAssignmentOut(
        id=assignment.id,
        route_id=assignment.route_id,
        driver_id=assignment.driver_id,
        driver_name=assignment.driver.name if assignment.driver else None,
        active=assignment.active,
        is_primary=assignment.is_primary,
    )

# -----------------------------------------------------------
# - List driver assignments for one route
# - Show current active and default primary assignment meaning
# -----------------------------------------------------------
@router.get(
    "/{route_id}/drivers",                                       # Read assignments for one route
    response_model=List[RouteDriverAssignmentOut],               # Return assignment collection
    summary="List route driver assignments",                     # Clear Swagger title
    description=(                                                # Explain what the list represents
        "Return all driver assignments for the route, including which assignment is currently active "
        "for operations and which assignment is the primary/default route owner. "
        "Operational run logic follows the active/current assignment only. "
        "Legacy date fields are not authoritative for live routing."
    ),
    response_description="Route driver assignment list",         # Swagger response text
)
def get_route_drivers(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )

    return [
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
    ]


# -----------------------------------------------------------
# - Unassign driver from route
# - Deactivate one route-driver assignment safely
# -----------------------------------------------------------
@router.delete(
    "/{route_id}/unassign_driver/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unassign driver from route",
    description=(
        "Deactivate the selected route-driver assignment safely. "
        "If the active assignment being removed is a temporary replacement and the route still has an inactive primary/default assignment, "
        "the primary assignment is reactivated automatically. "
        "Operational run logic continues to follow the single active/current assignment only."
    ),
    response_description="Route-driver assignment deactivated",
)
def unassign_driver_from_route(
    route_id: int,
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )
    ensure_route_owner(route, operator.id)

    _assert_route_driver_assignment_integrity(route)             # Fail safely on invalid legacy active/primary state

    assignment = _get_route_assignment_for_driver(route, driver_id)
    if assignment is None or assignment.active is not True:
        raise HTTPException(status_code=404, detail="Active route-driver assignment not found")

    # -----------------------------------------------------------
    # - Deactivate assignment
    # - Reactivate primary/default owner only when removing an active replacement
    # -----------------------------------------------------------
    assignment.active = False

    primary_assignment = _get_primary_route_assignment(route)    # Default/base owner may be restored after replacement ends
    if (
        primary_assignment is not None
        and primary_assignment.id != assignment.id
        and primary_assignment.active is not True
    ):
        primary_assignment.active = True                         # Restore primary only when a distinct replacement was active

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{route_id}/share/{target_operator_id}",
    summary="Grant shared route access",
    description="Owner-only endpoint that grants explicit read or operate access for a route to another operator.",
)
def share_route_with_operator(
    route_id: int,
    target_operator_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    if target_operator_id == route.operator_id:
        raise HTTPException(status_code=400, detail="Owner operator already has access")

    target_operator = db.get(Operator, target_operator_id)
    if not target_operator:
        raise HTTPException(status_code=404, detail="Operator not found")

    access_level = str(payload.get("access_level", "read")).strip().lower()
    if access_level not in {"read", "operate"}:
        raise HTTPException(status_code=400, detail="Invalid access level")

    grant = (
        db.query(OperatorRouteAccess)
        .filter(OperatorRouteAccess.route_id == route_id)
        .filter(OperatorRouteAccess.operator_id == target_operator_id)
        .first()
    )
    if grant is None:
        grant = create_operator_route_access(
            route_id=route_id,
            operator_id=target_operator_id,
            access_level=access_level,
        )
        db.add(grant)
    else:
        grant.access_level = access_level

    db.commit()
    db.refresh(grant)
    return {
        "route_id": route_id,
        "operator_id": target_operator_id,
        "access_level": grant.access_level,
    }


@router.delete(
    "/{route_id}/share/{target_operator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove shared route access",
    description="Owner-only endpoint that removes explicit shared access for a route.",
)
def unshare_route_with_operator(
    route_id: int,
    target_operator_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)

    grant = (
        db.query(OperatorRouteAccess)
        .filter(OperatorRouteAccess.route_id == route_id)
        .filter(OperatorRouteAccess.operator_id == target_operator_id)
        .first()
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Shared access not found")

    db.delete(grant)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

