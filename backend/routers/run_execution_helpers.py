from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from backend.models import posttrip as posttrip_model
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import StudentRunAssignment
from backend.models.run import Run
from backend.models.run_event import RunEvent
from backend.schemas.run import (
    RunDetailDriverOut,
    RunDetailOut,
    RunDetailRouteOut,
    RunDetailStopOut,
    RunDetailStudentOut,
    RunListOut,
    RunOut,
    RunningBoardStop,
    RunningBoardStudent,
)
from backend.utils.planning_scope import (
    EXECUTION_ROUTE_BLOCKED_DETAIL,
    get_route_for_execution_or_404,
)
from backend.utils.route_driver_assignment import resolve_route_driver_assignment
from backend.utils.student_bus_absence import apply_run_absence_filter


EXECUTION_RUN_BLOCKED_DETAIL = "Run is not executable because its route is not assigned to a yard for execution for this operator"


def _get_run_or_404(run_id: int, db: Session) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
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
    run = _get_run_or_404(run_id, db)
    query = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
    )
    return apply_run_absence_filter(query, run).all()


def _build_run_occupancy_counts(assignments: list[StudentRunAssignment]) -> dict[str, int]:
    total_assigned_students = len(assignments)
    total_picked_up = sum(1 for assignment in assignments if assignment.picked_up)
    total_dropped_off = sum(1 for assignment in assignments if assignment.dropped_off)
    total_currently_onboard = sum(1 for assignment in assignments if assignment.is_onboard)
    total_not_yet_boarded = sum(1 for assignment in assignments if not assignment.picked_up)
    total_remaining_dropoffs = sum(
        1
        for assignment in assignments
        if assignment.picked_up and not assignment.dropped_off
    )

    return {
        "total_assigned_students": total_assigned_students,
        "total_picked_up": total_picked_up,
        "total_dropped_off": total_dropped_off,
        "total_currently_onboard": total_currently_onboard,
        "total_not_yet_boarded": total_not_yet_boarded,
        "total_remaining_dropoffs": total_remaining_dropoffs,
    }


def _require_posttrip_phase1_and_phase2_completed(run_id: int, db: Session) -> None:
    inspection = (
        db.query(posttrip_model.PostTripInspection)
        .filter(posttrip_model.PostTripInspection.run_id == run_id)
        .first()
    )
    if (
        not inspection
        or inspection.phase1_completed is not True
        or inspection.phase2_completed is not True
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post-trip phases 1 and 2 must be completed before completing the run",
        )


def _get_runtime_run_or_404(run_id: int, db: Session) -> Run:
    run = db.get(run_model.Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _require_active_runtime_run(run: Run) -> Run:
    if run.is_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is already completed",
        )

    if run.start_time is None:
        raise HTTPException(status_code=400, detail="Run is not active")

    if run.end_time is not None:
        raise HTTPException(status_code=400, detail="Run has already ended")

    return run


def _get_ordered_run_stops(run_id: int, db: Session) -> list[stop_model.Stop]:
    return (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .order_by(stop_model.Stop.sequence.asc(), stop_model.Stop.id.asc())
        .all()
    )


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
        )
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found for this run")

    if stop_sequence is not None:
        sequence_stop = (
            db.query(stop_model.Stop)
            .filter(stop_model.Stop.run_id == run_id)
            .filter(stop_model.Stop.sequence == stop_sequence)
            .first()
        )
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
    run.current_stop_id = stop.id
    run.current_stop_sequence = stop.sequence

    db.add(
        RunEvent(
            run_id=run.id,
            stop_id=stop.id,
            event_type="ARRIVE",
        )
    )

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
    )
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
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student is not assigned to this run",
        )

    return assignment


def _assert_pickup_transition_allowed(assignment: StudentRunAssignment) -> None:
    if assignment.dropped_off is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been dropped off",
        )

    if assignment.picked_up is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been picked up",
        )

    if assignment.is_onboard is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is already onboard",
        )


def _assert_dropoff_transition_allowed(assignment: StudentRunAssignment) -> None:
    if assignment.dropped_off is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been dropped off",
        )

    if assignment.picked_up is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has not been picked up yet",
        )

    if assignment.is_onboard is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is not currently onboard",
        )


def _group_running_board_students(
    assignments: list[StudentRunAssignment],
) -> dict[int, list[RunningBoardStudent]]:
    assignments_by_stop: dict[int, list[RunningBoardStudent]] = {}

    for assignment in assignments:
        if assignment.stop_id is None or not assignment.student:
            continue

        assignments_by_stop.setdefault(
            assignment.stop_id,
            [],
        ).append(
            RunningBoardStudent(
                student_id=assignment.student.id,
                student_name=assignment.student.name,
            )
        )

    return assignments_by_stop


def _build_running_board_stops(
    stops: list[stop_model.Stop],
    assignments_by_stop: dict[int, list[RunningBoardStudent]],
) -> list[RunningBoardStop]:
    running_stops: list[RunningBoardStop] = []
    cumulative_load = 0

    for stop in stops:
        stop_students = assignments_by_stop.get(stop.id, [])
        student_count = len(stop_students)
        load_change = student_count
        cumulative_load += load_change

        is_school_stop = stop.type in {"SCHOOL_ARRIVE", "SCHOOL_DEPART"}
        if is_school_stop and stop.school:
            display_name = stop.school.name
        else:
            display_name = stop.name or f"STOP {stop.sequence}"

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


def _resolve_run_driver(route):
    try:
        assignment = resolve_route_driver_assignment(route)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return assignment.driver_id


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


def _serialize_run_detail(run: run_model.Run) -> RunDetailOut:
    ordered_stops = sorted(
        run.stops,
        key=lambda stop: (
            stop.sequence if stop.sequence is not None else 999999,
            stop.id,
        ),
    )

    ordered_assignments = sorted(
        run.student_assignments,
        key=lambda assignment: (
            assignment.stop.sequence if assignment.stop and assignment.stop.sequence is not None else 999999,
            assignment.student.name if assignment.student else "",
            assignment.id,
        ),
    )

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
    )


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
    )
