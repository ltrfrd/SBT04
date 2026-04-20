from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from backend import schemas
from backend.models import route as route_model
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import StudentRunAssignment
from backend.models.run import Run
from backend.models.student import Student
from backend.schemas.run import normalize_run_type
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import (
    get_school_for_planning_or_404,
    validate_route_school_alignment,
)
from backend.utils.route_driver_assignment import resolve_route_driver_assignment
from backend.utils.run_setup import get_run_stop_context_or_404


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


def _get_run_stop_or_404(run_id: int, stop_id: int, db: Session) -> tuple[run_model.Run, stop_model.Stop]:
    return get_run_stop_context_or_404(
        run_id=run_id,
        stop_id=stop_id,
        db=db,
        require_planned=True,
    )


def _get_run_stop_student_context_or_404(
    run_id: int,
    stop_id: int,
    student_id: int,
    db: Session,
) -> tuple[run_model.Run, stop_model.Stop, student_model.Student, StudentRunAssignment]:
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)

    student = db.get(student_model.Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.route_id != run.route_id:
        raise HTTPException(status_code=400, detail="Student does not belong to run route")

    assignment = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .filter(StudentRunAssignment.student_id == student_id)
        .first()
    )
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
    )
    db.add(student)
    db.flush()

    db.add(
        StudentRunAssignment(
            student_id=student.id,
            run_id=run.id,
            stop_id=stop.id,
        )
    )
    db.flush()

    db.refresh(student)
    return student


def _resolve_planned_run_driver(route) -> int | None:
    try:
        assignment = resolve_route_driver_assignment(route)
    except ValueError as exc:
        if str(exc) == "Route has no active driver assignment":
            return None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return assignment.driver_id


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
    normalized_run_type = normalize_run_type(run_type)
    _assert_unique_route_run_type(
        route_id=route.id,
        normalized_run_type=normalized_run_type,
        db=db,
    )
    resolved_driver_id = _resolve_planned_run_driver(route)

    new_run = run_model.Run(
        driver_id=resolved_driver_id,
        route_id=route.id,
        district_id=route.district_id,
        run_type=normalized_run_type,
        scheduled_start_time=scheduled_start_time,
        scheduled_end_time=scheduled_end_time,
        start_time=None,
        end_time=None,
        current_stop_id=None,
        current_stop_sequence=None,
    )
    db.add(new_run)
    return new_run
