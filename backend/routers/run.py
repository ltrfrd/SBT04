# ===========================================================
# backend/routers/run.py - FleetOS Run Router
# Manage run lifecycle, live stop progress, and rider actions.
# ===========================================================

from datetime import date, datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload, selectinload  # Used for eager loading relationships
from database import get_db
from backend import schemas
from backend.models import run as run_model
from backend.models import driver as driver_model
from backend.models import route as route_model
from backend.models import school as school_model
from backend.models import stop as stop_model
from backend.models import pretrip as pretrip_model
from backend.models import posttrip as posttrip_model
from backend.models.operator import Operator
from backend.models.run import Run                            # Run model
from backend.models.student import Student                      # Student model
from backend.models.stop import Stop                            # Stop model
from backend.models.associations import StudentRunAssignment  # Runtime rider assignments
from backend.models.associations import RouteDriverAssignment  # Route-level driver assignments
from backend.schemas.run import RunCreateLegacy, RunOut, RunUpdate, RunDetailOut, RunDetailRouteOut, RunDetailDriverOut, RunDetailStopOut, RunDetailStudentOut, RunListOut, normalize_run_type
from backend.models.run_event import RunEvent                  # Run timeline event model
from backend.models import student as student_model  # Student model for replay names
from backend.schemas.run import RunReplayOut, RunReplayEventOut, RunReplaySummaryOut
from backend.schemas.run import RunTimelineOut                 # Timeline response schema
from backend.schemas.stop import RunStopCreate, RunStopUpdate, StopOut
from backend.schemas.run import (  # Running board response schemas
    RunningBoardResponse,
    RunningBoardStop,
    RunningBoardStudent,
)
from backend.utils.student_bus_absence import apply_run_absence_filter
from backend.utils.route_driver_assignment import resolve_route_driver_assignment
from backend.utils.db_errors import raise_conflict_if_unique
from backend.utils.pretrip_alerts import create_missing_pretrip_alert_if_needed
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_record_or_404
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.operator_scope import get_route_access_level
from backend.utils.run_setup import ensure_run_is_planned_for_setup, get_run_stop_context_or_404
from backend.schemas.run import (
    PickupStudentRequest,
    PickupStudentResponse,
    DropoffStudentRequest,
    DropoffStudentResponse,
    OnboardStudentsResponse,
    OnboardStudentItem,
    RunOccupancySummaryResponse,
    RunStateOut,
    RunCompleteOut,
)
router = APIRouter(prefix="/runs", tags=["Runs"])


# -----------------------------------------------------------
# - Run state helpers
# - Shared read-only summary logic for occupancy and state views
# -----------------------------------------------------------
def _get_run_or_404(run_id: int, db: Session) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()  # Load run by ID
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    return run


def _get_operator_scoped_run_or_404(
    run_id: int,
    db: Session,
    operator_id: int,
    required_access: str = "read",
    options: list | None = None,
) -> Run:
    query = db.query(Run)
    if options:
        query = query.options(*options)

    run = query.filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator_id,
        required_access=required_access,
    )
    return run


def _get_run_assignments(run_id: int, db: Session) -> list[StudentRunAssignment]:
    run = _get_run_or_404(run_id, db)  # Load run once so absence filtering uses authoritative run date/type
    query = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
    )  # Base effective assignment query for this run
    return apply_run_absence_filter(query, run).all()  # Exclude planned absences from run-derived assignment views


def _build_run_occupancy_counts(assignments: list[StudentRunAssignment]) -> dict[str, int]:
    total_assigned_students = len(assignments)  # All students assigned to this run
    total_picked_up = sum(1 for assignment in assignments if assignment.picked_up)  # Picked up at least once
    total_dropped_off = sum(1 for assignment in assignments if assignment.dropped_off)  # Dropped off
    total_currently_onboard = sum(1 for assignment in assignments if assignment.is_onboard)  # Current bus load
    total_not_yet_boarded = sum(1 for assignment in assignments if not assignment.picked_up)  # Assigned but not picked up
    total_remaining_dropoffs = sum(
        1
        for assignment in assignments
        if assignment.picked_up and not assignment.dropped_off
    )  # Picked up already but still onboard / awaiting dropoff

    return {
        "total_assigned_students": total_assigned_students,
        "total_picked_up": total_picked_up,
        "total_dropped_off": total_dropped_off,
        "total_currently_onboard": total_currently_onboard,
        "total_not_yet_boarded": total_not_yet_boarded,
        "total_remaining_dropoffs": total_remaining_dropoffs,
    }


def _is_run_active(run: Run) -> bool:
    return run.start_time is not None and run.end_time is None  # Planned runs are not active until they start


def _require_posttrip_phase2_completed(run_id: int, db: Session) -> None:
    inspection = (
        db.query(posttrip_model.PostTripInspection)
        .filter(posttrip_model.PostTripInspection.run_id == run_id)
        .first()
    )                                                          # One post-trip row may exist per run
    if not inspection or inspection.phase2_completed is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post-trip phase 2 must be completed before ending the run",
        )


# -----------------------------------------------------------
# - Runtime action helpers
# - Keep flexible stop execution and rider validation consistent
# -----------------------------------------------------------
def _get_runtime_run_or_404(run_id: int, db: Session) -> Run:
    run = db.get(run_model.Run, run_id)                        # Load run once for runtime actions
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _require_active_runtime_run(run: Run) -> Run:
    if run.is_completed:                                       # Completed runs are read-only
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is already completed",
        )

    if run.start_time is None:                                 # Planned runs cannot accept live actions
        raise HTTPException(status_code=400, detail="Run is not active")

    if run.end_time is not None:                               # Ended runs are no longer live
        raise HTTPException(status_code=400, detail="Run has already ended")

    return run


def _get_ordered_run_stops(run_id: int, db: Session) -> list[stop_model.Stop]:
    return (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)              # Keep only this run's stops
        .order_by(stop_model.Stop.sequence.asc(), stop_model.Stop.id.asc())
        .all()
    )                                                          # Stable stop order supports convenience navigation


def _resolve_runtime_stop_target_or_404(
    *,
    run_id: int,
    stop_id: int | None,
    stop_sequence: int | None,
    db: Session,
) -> stop_model.Stop:
    if stop_id is None and stop_sequence is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stop_id or stop_sequence is required",
        )

    stop = None

    if stop_id is not None:
        stop = (
            db.query(stop_model.Stop)
            .filter(stop_model.Stop.run_id == run_id)
            .filter(stop_model.Stop.id == stop_id)
            .first()
        )                                                      # Resolve target by explicit stop id when provided
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found for this run")

    if stop_sequence is not None:
        sequence_stop = (
            db.query(stop_model.Stop)
            .filter(stop_model.Stop.run_id == run_id)
            .filter(stop_model.Stop.sequence == stop_sequence)
            .first()
        )                                                      # Preserve compatibility with stop_sequence callers
        if not sequence_stop:
            raise HTTPException(status_code=404, detail="Stop sequence not found for this run")

        if stop is not None and stop.id != sequence_stop.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="stop_id and stop_sequence do not match",
            )

        stop = sequence_stop

    return stop


def _set_run_current_stop(
    *,
    run: Run,
    stop: stop_model.Stop,
    db: Session,
) -> Run:
    run.current_stop_id = stop.id                              # Actual runtime location source of truth
    run.current_stop_sequence = stop.sequence                  # Preserve current stop sequence for read surfaces

    db.add(
        RunEvent(
            run_id=run.id,
            stop_id=stop.id,
            event_type="ARRIVE",
        )
    )                                                          # Repeated ARRIVE events are valid for revisits and jumps

    db.commit()
    db.refresh(run)
    return run


def _require_current_runtime_stop(run: Run, db: Session) -> stop_model.Stop:
    if run.current_stop_sequence is None or run.current_stop_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not currently at a stop",
        )

    current_stop = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run.id)
        .filter(stop_model.Stop.id == run.current_stop_id)
        .first()
    )                                                          # Validate the stored live stop still belongs to this run
    if not current_stop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not currently at a valid stop",
        )

    return current_stop


def _get_runtime_assignment_or_404(
    *,
    run_id: int,
    student_id: int,
    db: Session,
) -> StudentRunAssignment:
    assignment = (
        db.query(StudentRunAssignment)
        .options(joinedload(StudentRunAssignment.stop))
        .filter(
            StudentRunAssignment.run_id == run_id,
            StudentRunAssignment.student_id == student_id,
        )
        .first()
    )                                                          # Load run-scoped student assignment once

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student is not assigned to this run",
        )

    return assignment


# -----------------------------------------------------------
# - Runtime rider state helpers
# - Block impossible pickup/dropoff transitions before writes
# -----------------------------------------------------------
def _assert_pickup_transition_allowed(assignment: StudentRunAssignment) -> None:
    if assignment.dropped_off is True:                        # Dropped-off riders cannot board again
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been dropped off",
        )

    if assignment.picked_up is True:                          # Prevent duplicate pickup events
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been picked up",
        )

    if assignment.is_onboard is True:                         # Guard impossible duplicate onboard state
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is already onboard",
        )


def _assert_dropoff_transition_allowed(assignment: StudentRunAssignment) -> None:
    if assignment.dropped_off is True:                        # Prevent duplicate dropoff events
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been dropped off",
        )

    if assignment.picked_up is not True:                      # Cannot exit before boarding
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has not been picked up yet",
        )

    if assignment.is_onboard is not True:                     # Must still be onboard to drop off now
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is not currently onboard",
        )


# -----------------------------------------------------------
# - Planned run mutation guard
# - Allow setup mutations only while the run is still planned
# -----------------------------------------------------------
def _get_run_stop_or_404(run_id: int, stop_id: int, db: Session) -> tuple[run_model.Run, stop_model.Stop]:
    return get_run_stop_context_or_404(
        run_id=run_id,
        stop_id=stop_id,
        db=db,
        require_planned=True,
    )                                                          # Shared run/stop validation keeps assignment writes aligned


def _get_run_stop_student_context_or_404(
    run_id: int,
    stop_id: int,
    student_id: int,
    db: Session,
) -> tuple[run_model.Run, stop_model.Stop, student_model.Student, StudentRunAssignment]:
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)        # Reuse existing run-stop validation

    student = db.get(student_model.Student, student_id)          # Validate student exists
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.route_id != run.route_id:
        raise HTTPException(status_code=400, detail="Student does not belong to run route")

    assignment = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .filter(StudentRunAssignment.student_id == student_id)
        .first()
    )                                                            # Validate the internal runtime assignment exists
    if not assignment:
        raise HTTPException(status_code=400, detail="Student is not assigned to run")

    return run, stop, student, assignment


def _create_stop_context_student(
    *,
    run: run_model.Run,
    stop: stop_model.Stop,
    payload: schemas.StopStudentCreate,
    operator_id: int,
    db: Session,
) -> Student:
    school = get_operator_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=payload.school_id,
        operator_id=operator_id,
        detail="School not found",
    )

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator_id,
        required_access="read",
        options=[selectinload(route_model.Route.schools)],
    )

    route_school_ids = {school.id for school in route.schools}
    if payload.school_id not in route_school_ids:
        raise HTTPException(status_code=400, detail="School is not assigned to the run route")

    student = Student(
        name=payload.name,
        grade=payload.grade,
        district_id=run.route.district_id if run.route else None,
        operator_id=operator_id,
        school_id=payload.school_id,
        route_id=run.route_id,
        stop_id=stop.id,
    )  # Keep route and default stop pointers aligned with the selected workflow context
    db.add(student)
    db.flush()  # Allocate student id before creating the internal runtime assignment

    db.add(
        StudentRunAssignment(
            student_id=student.id,
            run_id=run.id,
            stop_id=stop.id,
        )
    )  # Preserve existing runtime execution source-of-truth
    db.flush()  # Surface any assignment conflicts before the outer commit

    db.refresh(student)
    return student


# -----------------------------------------------------------
# - Running board helpers
# - Keep running board assembly stable and source-of-truth aligned
# -----------------------------------------------------------
def _group_running_board_students(
    assignments: list[StudentRunAssignment],
) -> dict[int, list[RunningBoardStudent]]:
    assignments_by_stop: dict[int, list[RunningBoardStudent]] = {}  # stop_id -> ordered student rows

    for assignment in assignments:
        if assignment.stop_id is None or not assignment.student:
            continue

        assignments_by_stop.setdefault(
            assignment.stop_id,
            [],
        ).append(
            RunningBoardStudent(
                student_id=assignment.student.id,              # Stable student identifier
                student_name=assignment.student.name,          # Driver-facing student display
            )
        )

    return assignments_by_stop


def _build_running_board_stops(
    stops: list[stop_model.Stop],
    assignments_by_stop: dict[int, list[RunningBoardStudent]],
) -> list[RunningBoardStop]:
    running_stops: list[RunningBoardStop] = []                 # Final ordered stop rows
    cumulative_load = 0                                        # Running onboard total

    for stop in stops:
        stop_students = assignments_by_stop.get(stop.id, [])   # Students assigned to this stop
        student_count = len(stop_students)                     # Boardings sourced from runtime assignments
        load_change = student_count                            # Existing running board uses boarding count per stop
        cumulative_load += load_change                         # Preserve current cumulative behavior

        is_school_stop = stop.type in {"SCHOOL_ARRIVE", "SCHOOL_DEPART"}
        if is_school_stop and stop.school:
            display_name = stop.school.name                    # School stop rows display school name when linked
        else:
            display_name = stop.name or f"STOP {stop.sequence}"  # Fallback remains operator-friendly

        running_stops.append(
            RunningBoardStop(
                stop_id=stop.id,
                sequence=stop.sequence,
                stop_type=stop.type,
                is_school_stop=is_school_stop,
                display_name=display_name,
                planned_time=str(stop.planned_time) if stop.planned_time else None,
                lat=stop.latitude,
                lng=stop.longitude,
                student_count_at_stop=student_count,
                load_change=load_change,
                cumulative_load=cumulative_load,
                students=stop_students,
            )
        )

    return running_stops


# -----------------------------------------------------------
# - Route driver resolver
# - Require one active driver assignment per route
# - Primary/default ownership does not drive runtime selection
# -----------------------------------------------------------
def _resolve_run_driver(route):
    try:
        assignment = resolve_route_driver_assignment(route)  # Resolve the single active operational driver only
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return assignment.driver_id


def _resolve_planned_run_driver(route) -> int | None:
    try:
        assignment = resolve_route_driver_assignment(route)  # Planned runs inherit the current active operational driver only
    except ValueError as exc:
        if str(exc) == "Route has no active driver assignment":
            return None  # Planned runs may exist before a driver is assigned
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return assignment.driver_id


# -----------------------------------------------------------
# Run creation helpers
# Normalize flexible run labels and enforce one label per route
# -----------------------------------------------------------
def _assert_unique_route_run_type(
    *,
    route_id: int,
    normalized_run_type: str,
    db: Session,
    exclude_run_id: int | None = None,
) -> None:
    existing_runs = (
        db.query(run_model.Run)
        .filter(run_model.Run.route_id == route_id)
        .all()
    )

    for existing_run in existing_runs:
        if exclude_run_id is not None and existing_run.id == exclude_run_id:
            continue

        if normalize_run_type(existing_run.run_type) == normalized_run_type:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run label already exists for this route",
            )


def _create_planned_run(
    *,
    route: route_model.Route,
    run_type: str,
    scheduled_start_time,
    scheduled_end_time,
    db: Session,
) -> run_model.Run:
    normalized_run_type = normalize_run_type(run_type)          # Store normalized flexible label
    _assert_unique_route_run_type(
        route_id=route.id,
        normalized_run_type=normalized_run_type,
        db=db,
    )
    resolved_driver_id = _resolve_planned_run_driver(route)     # Planned runs may exist before a driver is assigned

    new_run = run_model.Run(                                    # Create run under current route context
        driver_id=resolved_driver_id,                           # Inherit current route driver when available
        route_id=route.id,                                      # Inherit route automatically
        district_id=route.district_id,                          # Inherit planning district when available
        run_type=normalized_run_type,                           # Store normalized flexible run label
        scheduled_start_time=scheduled_start_time,              # Store fixed planned start time
        scheduled_end_time=scheduled_end_time,                  # Store fixed planned end time
        start_time=None,                                        # Planned only until explicitly started
        end_time=None,                                          # Not completed
        current_stop_id=None,                                   # No live stop yet
        current_stop_sequence=None,                             # No live sequence yet
    )
    db.add(new_run)
    return new_run


# -----------------------------------------------------------
# - Run serializer
# - Return enriched run payloads with driver and route labels
# -----------------------------------------------------------
def _serialize_run(run: run_model.Run) -> RunOut:
    return RunOut(
        id=run.id,
        driver_id=run.driver_id,
        route_id=run.route_id,
        run_type=run.run_type,
        scheduled_start_time=run.scheduled_start_time,
        scheduled_end_time=run.scheduled_end_time,
        start_time=run.start_time,
        end_time=run.end_time,
        current_stop_id=run.current_stop_id,
        current_stop_sequence=run.current_stop_sequence,
        driver_name=run.driver.name if run.driver else None,
        route_number=run.route.route_number if run.route else None,
    )


# -----------------------------------------------------------
# - Run detail serializer
# - Return one run with nested route, stop, and student context
# -----------------------------------------------------------
def _serialize_run_detail(run: run_model.Run) -> RunDetailOut:
    ordered_stops = sorted(
        run.stops,
        key=lambda stop: (
            stop.sequence if stop.sequence is not None else 999999,
            stop.id,
        ),
    )                                                          # Keep stop order stable

    ordered_assignments = sorted(
        run.student_assignments,
        key=lambda assignment: (
            assignment.stop.sequence if assignment.stop and assignment.stop.sequence is not None else 999999,
            assignment.student.name if assignment.student else "",
            assignment.id,
        ),
    )                                                          # Keep student rows grouped by stop order

    return RunDetailOut(
        id=run.id,
        driver_id=run.driver_id,
        route_id=run.route_id,
        run_type=run.run_type,
        scheduled_start_time=run.scheduled_start_time,
        scheduled_end_time=run.scheduled_end_time,
        start_time=run.start_time,
        end_time=run.end_time,
        current_stop_id=run.current_stop_id,
        current_stop_sequence=run.current_stop_sequence,
        driver_name=run.driver.name if run.driver else None,
        route_number=run.route.route_number if run.route else None,
        route=RunDetailRouteOut(
            route_id=run.route_id,
            route_number=run.route.route_number if run.route else None,
        ),
        driver=RunDetailDriverOut(
            driver_id=run.driver_id,
            driver_name=run.driver.name if run.driver else None,
        ),
        stops=[
            RunDetailStopOut(
                stop_id=stop.id,
                sequence=stop.sequence,
                type=stop.type.value if hasattr(stop.type, "value") else str(stop.type),
                name=stop.name,
                school_id=stop.school_id,
                address=stop.address,
                planned_time=str(stop.planned_time) if stop.planned_time else None,
            )
            for stop in ordered_stops
        ],
        students=[
            RunDetailStudentOut(
                student_id=assignment.student.id,
                student_name=assignment.student.name,
                school_id=assignment.student.school_id,
                school_name=assignment.student.school.name if assignment.student.school else None,
                stop_id=assignment.stop_id,
                stop_sequence=assignment.stop.sequence if assignment.stop else None,
                stop_name=assignment.stop.name if assignment.stop else None,
            )
            for assignment in ordered_assignments
            if assignment.student
        ],
    )                                                          # Return nested run detail


# -----------------------------------------------------------
# - Run list serializer
# - Return summary-level run data for route-scoped listing
# -----------------------------------------------------------
def _serialize_run_list_item(run: run_model.Run) -> RunListOut:
    return RunListOut(
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
        is_completed=run.end_time is not None,
        stops_count=len(run.stops),
        students_count=len(run.student_assignments),
    )                                                          # Return run summary row


# -----------------------------------------------------------
# - Create run
# - Legacy planned run creation
# - Preserve compatibility while the route-context flow is primary
# -----------------------------------------------------------
@router.post(
    "/",                                                         # Route path
    response_model=schemas.RunOut,                               # Response schema
    status_code=status.HTTP_201_CREATED,                         # HTTP 201 on success
    summary="Create run (legacy compatibility)",                 # Swagger summary
    description=(
        "Legacy compatibility endpoint for creating a planned run by sending route_id in the body. "
        "Preferred workflow-first creation is POST /routes/{route_id}/runs so route context is inherited automatically. "
        "When exactly one active route-driver assignment exists, the planned run inherits that active driver. "
        "Primary/default assignment does not drive live run resolution by itself. "
        "A driver assignment is optional until the run is started."
    ),                                                           # Swagger description
    response_description="Created run",                          # Swagger response text
)
def create_run(
    run: RunCreateLegacy,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -----------------------------------------------------------
    # - Validate route exists
    # - Load route context and optional active driver assignment
    # -----------------------------------------------------------
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
        required_access="read",
        options=[
            joinedload(route_model.Route.driver_assignments).joinedload(RouteDriverAssignment.driver),
        ],
    )
    if route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Route not found")

    new_run = _create_planned_run(                               # Reuse normalized planned run workflow
        route=route,                                             # Selected route context
        run_type=run.run_type,                                   # Flexible run label
        scheduled_start_time=run.scheduled_start_time,           # Fixed planned start time
        scheduled_end_time=run.scheduled_end_time,               # Fixed planned end time
        db=db,                                                   # Shared DB session
    )
    db.commit()                                                  # Persist to DB
    db.refresh(new_run)                                          # Reload instance
    return _serialize_run(new_run)                               # Return response

# -----------------------------------------------------------
# - Start run
# - Start a prepared run only
# -----------------------------------------------------------
@router.post(
    "/start",
    response_model=RunOut,
    summary="Start run",
    description=(
        "Operational runtime endpoint. Start an existing prepared run only through the Route -> Run -> Stop -> Student workflow. "
        "A prepared run must already have stops and at least one runtime student assignment before start succeeds. "
        "At start time, the run driver is resolved from the single active route-driver assignment only. "
        "Primary/default assignment does not control runtime ownership by itself. "
        "This endpoint starts the run only and does not create stops, students, or StudentRunAssignment rows."
    ),
    response_description="Started run",
)
def start_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    target_run = _get_operator_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        "operate",
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        ],
    )

    if target_run.start_time is not None:
        raise HTTPException(status_code=400, detail="Run already started")

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=target_run.route_id,
        operator_id=operator.id,
        required_access="operate",
        options=[joinedload(route_model.Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )

    active_bus_id = route.active_bus_id or route.bus_id         # Active bus is authoritative; compatibility bus_id is fallback
    if active_bus_id is None:
        raise HTTPException(status_code=400, detail="Route has no active bus assigned")

    today_pretrip = (
        db.query(pretrip_model.PreTripInspection)
        .options(selectinload(pretrip_model.PreTripInspection.defects))
        .filter(pretrip_model.PreTripInspection.bus_id == active_bus_id)
        .filter(pretrip_model.PreTripInspection.inspection_date == date.today())
        .first()
    )  # Today's pre-trip for the resolved active bus only

    if not today_pretrip:
        create_missing_pretrip_alert_if_needed(
            db=db,
            bus_id=active_bus_id,
            route_id=route.id,
            run_id=target_run.id,
            scheduled_start_time=target_run.scheduled_start_time,
        )
        db.commit()                                             # Persist any missing-pretrip alert before returning the block response
        raise HTTPException(status_code=400, detail="No pre-trip found for active bus for today")

    if today_pretrip.fit_for_duty == "no":
        raise HTTPException(status_code=400, detail="Run blocked: driver marked not fit for duty")

    if any(defect.severity == "major" for defect in today_pretrip.defects):
        raise HTTPException(status_code=400, detail="Run blocked: major defect reported on pre-trip")

    resolved_driver_id = _resolve_run_driver(route)  # Resolve active driver at actual start time
    target_run.driver_id = resolved_driver_id        # Persist the current start-time driver on the run

    driver = db.get(driver_model.Driver, resolved_driver_id)  # Load resolved driver

    # -------------------------------------------------------------------------
    # Prevent driver from starting multiple active runs
    # -------------------------------------------------------------------------
    existing_active_run = (
        db.query(run_model.Run)
        .filter(run_model.Run.driver_id == resolved_driver_id)
        .filter(run_model.Run.start_time.is_not(None))
        .filter(run_model.Run.end_time.is_(None))
        .filter(run_model.Run.id != target_run.id)
        .first()
    )

    if existing_active_run:
        raise HTTPException(
            status_code=409,
            detail="Driver already has an active run"
        )

    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    # -------------------------------------------------------------------------
    # Require prepared stops before runtime start
    # -------------------------------------------------------------------------
    existing_stop_count = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == target_run.id)
        .count()
    )  # Determine whether this run already has its own stop plan

    if existing_stop_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Run has no stops. Prepare stops before starting the run."
        )

    # -------------------------------------------------------------------------
    # Require prepared runtime student assignments before runtime start
    # -------------------------------------------------------------------------
    existing_student_count = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == target_run.id)
        .count()
    )  # Determine whether this run already has runtime student assignments

    if existing_student_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Run has no students. Assign students before starting the run."
        )


    # -------------------------------------------------------------------------
    # Mark the selected run as started
    # -------------------------------------------------------------------------
    target_run.start_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Start timestamp
    target_run.current_stop_id = None                                        # Clear any stale planned location
    target_run.current_stop_sequence = None                                  # Reset live stop progress

    db.commit()               # Save started run only
    db.refresh(target_run)    # Reload saved run
    return _serialize_run(target_run)  # Return started run
# -----------------------------------------------------------
# - End run
# - End an active run by run id
# -----------------------------------------------------------
@router.post(
    "/end",
    response_model=schemas.RunOut,
    summary="End run",
    description="Operational runtime endpoint for ending one active run by run id.",
    response_description="Ended run",
)
def end_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")
    if run.start_time is None:
        raise HTTPException(status_code=400, detail="Run is not active")
    if run.end_time:
        raise HTTPException(status_code=400, detail="Run already ended")

    _require_posttrip_phase2_completed(run.id, db)             # Run cannot close until post-trip phase 2 is complete

    run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Set end timestamp
    db.commit()  # Save changes
    db.refresh(run)  # Reload updated run
    return run  # Return ended run

# -----------------------------------------------------------
# - End run by driver
# - End the newest active run for a specific driver
# -----------------------------------------------------------
@router.post(
    "/end_by_driver",
    response_model=schemas.RunOut,
    summary="End run by driver",
    description="Operational runtime endpoint for ending the newest active run for a specific driver.",
    response_description="Ended run",
)
def end_run_by_driver(
    driver_id: int,                         # Driver whose active run should be ended
    db: Session = Depends(get_db),          # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    driver = get_operator_scoped_record_or_404(
        db=db,
        model=driver_model.Driver,
        record_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                      # Query Run table
        .filter(run_model.Run.driver_id == driver_id)  # Only this driver
        .filter(run_model.Run.start_time.is_not(None))  # Only started runs
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .order_by(run_model.Run.start_time.desc())  # Newest active run first
        .first()
    )

    # -------------------------------------------------------------------------
    # Validate active run exists
    # -------------------------------------------------------------------------
    if not active_run:                              # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    _require_posttrip_phase2_completed(active_run.id, db)      # Run cannot close until post-trip phase 2 is complete

    # -------------------------------------------------------------------------
    # End the active run
    # -------------------------------------------------------------------------
    active_run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Set end timestamp

    db.commit()                                     # Save changes
    db.refresh(active_run)                          # Reload updated run

    return active_run                               # Return ended run

# -----------------------------------------------------------
# - List runs by route
# - Return only runs that belong to the selected route
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[RunListOut],
    summary="List runs",
    description="Return summary-level run data for one route only. route_id is required so operators stay inside a selected route context.",
    response_description="Run summary list",
)
def get_all_runs(
    route_id: int | None = Query(None),    # Required route filter
    db: Session = Depends(get_db),          # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate route filter exists
    # -------------------------------------------------------------------------
    if route_id is None:
        raise HTTPException(status_code=400, detail="route_id is required")  # Require route-scoped listing

    get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    # -------------------------------------------------------------------------
    # Load route runs in stable planning order
    # -------------------------------------------------------------------------
    runs = (
        db.query(run_model.Run)
        .options(
            joinedload(run_model.Run.driver),                   # Include driver label
            joinedload(run_model.Run.route),                    # Include route label
            selectinload(run_model.Run.stops),                  # Include stop counts
            selectinload(run_model.Run.student_assignments),    # Include student counts
        )
        .filter(run_model.Run.route_id == route_id)            # Keep only this route's runs
        .order_by(
            run_model.Run.start_time.desc(),                    # Show newest started runs first
            run_model.Run.id.desc(),                            # Keep planned/history ordering stable
        )
        .all()
    )                                                          # Load route runs

    return [_serialize_run_list_item(run) for run in runs]     # Return run summary list
# =============================================================================
# GET /runs/active
# Return the current active run for one driver
#
# Rules:
#   - driver_id is required
#   - active run = start_time IS NOT NULL and end_time IS NULL
#   - if no active run exists for that driver, return 404
#   - if multiple active runs exist, return the newest one
# =============================================================================
@router.get(
    "/active",
    response_model=schemas.RunOut,
    summary="Get active run",
    description="Operational runtime endpoint that returns the newest active run for the requested driver.",
    response_description="Active run",
)
def get_active_run(
    driver_id: int,                         # Driver to check for active run
    db: Session = Depends(get_db),          # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    get_operator_scoped_record_or_404(
        db=db,
        model=driver_model.Driver,
        record_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                      # Query Run table
        .filter(run_model.Run.driver_id == driver_id)  # Only this driver
        .filter(run_model.Run.start_time.is_not(None))  # Only started runs
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .order_by(run_model.Run.start_time.desc())  # Newest active run first
        .first()
    )

    # -------------------------------------------------------------------------
    # Return result or 404
    # -------------------------------------------------------------------------
    if not active_run:                              # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    return active_run                               # Return active run

# =============================================================================
# GET /runs/{run_id}/stops
# Return ordered stops for a specific run
#
# Ordering:
#   - sequence ascending
#   - id ascending
# =============================================================================
@router.get(
    "/{run_id}/stops",
    response_model=List[StopOut],
    summary="Get run stops",
    description="Return the prepared stop structure for a run ordered by sequence and id so drivers and operators can work inside the selected run context.",
    response_description="Ordered run stops",
)
def get_run_stops(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Load stops in stable order
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)   # Only stops for this run
        .order_by(
            stop_model.Stop.sequence.asc(),         # Primary stable order
            stop_model.Stop.id.asc(),               # Secondary stable order
        )
        .all()
    )

    return stops  # Return ordered stop list


# -----------------------------------------------------------
# Run-context stop creation
# Create a stop inside the selected run context
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops",
    response_model=StopOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create stop inside run",
    description="Create a stop inside the selected planned run context without sending run_id in the body. This is a setup workflow endpoint and is not available after the run has started.",
    response_description="Created stop",
)
def create_stop_inside_run(
    run_id: int,
    payload: RunStopCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time
    owner_run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    if owner_run.route and owner_run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")

    return stop_router.create_run_stop(                          # Reuse shared stop workflow rules
        run_id=run_id,                                          # Parent run context from path
        payload=payload,                                        # Context payload without run_id
        db=db,                                                  # Shared DB session
    )


# -----------------------------------------------------------
# Run-context stop update
# Update a stop inside the selected run context
# -----------------------------------------------------------
@router.put(
    "/{run_id}/stops/{stop_id}",
    response_model=StopOut,
    summary="Update stop inside run",
    description="Update a stop inside the selected planned run context without sending run_id again. This is a setup workflow endpoint and is not available after the run has started.",
    response_description="Updated stop",
)
def update_stop_inside_run(
    run_id: int,
    stop_id: int,
    payload: RunStopUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time
    owner_run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    if owner_run.route and owner_run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")

    return stop_router.update_run_stop(
        run_id=run_id,                                          # Parent run context from path
        stop_id=stop_id,                                        # Stop selected within that run
        payload=payload,                                        # Context payload without run_id
        db=db,                                                  # Shared DB session
    )


# -----------------------------------------------------------
# - Add one student from stop context
# - Create the student and internal runtime assignment together
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops/{stop_id}/students",
    response_model=schemas.StudentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add student to run stop",
    description="Create one student from planned run-stop context without repeating route_id, run_id, or stop_id in the body. This is a setup workflow endpoint and is not available after the run has started.",
    response_description="Created student",
)
def create_run_stop_student(
    run_id: int,
    stop_id: int,
    payload: schemas.StopStudentCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    owner_run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    if owner_run.route and owner_run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)  # Validate stop context once

    try:
        student = _create_stop_context_student(
            run=run,
            stop=stop,
            payload=payload,
            operator_id=operator.id,
            db=db,
        )
        db.commit()
        db.refresh(student)
        return student
    except IntegrityError as exc:
        db.rollback()
        raise_conflict_if_unique(
            db,
            exc,
            constraint_name="uq_student_run_assignment",
            sqlite_columns=("student_id", "run_id"),
            detail="Student is already assigned for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")


# -----------------------------------------------------------
# - Update one student from stop context
# - Keep student and assignment stop linkage aligned
# -----------------------------------------------------------
@router.put(
    "/{run_id}/stops/{stop_id}/students/{student_id}",
    response_model=schemas.StudentOut,
    summary="Update student inside run stop",
    description="Update a student from planned run-stop context without repeating run_id, stop_id, or student_id in the body. This is a setup workflow endpoint and is not available after the run has started.",
    response_description="Updated student",
)
def update_run_stop_student(
    run_id: int,
    stop_id: int,
    student_id: int,
    payload: schemas.StopStudentUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    from backend.routers import student as student_router  # Local import avoids circular import at module load time
    owner_run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    if owner_run.route and owner_run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")

    run, stop, student, assignment = _get_run_stop_student_context_or_404(
        run_id=run_id,
        stop_id=stop_id,
        student_id=student_id,
        db=db,
    )

    student = student_router._update_student_record(
        student=student,                                         # Existing routed student
        payload=payload,                                         # Context-safe update payload
        operator_id=operator.id,
        db=db,                                                   # Shared DB session
        authoritative_route_id=run.route_id,                     # Keep student on the run route
        authoritative_stop=stop,                                 # Keep planning stop aligned with path context
        assignment=assignment,                                   # Keep internal runtime assignment aligned too
    )
    db.commit()
    db.refresh(student)
    return student


# -----------------------------------------------------------
# - Remove one student from stop context
# - Delete only the selected runtime assignment for one planned run
# -----------------------------------------------------------
@router.delete(
    "/{run_id}/stops/{stop_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove student from run stop",
    description="Remove the student from the selected run-stop planning context without deleting the student record entirely. Planned run only.",
    response_description="Student removed from run stop",
)
def delete_run_stop_student(
    run_id: int,
    stop_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    owner_run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    if owner_run.route and owner_run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")
    run, stop, student, assignment = _get_run_stop_student_context_or_404(
        run_id=run_id,
        stop_id=stop_id,
        student_id=student_id,
        db=db,
    )

    db.delete(assignment)                                       # Remove only the selected run-scoped assignment row

    if student.route_id == run.route_id:
        student.route_id = None                                 # Clear route pointer when it still points at removed context

    if student.stop_id == stop.id:
        student.stop_id = None                                  # Clear stop pointer when it still points at removed context

    db.commit()
    return None


# -----------------------------------------------------------
# - Bulk add students from stop context
# - Create students and internal runtime assignments together
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops/{stop_id}/students/bulk",
    response_model=schemas.StopStudentBulkResult,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk add students to run stop",
    description="Create multiple students from planned run-stop context without repeating route_id, run_id, or stop_id in the body. This is a setup workflow endpoint and is not available after the run has started.",
    response_description="Bulk student creation summary",
)
def bulk_create_run_stop_students(
    run_id: int,
    stop_id: int,
    payload: schemas.StopStudentBulkCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    owner_run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    if owner_run.route and owner_run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)  # Validate stop context once

    created_students: list[Student] = []
    errors: list[schemas.StopStudentBulkError] = []

    for index, student_payload in enumerate(payload.students):
        try:
            with db.begin_nested():  # Keep one bad row from aborting the full batch
                student = _create_stop_context_student(
                    run=run,
                    stop=stop,
                    payload=student_payload,
                    operator_id=operator.id,
                    db=db,
                )
                created_students.append(student)
        except IntegrityError as exc:
            errors.append(
                schemas.StopStudentBulkError(
                    index=index,
                    name=student_payload.name,
                    detail="Student is already assigned for this run",
                )
            )
        except HTTPException as exc:
            errors.append(
                schemas.StopStudentBulkError(
                    index=index,
                    name=student_payload.name,
                    detail=exc.detail if isinstance(exc.detail, str) else "Unable to create student",
                )
            )

    db.commit()

    for student in created_students:
        db.refresh(student)

    return schemas.StopStudentBulkResult(
        created_count=len(created_students),
        skipped_count=len(errors),
        created_students=created_students,
        errors=errors,
    )


# -----------------------------------------------------------
# - Run action endpoints
# - Mutate live run state and runtime rider execution data
# -----------------------------------------------------------
# -----------------------------------------------------------
# - Arrive at stop
# - Mark actual runtime position with flexible stop movement
# -----------------------------------------------------------
@router.post(
    "/{run_id}/arrive_stop",
    response_model=schemas.RunOut,
    summary="Arrive at stop",
    description=(
        "Mark the run as arrived at an actual stop and update the live runtime location. "
        "Flexible stop execution is allowed: drivers may revisit earlier stops, jump ahead, or skip planned stops. "
        "Compatibility stop_sequence input remains supported, and optional stop_id may be used when available."
    ),
    response_description="Updated run state",
)
def arrive_at_stop(
    run_id: int,
    stop_sequence: int | None = Query(None, ge=1),  # Compatibility stop-sequence target
    stop_id: int | None = Query(None, ge=1),        # Optional explicit stop target for flexible movement
    db: Session = Depends(get_db),                  # Database session dependency
    operator: Operator = Depends(get_operator_context),
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    stop = _resolve_runtime_stop_target_or_404(
        run_id=run_id,
        stop_id=stop_id,
        stop_sequence=stop_sequence,
        db=db,
    )                                                          # Allow explicit jumps, revisits, and backward movement

    return _set_run_current_stop(run=run, stop=stop, db=db)

# =============================================================================
# POST /runs/{run_id}/next_stop
# -----------------------------------------------------------------------------
# Purpose:
#   Convenience helper for moving to the next configured stop in stable order.
#   Flexible execution still uses arrive_stop as the authoritative location
#   setter, including revisits, backward movement, and jumps.
# =============================================================================
@router.post(
    "/{run_id}/next_stop",
    response_model=schemas.RunOut,
    summary="Advance to next configured stop (compatibility helper)",
    description=(
        "Compatibility convenience helper that moves the active run to the next configured stop in ordered stop-list order. "
        "This endpoint does not enforce the overall execution model; drivers may still use POST /runs/{run_id}/arrive_stop "
        "to revisit earlier stops, jump ahead, skip stops, or otherwise reflect actual runtime location."
    ),
    response_description="Updated run state",
)
def advance_to_next_stop(
    run_id: int,
    db: Session = Depends(get_db),                  # Database session dependency
    operator: Operator = Depends(get_operator_context),
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    stops = _get_ordered_run_stops(run_id, db)      # Stable ordered list for convenience-only navigation

    if not stops:
        raise HTTPException(status_code=404, detail="No stops found for this run")

    if run.current_stop_id is None:
        next_stop = stops[0]                        # First convenience move starts at the first configured stop
    else:
        current_index = next(
            (index for index, stop in enumerate(stops) if stop.id == run.current_stop_id),
            None,
        )                                           # Resolve ordered position from the current actual stop id

        if current_index is None:
            next_stop = next(
                (
                    stop
                    for stop in stops
                    if run.current_stop_sequence is None or stop.sequence > run.current_stop_sequence
                ),
                None,
            )                                       # Conservative fallback if stored stop id is stale
        elif current_index + 1 < len(stops):
            next_stop = stops[current_index + 1]    # Move to the next configured stop in stable order
        else:
            next_stop = None                        # No later configured stop remains

    if not next_stop:
        raise HTTPException(status_code=404, detail="No next stop found for this run")

    return _set_run_current_stop(run=run, stop=next_stop, db=db)

# -----------------------------------------------------------
# - Pick up student
# - Record boarding at the run's current actual stop
# -----------------------------------------------------------
@router.post(
    "/{run_id}/pickup_student",
    response_model=PickupStudentResponse,
    summary="Pick up student",
    description=(
        "Mark a student as picked up at the run's current actual stop and log a PICKUP event. "
        "Rider actions follow the actual runtime location source of truth, not forward-only planned progression."
    ),
    response_description="Pickup confirmation",
)
def pickup_student(
    run_id: int,
    payload: PickupStudentRequest,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    current_stop = _require_current_runtime_stop(run, db)  # Pickup must happen at the actual current stop
    assignment = _get_runtime_assignment_or_404(
        run_id=run_id,
        student_id=payload.student_id,
        db=db,
    )

    # -------------------------------------------------------------------------
    # Validate pickup transition from current runtime rider state
    # -------------------------------------------------------------------------
    _assert_pickup_transition_allowed(assignment)

    # -------------------------------------------------------------------------
    # Mark pickup fields using the current actual stop
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)
    
    assignment.picked_up = True  # Student has boarded
    assignment.picked_up_at = now  # Store pickup time
    assignment.is_onboard = True  # Student is now physically on the bus
    assignment.actual_pickup_stop_id = current_stop.id  # Record the actual boarding stop

    # -----------------------------------------------------------
    # Log pickup event
    # - Records actual stop used for pickup
    # -----------------------------------------------------------
    event = RunEvent(
        run_id=run.id,
        stop_id=current_stop.id,
        student_id=assignment.student_id,
        event_type="PICKUP",
    )

    db.add(event)                                                           # Add event to current transaction
    # -------------------------------------------------------------------------
    # Save changes
    # -------------------------------------------------------------------------
    db.commit()  # Persist pickup state
    db.refresh(assignment)  # Reload updated assignment from DB

    # -------------------------------------------------------------------------
    # Return clean API response
    # -------------------------------------------------------------------------
    return PickupStudentResponse(
        message="Student picked up successfully",
        run_id=run.id,
        student_id=assignment.student_id,
        picked_up=assignment.picked_up,
        is_onboard=assignment.is_onboard,
        picked_up_at=assignment.picked_up_at,
    )

# -----------------------------------------------------------
# - Drop off student
# - Record drop-off at the run's current actual stop
# -----------------------------------------------------------
@router.post(
    "/{run_id}/dropoff_student",
    response_model=DropoffStudentResponse,
    summary="Drop off student",
    description=(
        "Mark a student as dropped off at the run's current actual stop and log a DROPOFF event. "
        "Rider actions follow the actual runtime location source of truth, not forward-only planned progression."
    ),
    response_description="Drop-off confirmation",
)
def dropoff_student(
    run_id: int,
    payload: DropoffStudentRequest,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    current_stop = _require_current_runtime_stop(run, db)  # Dropoff must happen at the actual current stop
    assignment = _get_runtime_assignment_or_404(
        run_id=run_id,
        student_id=payload.student_id,
        db=db,
    )

    # -------------------------------------------------------------------------
    # Validate dropoff transition from current runtime rider state
    # -------------------------------------------------------------------------
    _assert_dropoff_transition_allowed(assignment)

    # -------------------------------------------------------------------------
    # Mark drop-off fields using the current actual stop
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)

    assignment.dropped_off = True  # Student has been dropped off
    assignment.dropped_off_at = now  # Store drop-off time
    assignment.is_onboard = False  # Student is no longer on the bus
    assignment.actual_dropoff_stop_id = current_stop.id  # Record the actual drop-off stop

    # -----------------------------------------------------------
    # Log DROPOFF event
    # - Records actual stop used for dropoff
    # -----------------------------------------------------------
    event = RunEvent(                                                        # Build dropoff event
        run_id=run.id,                                                       # Parent run
        stop_id=current_stop.id,                                             # Actual dropoff stop
        student_id=assignment.student_id,                                    # Dropped-off student
        event_type="DROPOFF",                                                # Event type
    )
    db.add(event)                                                            # Add event to current transaction
    
    # -------------------------------------------------------------------------
    # Save changes
    # -------------------------------------------------------------------------
    db.commit()  # Persist drop-off state
    db.refresh(assignment)  # Reload updated assignment from DB

    # -------------------------------------------------------------------------
    # Return clean API response
    # -------------------------------------------------------------------------
    return DropoffStudentResponse(
        message="Student dropped off successfully",
        run_id=run.id,
        student_id=assignment.student_id,
        dropped_off=assignment.dropped_off,
        is_onboard=assignment.is_onboard,
        dropped_off_at=assignment.dropped_off_at,
    )

# -----------------------------------------------------------
# - Complete Run
# - Mark a run as finished and lock further action updates
# -----------------------------------------------------------
@router.post(
    "/{run_id}/complete",
    response_model=RunCompleteOut,
    summary="Complete run",
    description=(
        "Mark an active run as completed, close it, and create no-show events for riders not picked up. "
        "This preserves flexible runtime stop history while locking further live rider actions."
    ),
    response_description="Run completion status",
)
def complete_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")

    if not _is_run_active(run):  # Only active runs can be completed
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Prevent duplicate completion
    # -------------------------------------------------------------------------
    if run.is_completed:  # Run already finished
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is already completed",
        )

    # -------------------------------------------------------------------------
    # Mark completion fields
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC completion timestamp

    run.is_completed = True  # Lock run from further action updates
    run.completed_at = now  # Store completion time
    run.end_time = now  # Also close the run's end_time for summary/report use


    # -----------------------------------------------------------
    # Create automatic no-show events
    # - Students not picked up by completion time
    # -----------------------------------------------------------
    assignments = _get_run_assignments(run_id, db)                    # Load effective assignments for this run

    for assignment in assignments:
        if assignment.picked_up is True:                              # Skip students who boarded
            continue

        existing_no_show = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.student_id == assignment.student_id,
                RunEvent.event_type == "STUDENT_NO_SHOW",
            )
            .first()
        )

        if existing_no_show:
            continue                                                  # Prevent duplicate no-show events

        no_show_event = RunEvent(
            run_id=run.id,
            stop_id=assignment.stop_id,                               # Keep related stop if available
            student_id=assignment.student_id,
            event_type="STUDENT_NO_SHOW",
        )

        db.add(no_show_event)                                         # Store automatic no-show event

    
    # -------------------------------------------------------------------------
    # Save changes
    # -------------------------------------------------------------------------
    db.add(run)  # Track updated run
    db.commit()  # Persist completion state
    db.refresh(run)  # Reload final values

    # -------------------------------------------------------------------------
    # Return confirmation
    # -------------------------------------------------------------------------
    return RunCompleteOut(
        id=run.id,
        is_completed=run.is_completed,
        completed_at=run.completed_at,
        message="Run completed successfully",
    )

# -----------------------------------------------------------
# - Run view endpoints
# - Read and present live run state, summaries, and history views
# -----------------------------------------------------------
# -----------------------------------------------------------
# - Get run state
# - Return the current operational snapshot of a run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/state",
    response_model=RunStateOut,
    summary="Get run state",
    description=(
        "Return the current operational snapshot for a run, including the actual current runtime stop, "
        "flexible stop-progress interpretation, and rider counts."
    ),
    response_description="Current run state",
)
def get_run_state(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Load stops in stable order for current-stop and progress context
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .order_by(
            stop_model.Stop.sequence.asc(),
            stop_model.Stop.id.asc(),
        )
        .all()
    )
    stops_by_id = {stop.id: stop for stop in stops}  # Fast lookup by actual current stop ID

    # -------------------------------------------------------------------------
    # Load runtime assignments and reuse shared occupancy interpretation
    # -------------------------------------------------------------------------
    assignments = _get_run_assignments(run_id, db)
    occupancy_counts = _build_run_occupancy_counts(assignments)

    # -------------------------------------------------------------------------
    # Determine distinct arrived stops for flexible-progress reporting
    # -------------------------------------------------------------------------
    arrive_events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .filter(RunEvent.event_type == "ARRIVE")
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())
        .all()
    )
    arrived_stop_ids = {
        event.stop_id
        for event in arrive_events
        if event.stop_id is not None
    }  # Distinct actual stop visits, even if the bus revisits a stop later

    total_stops = len(stops)
    completed_stops = min(total_stops, len(arrived_stop_ids))  # Cap to configured stops for safety
    remaining_stops = max(0, total_stops - completed_stops)  # Never allow negative remaining stops

    if total_stops == 0:
        progress_percent = 0.0  # Avoid division by zero for runs with no stops
    else:
        progress_percent = round((completed_stops / total_stops) * 100, 1)  # Stable % from distinct arrivals
    progress_percent = max(0.0, min(100.0, progress_percent))  # Keep progress within valid bounds

    current_stop = stops_by_id.get(run.current_stop_id) if run.current_stop_id is not None else None

    # -------------------------------------------------------------------------
    # Return current run snapshot
    # -------------------------------------------------------------------------
    return RunStateOut(
        run_id=run.id,
        route_id=run.route_id,
        driver_id=run.driver_id,
        run_type=run.run_type,
        current_stop_id=run.current_stop_id,
        current_stop_sequence=run.current_stop_sequence,
        current_stop_name=current_stop.name if current_stop else None,
        total_stops=total_stops,
        completed_stops=completed_stops,
        remaining_stops=remaining_stops,
        progress_percent=progress_percent,
        total_assigned_students=occupancy_counts["total_assigned_students"],
        picked_up_students=occupancy_counts["total_picked_up"],
        dropped_off_students=occupancy_counts["total_dropped_off"],
        students_onboard=occupancy_counts["total_currently_onboard"],
        remaining_pickups=occupancy_counts["total_not_yet_boarded"],
        remaining_dropoffs=occupancy_counts["total_remaining_dropoffs"],
    )
# =============================================================================
# GET /runs/{run_id}/onboard_students
# -----------------------------------------------------------------------------
# Return all students currently onboard the bus for an active run.
#
# Purpose:
#   - allow drivers to see who is still on the bus
#   - allow dispatch to monitor live bus occupancy
#
# Data source:
#   StudentRunAssignment where:
#       run_id == run_id
#       is_onboard == True
#
# Students are returned ordered by stop sequence.
# =============================================================================
@router.get(
    "/{run_id}/onboard_students",
    response_model=OnboardStudentsResponse,
    summary="Get onboard students",
    description="Return students currently onboard the bus for an active run, ordered by stop sequence.",
    response_description="Onboard student list",
)
def get_onboard_students(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)
        .filter(run_model.Run.id == run_id)
        .first()
    )

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # -------------------------------------------------------------------------
    # Ensure run is active
    # -------------------------------------------------------------------------
    if run.start_time is None or run.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Load onboard assignments with related student + stop
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),
            joinedload(StudentRunAssignment.stop),
        )
        .filter(
            StudentRunAssignment.run_id == run_id,
            StudentRunAssignment.is_onboard == True,
        )
        .all()
    )

    # -------------------------------------------------------------------------
    # Sort students by stop sequence
    # -------------------------------------------------------------------------
    assignments.sort(key=lambda a: a.stop.sequence if a.stop else 0)

    # -------------------------------------------------------------------------
    # Build response items
    # -------------------------------------------------------------------------
    students = []

    for a in assignments:
        students.append(
            OnboardStudentItem(
                student_id=a.student.id,
                student_name=a.student.name,
                stop_id=a.stop.id,
                stop_name=a.stop.name,
                stop_sequence=a.stop.sequence,
                picked_up_at=a.picked_up_at,
            )
        )

    # -------------------------------------------------------------------------
    # Return structured response
    # -------------------------------------------------------------------------
    return OnboardStudentsResponse(
        run_id=run_id,
        total_onboard_students=len(students),
        students=students,
    )


# =============================================================================
# Get Run Occupancy Summary
# -----------------------------------------------------------------------------
# Purpose:
#   Return a quick student occupancy summary for one run.
#
# Summary includes:
#   - total assigned students
#   - total picked up
#   - total dropped off
#   - total currently onboard
#   - total not yet boarded
#
# Notes:
#   Runtime state is derived from StudentRunAssignment.
#   This keeps summary logic aligned with pickup/dropoff/onboard endpoints.
# =============================================================================
@router.get(
    "/{run_id}/occupancy_summary",
    response_model=RunOccupancySummaryResponse,
    summary="Get run occupancy summary",
    description="Return rider occupancy totals for one run based on runtime student assignments.",
    response_description="Run occupancy summary",
)
def get_run_occupancy_summary(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Load all runtime student assignments for this run
    # -------------------------------------------------------------------------
    assignments = _get_run_assignments(run_id, db)
    occupancy_counts = _build_run_occupancy_counts(assignments)

    # -------------------------------------------------------------------------
    # Return occupancy summary
    # -------------------------------------------------------------------------
    return RunOccupancySummaryResponse(
        run_id=run.id,
        route_id=run.route_id,
        run_type=run.run_type,
        total_assigned_students=occupancy_counts["total_assigned_students"],
        total_picked_up=occupancy_counts["total_picked_up"],
        total_dropped_off=occupancy_counts["total_dropped_off"],
        total_currently_onboard=occupancy_counts["total_currently_onboard"],
        total_not_yet_boarded=occupancy_counts["total_not_yet_boarded"],
    )


# =============================================================================
# GET /runs/{run_id}/timeline
# ---------------------------------------------------------------------------
# Purpose:
#   Return raw ordered ARRIVE / PICKUP / DROPOFF history for the run.
#
# Notes:
#   This stays separate from /state because timeline is a lossless event log,
#   not a current snapshot or interpreted admin view.
# =============================================================================
@router.get(
    "/{run_id}/timeline",
    response_model=RunTimelineOut,
    summary="Get run timeline",
    description=(
        "Return the raw ordered ARRIVE, PICKUP, and DROPOFF event history for a run. "
        "Repeated ARRIVE events are preserved when the driver revisits stops during flexible execution."
    ),
    response_description="Run timeline",
)
def get_run_timeline(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    events = (
        db.query(RunEvent)                                                # Query run events
        .filter(RunEvent.run_id == run_id)                                # Only this run
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())            # Stable oldest-first ordering
        .all()                                                            # Materialize list
    )

    return RunTimelineOut(                                                # Build timeline response
        run_id=run_id,                                                    # Parent run ID
        total_events=len(events),                                         # Event count
        events=events,                                                    # Ordered event rows
    )


# =============================================================================
# GET /runs/{run_id}/replay
# ---------------------------------------------------------------------------
# Purpose:
#   Return an interpreted human-readable history for admin/debug/report use.
#
# Notes:
#   This stays separate from /timeline because replay adds names, messages,
#   and occupancy interpretation on top of the raw event log.
# =============================================================================
@router.get(
    "/{run_id}/replay",
    response_model=RunReplayOut,
    summary="Get run replay",
    description=(
        "Return an interpreted event history for a run with readable messages and occupancy context. "
        "Flexible stop revisits and jumps are reflected from the underlying runtime event log."
    ),
    response_description="Run replay",
)
def get_run_replay(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Load all run events in stable chronological order
    # -------------------------------------------------------------------------
    raw_events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)  # Only events for this run
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())  # Stable time order
        .all()
    )

    # -------------------------------------------------------------------------
    # Build replay rows with readable context
    # -------------------------------------------------------------------------
    replay_events: list[RunReplayEventOut] = []  # Final replay rows
    onboard_count = 0  # Live bus occupancy during replay

    total_arrivals = 0  # Summary counter
    total_pickups = 0  # Summary counter
    total_dropoffs = 0  # Summary counter

    for event in raw_events:
        stop_name = None  # Default when stop is missing
        student_name = None  # Default when student is missing

        # ---------------------------------------------------------------------
        # Resolve stop context
        # ---------------------------------------------------------------------
        if event.stop_id is not None:
            stop = db.get(stop_model.Stop, event.stop_id)  # Load stop by ID
            stop_name = stop.name if stop else None  # Safe stop name

        # ---------------------------------------------------------------------
        # Resolve student context
        # ---------------------------------------------------------------------
        if event.student_id is not None:
            student = db.get(student_model.Student, event.student_id)  # Load student
            student_name = student.name if student else None  # Safe student name

        # ---------------------------------------------------------------------
        # Convert raw event into readable replay message
        # ---------------------------------------------------------------------
        if event.event_type == "ARRIVE":
            total_arrivals += 1  # Count arrival events

            if stop_name:
                message = f"Bus arrived at {stop_name}"  # Human-readable arrival
            elif event.stop_id is not None:
                message = f"Bus arrived at Stop {event.stop_id}"  # Fallback arrival
            else:
                message = "Bus arrived at an unknown stop"  # Safety fallback

        elif event.event_type == "PICKUP":
            total_pickups += 1  # Count pickup events
            onboard_count += 1  # Occupancy increases after pickup

            if student_name and stop_name:
                message = f"{student_name} picked up at {stop_name}"  # Full pickup message
            elif event.student_id is not None and stop_name:
                message = f"Student {event.student_id} picked up at {stop_name}"  # Partial fallback
            elif student_name and event.stop_id is not None:
                message = f"{student_name} picked up at Stop {event.stop_id}"  # Partial fallback
            else:
                message = "Student picked up"  # Safety fallback

        elif event.event_type == "DROPOFF":
            total_dropoffs += 1  # Count dropoff events
            onboard_count = max(0, onboard_count - 1)  # Never allow negative occupancy

            if student_name and stop_name:
                message = f"{student_name} dropped off at {stop_name}"  # Full dropoff message
            elif event.student_id is not None and stop_name:
                message = f"Student {event.student_id} dropped off at {stop_name}"  # Partial fallback
            elif student_name and event.stop_id is not None:
                message = f"{student_name} dropped off at Stop {event.stop_id}"  # Partial fallback
            else:
                message = "Student dropped off"  # Safety fallback

        else:
            message = f"Run event: {event.event_type}"  # Unknown/future event fallback

        # ---------------------------------------------------------------------
        # Save replay event row
        # ---------------------------------------------------------------------
        replay_events.append(
            RunReplayEventOut(
                id=event.id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                stop_id=event.stop_id,
                stop_name=stop_name,
                student_id=event.student_id,
                student_name=student_name,
                onboard_count=onboard_count,
                message=message,
            )
        )

    # -------------------------------------------------------------------------
    # Return replay response with summary
    # -------------------------------------------------------------------------
    return RunReplayOut(
        run_id=run.id,
        events=replay_events,
        summary=RunReplaySummaryOut(
            total_events=len(replay_events),
            total_arrivals=total_arrivals,
            total_pickups=total_pickups,
            total_dropoffs=total_dropoffs,
        ),
    )
# -----------------------------------------------------------
# - Get run detail
# - Return one run with nested route, stops, and students
# -----------------------------------------------------------
@router.get(
    "/{run_id}",
    response_model=RunDetailOut,
    summary="Get run detail",
    description="Return one run by id with nested route, driver, stop, and runtime student details.",
    response_description="Run detail",
)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run with linked route, stops, and student assignments
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        "read",
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
            selectinload(run_model.Run.stops),
            selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),
            selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),
        ],
    )

    # -------------------------------------------------------------------------
    # Return nested run detail response
    # -------------------------------------------------------------------------
    return _serialize_run_detail(run)                            # Return run detail


# -----------------------------------------------------------
# - Update planned run
# - Correct the run type before the run has started
# -----------------------------------------------------------
@router.put(
    "/{run_id}",
    response_model=schemas.RunOut,
    summary="Update planned run",
    description="Update the run type for a planned run that has not started yet.",
    response_description="Updated run",
)
def update_run(
    run_id: int,
    payload: RunUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run with linked driver and route
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        "read",
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        ],
    )
    if run.route and run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Only planned runs may be updated
    # -------------------------------------------------------------------------
    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be updated")

    _assert_unique_route_run_type(
        route_id=run.route_id,
        normalized_run_type=payload.run_type,
        db=db,
        exclude_run_id=run.id,
    )
    run.run_type = payload.run_type  # Allow correction of the planned run label only
    if payload.scheduled_start_time is not None:
        run.scheduled_start_time = payload.scheduled_start_time  # Allow correction of planned start time before start
    if payload.scheduled_end_time is not None:
        run.scheduled_end_time = payload.scheduled_end_time  # Allow correction of planned end time before start

    db.commit()
    db.refresh(run)
    return _serialize_run(run)


# -----------------------------------------------------------
# - Delete planned run
# - Remove a run only before it has started
# -----------------------------------------------------------
@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete planned run",
    description="Delete a planned run that has not started yet.",
    response_description="Run deleted",
)
def delete_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")
    if run.route and run.route.operator_id != operator.id:
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Only planned runs may be deleted
    # -------------------------------------------------------------------------
    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be deleted")

    db.delete(run)
    db.commit()
    return None


# -----------------------------------------------------------
# - Get running board
# - Return the operational running board for one run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/running_board",
    response_model=RunningBoardResponse,
    summary="Get running board",
    description="Operational runtime endpoint that returns the running board for a prepared run using runtime student assignments as the source of truth.",
    response_description="Running board",
)
def get_running_board(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load the run
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Load run stops ordered by sequence
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)  # Query Stop table
        .options(joinedload(stop_model.Stop.school))  # Load school names for school-stop display rows
        .filter(stop_model.Stop.run_id == run_id)  # Only stops belonging to this run
        .order_by(stop_model.Stop.sequence.asc())  # Ensure correct stop order
        .all()
    )

    # -------------------------------------------------------------------------
    # Load student assignments for this run
    # -------------------------------------------------------------------------
    assignments = apply_run_absence_filter((
        db.query(StudentRunAssignment)  # Query assignment table
        .options(joinedload(StudentRunAssignment.student))  # Load linked student
        .filter(StudentRunAssignment.run_id == run_id)  # Only this run
    ), run).all()  # Exclude planned absences from running board source data

    # -------------------------------------------------------------------------
    # Group assignments by stop
    # -------------------------------------------------------------------------
    assignments_by_stop = _group_running_board_students(assignments)  # Keep runtime assignments authoritative
    running_stops = _build_running_board_stops(stops, assignments_by_stop)  # Preserve existing board contract

    # -------------------------------------------------------------------------
    # Return full running board
    # -------------------------------------------------------------------------
    return RunningBoardResponse(
        run_id=run.id,  # Run identifier
        route_id=run.route_id,  # Parent route
        run_name=f"{run.route.route_number} {run.run_type}".strip() if run.route and run.route.route_number else run.run_type,  # Route-number display label
        total_stops=len(stops),  # Stop count
        total_assigned_students=len(assignments),  # Rider count
        stops=running_stops,  # Running board rows
    )

# -----------------------------------------------------------
# - Get run assignments
# - Return all effective student assignments for a specific run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/assignments",
    summary="Get run assignments",
    description="Return all effective runtime student assignments for a run with student and stop details. This is a read-only operational view, not the primary setup flow.",
    response_description="Run assignments",
)
def get_run_assignments(
    run_id: int,                         # Run identifier
    db: Session = Depends(get_db),        # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Load assignments with student and stop
    # -------------------------------------------------------------------------
    assignments = apply_run_absence_filter((
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),  # Load student
            joinedload(StudentRunAssignment.stop),     # Load stop
        )
        .filter(StudentRunAssignment.run_id == run_id)
    ), run).all()  # Exclude planned absences from run assignment output

    # -------------------------------------------------------------------------
    # Apply stable ordering in Python
    # -------------------------------------------------------------------------
    assignments.sort(
        key=lambda a: (
            a.stop.sequence if a.stop and a.stop.sequence is not None else 999999,  # Stop order
            a.id,                                                                   # Stable tie-breaker
        )
    )

    # -------------------------------------------------------------------------
    # Build response
    # -------------------------------------------------------------------------
    result = []

    for a in assignments:
        result.append({
            "student_id": a.student.id if a.student else None,
            "student_name": a.student.name if a.student else None,
            "stop_id": a.stop_id,
            "stop_name": a.stop.name if a.stop else None,
            "sequence": a.stop.sequence if a.stop else None,
            "run_type": run.run_type,  
        })

    return result

# -----------------------------------------------------------
# - Get run summary
# - Return a compact operational summary for one run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/summary",
    response_model=schemas.RunSummaryOut,
    summary="Get run summary",
    description="Operational runtime endpoint that returns a compact summary for one prepared run with driver, route, and rider totals.",
    response_description="Run summary",
)
def get_run_summary(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run with driver and route
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        "read",
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        ],
    )

    # -------------------------------------------------------------------------
    # Load run stops
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .all()
    )

    # -------------------------------------------------------------------------
    # Load student assignments
    # -------------------------------------------------------------------------
    assignments = apply_run_absence_filter((
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
    ), run).all()  # Exclude planned absences from summary counts
    occupancy_counts = _build_run_occupancy_counts(assignments)  # Reuse shared onboard/load counts

    # -------------------------------------------------------------------------
    # Determine run status
    # -------------------------------------------------------------------------
    if run.start_time is None:
        status = "planned"
    elif run.end_time is None:
        status = "active"
    else:
        status = "ended"

    # -------------------------------------------------------------------------
    # Compute current load
    # -------------------------------------------------------------------------
    current_load = occupancy_counts["total_currently_onboard"]  # Current load means students onboard now

    # -------------------------------------------------------------------------
    # Return summary
    # -------------------------------------------------------------------------
    return schemas.RunSummaryOut(
        run_id=run.id,
        driver_id=run.driver_id,
        driver_name=run.driver.name if run.driver else None,
        route_id=run.route_id,
        route_number=run.route.route_number if run.route else None,
        run_type=run.run_type,
        scheduled_start_time=run.scheduled_start_time,
        scheduled_end_time=run.scheduled_end_time,
        start_time=run.start_time,
        end_time=run.end_time,
        status=status,
        total_stops=len(stops),
        total_assigned_students=len(assignments),
        current_load=current_load,
    )

