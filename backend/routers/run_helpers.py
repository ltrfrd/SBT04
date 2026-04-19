# ===========================================================
# backend/routers/run_helpers.py - FleetOS Run Router Helpers
# -----------------------------------------------------------
# Shared internal helpers extracted from the run router.
# ===========================================================

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload, selectinload  # Used for eager loading relationships

from backend import schemas
from backend.models import posttrip as posttrip_model
from backend.models import route as route_model
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import StudentRunAssignment
from backend.models.run import Run                            # Run model
from backend.models.run_event import RunEvent                  # Run timeline event model
from backend.models.student import Student                      # Student model
from backend.schemas.run import (
    RunOut,
    RunDetailOut,
    RunDetailRouteOut,
    RunDetailDriverOut,
    RunDetailStopOut,
    RunDetailStudentOut,
    RunListOut,
    normalize_run_type,
)
from backend.schemas.run import (  # Running board response schemas
    RunningBoardStop,
    RunningBoardStudent,
)
from backend.utils.student_bus_absence import apply_run_absence_filter
from backend.utils.planning_scope import (
    EXECUTION_ROUTE_BLOCKED_DETAIL,
    get_route_for_execution_or_404,
    get_school_for_planning_or_404,
    validate_route_school_alignment,
)
from backend.utils.route_driver_assignment import resolve_route_driver_assignment
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.run_setup import get_run_stop_context_or_404


EXECUTION_RUN_BLOCKED_DETAIL = "Run is not executable because its route is not assigned to a yard for execution for this operator"


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


def _get_execution_scoped_run_or_404(
    run_id: int,
    db: Session,
    operator_id: int,
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

    try:
        get_route_for_execution_or_404(
            db=db,
            route_id=run.route_id,
            operator_id=operator_id,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN and exc.detail == EXECUTION_ROUTE_BLOCKED_DETAIL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=EXECUTION_RUN_BLOCKED_DETAIL,
            ) from exc
        raise
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


def _require_posttrip_phase1_and_phase2_completed(run_id: int, db: Session) -> None:
    inspection = (
        db.query(posttrip_model.PostTripInspection)
        .filter(posttrip_model.PostTripInspection.run_id == run_id)
        .first()
    )                                                          # One post-trip row may exist per run
    if (
        not inspection
        or inspection.phase1_completed is not True
        or inspection.phase2_completed is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post-trip phases 1 and 2 must be completed before completing the run",
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
    school = get_school_for_planning_or_404(
        db=db,
        school_id=payload.school_id,
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
    validate_route_school_alignment(
        route_district_id=route.district_id,
        route_operator_id=None,
        school=school,
    )

    student = Student(
        name=payload.name,
        grade=payload.grade,
        district_id=run.route.district_id if run.route else None,
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
