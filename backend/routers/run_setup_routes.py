# ===========================================================
# backend/routers/run_setup_routes.py - FleetOS Run Setup Router
# -----------------------------------------------------------
# Setup and workflow endpoints split from the main run router.
# ===========================================================

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from database import get_db

from backend import schemas
from backend.models import run as run_model
from backend.models.operator import Operator
from backend.models.student import Student
from backend.routers.reports import SchoolStatusUpdate
from backend.utils.db_errors import raise_conflict_if_unique
from backend.utils.operator_scope import get_operator_context
from backend.routers.run_helpers import (
    _create_stop_context_student,
    _get_operator_scoped_run_or_404,
    _get_run_stop_or_404,
    _get_run_stop_student_context_or_404,
)


router = APIRouter(tags=["Runs"])


def _raise_district_planning_path_retired() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Run planning mutations now belong to district-nested planning paths. "
            "Use /districts/{district_id}/routes/{route_id}/runs/{run_id}/... planning endpoints."
        ),
    )


def _create_stop_inside_run_internal(
    *,
    run_id: int,
    payload: schemas.RunStopCreate,
    db: Session,
    operator: Operator,
):
    from backend.routers import stop as stop_router

    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

    return stop_router.create_run_stop(
        run_id=run_id,
        payload=payload,
        db=db,
    )


def _update_stop_inside_run_internal(
    *,
    run_id: int,
    stop_id: int,
    payload: schemas.RunStopUpdate,
    db: Session,
    operator: Operator,
):
    from backend.routers import stop as stop_router

    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

    return stop_router.update_run_stop(
        run_id=run_id,
        stop_id=stop_id,
        payload=payload,
        db=db,
    )


def _update_run_student_school_status_internal(
    *,
    run_id: int,
    student_id: int,
    payload: SchoolStatusUpdate,
    db: Session,
    operator: Operator,
):
    from backend.routers import reports as reports_router

    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

    return reports_router.update_school_status_for_assignment(
        run_id=run_id,
        student_id=student_id,
        status_value=payload.status,
        db=db,
        operator=operator,
    )


def _create_run_stop_student_internal(
    *,
    run_id: int,
    stop_id: int,
    payload: schemas.StopStudentCreate,
    db: Session,
    operator: Operator,
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)

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


def _update_run_stop_student_internal(
    *,
    run_id: int,
    stop_id: int,
    student_id: int,
    payload: schemas.StopStudentUpdate,
    db: Session,
    operator: Operator,
):
    from backend.routers import student as student_router

    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)
    student = student_router._get_student_for_planning_or_404(
        db=db,
        operator_id=operator.id,
        detail="Student not found",
        student_id=student_id,
    )

    student = student_router._update_student_record(
        student=student,
        payload=payload,
        operator_id=operator.id,
        db=db,
        authoritative_route_id=run.route_id,
        authoritative_stop=stop,
    )
    route = student_router._get_route_with_schools(run.route_id, db, operator.id, "read")
    student_router._sync_student_assignment_rows_for_assignment_move(
        student=student,
        target_route=route,
        target_run=run,
        target_stop=stop,
        db=db,
    )
    db.commit()
    db.refresh(student)
    return student


def _delete_run_stop_student_internal(
    *,
    run_id: int,
    stop_id: int,
    student_id: int,
    db: Session,
    operator: Operator,
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    run, stop, student, assignment = _get_run_stop_student_context_or_404(
        run_id=run_id,
        stop_id=stop_id,
        student_id=student_id,
        db=db,
    )

    db.delete(assignment)

    if student.route_id == run.route_id:
        student.route_id = None

    if student.stop_id == stop.id:
        student.stop_id = None

    db.commit()
    return None


def _bulk_create_run_stop_students_internal(
    *,
    run_id: int,
    stop_id: int,
    payload: schemas.StopStudentBulkCreate,
    db: Session,
    operator: Operator,
):
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
    run, stop = _get_run_stop_or_404(run_id, stop_id, db)

    created_students: list[Student] = []
    errors: list[schemas.StopStudentBulkError] = []

    for index, student_payload in enumerate(payload.students):
        try:
            with db.begin_nested():
                student = _create_stop_context_student(
                    run=run,
                    stop=stop,
                    payload=student_payload,
                    operator_id=operator.id,
                    db=db,
                )
                created_students.append(student)
        except IntegrityError:
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
# Run-context stop creation
# Create a stop inside the selected run context
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops",
    response_model=schemas.StopOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Create stop inside run",
    description="Context-driven run helper for stop setup. Preferred primary stop creation workflow is POST /routes/{route_id}/runs/{run_id}/stops so route and run context stay explicit. This setup endpoint is not available after the run has started.",
    response_description="Created stop",
)
def create_stop_inside_run(
    run_id: int,
    payload: schemas.RunStopCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _create_stop_inside_run_internal(run_id=run_id, payload=payload, db=db, operator=operator)


# -----------------------------------------------------------
# Run-context stop update
# Update a stop inside the selected run context
# -----------------------------------------------------------
@router.put(
    "/{run_id}/stops/{stop_id}",
    response_model=schemas.StopOut,
    include_in_schema=False,
    summary="Update stop inside run",
    description="Update a stop inside the selected planned run context without sending run_id again. This is a setup workflow endpoint and is not available after the run has started.",
    response_description="Updated stop",
)
def update_stop_inside_run(
    run_id: int,
    stop_id: int,
    payload: schemas.RunStopUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _update_stop_inside_run_internal(run_id=run_id, stop_id=stop_id, payload=payload, db=db, operator=operator)


# -----------------------------------------------------------
# - Run-context school status update
# - Update school reports status from authoritative run and student path context
# -----------------------------------------------------------
@router.post(
    "/{run_id}/students/{student_id}/school-status",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    summary="Update school status inside run",
    description="Primary path-driven school status workflow. Update one assigned student's school status from run and student path context without sending internal IDs in the body.",
    response_description="School student status updated",
)
def update_run_student_school_status(
    run_id: int,
    student_id: int,
    payload: SchoolStatusUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _update_run_student_school_status_internal(run_id=run_id, student_id=student_id, payload=payload, db=db, operator=operator)


# -----------------------------------------------------------
# - Add one student from stop context
# - Create the student and internal runtime assignment together
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops/{stop_id}/students",
    response_model=schemas.StudentOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Add student to run stop",
    description="Primary path-driven student creation workflow. Create one student from planned run-stop context without repeating route_id, run_id, or stop_id in the body. This setup endpoint is not available after the run has started.",
    response_description="Created student",
)
def create_run_stop_student(
    run_id: int,
    stop_id: int,
    payload: schemas.StopStudentCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _create_run_stop_student_internal(run_id=run_id, stop_id=stop_id, payload=payload, db=db, operator=operator)


# -----------------------------------------------------------
# - Update one student from stop context
# - Keep student and assignment stop linkage aligned
# -----------------------------------------------------------
@router.put(
    "/{run_id}/stops/{stop_id}/students/{student_id}",
    response_model=schemas.StudentOut,
    include_in_schema=False,
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
    _raise_district_planning_path_retired()
    return _update_run_stop_student_internal(
        run_id=run_id,
        stop_id=stop_id,
        student_id=student_id,
        payload=payload,
        db=db,
        operator=operator,
    )


# -----------------------------------------------------------
# - Remove one student from stop context
# - Delete only the selected runtime assignment for one planned run
# -----------------------------------------------------------
@router.delete(
    "/{run_id}/stops/{stop_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
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
    _raise_district_planning_path_retired()
    return _delete_run_stop_student_internal(run_id=run_id, stop_id=stop_id, student_id=student_id, db=db, operator=operator)


# -----------------------------------------------------------
# - Bulk add students from stop context
# - Create students and internal runtime assignments together
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops/{stop_id}/students/bulk",
    response_model=schemas.StopStudentBulkResult,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Bulk add students to run stop",
    description="Primary bulk student creation workflow for run-stop context. Create multiple students without repeating route_id, run_id, or stop_id in the body. This setup endpoint is not available after the run has started.",
    response_description="Bulk student creation summary",
)
def bulk_create_run_stop_students(
    run_id: int,
    stop_id: int,
    payload: schemas.StopStudentBulkCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _bulk_create_run_stop_students_internal(run_id=run_id, stop_id=stop_id, payload=payload, db=db, operator=operator)
