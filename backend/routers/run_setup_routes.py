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


# -----------------------------------------------------------
# Run-context stop creation
# Create a stop inside the selected run context
# -----------------------------------------------------------
@router.post(
    "/{run_id}/stops",
    response_model=schemas.StopOut,
    status_code=status.HTTP_201_CREATED,
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
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

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
    response_model=schemas.StopOut,
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
    from backend.routers import stop as stop_router  # Local import avoids circular import at module load time
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

    return stop_router.update_run_stop(
        run_id=run_id,                                          # Parent run context from path
        stop_id=stop_id,                                        # Stop selected within that run
        payload=payload,                                        # Context payload without run_id
        db=db,                                                  # Shared DB session
    )


# -----------------------------------------------------------
# - Run-context school status update
# - Update school reports status from authoritative run and student path context
# -----------------------------------------------------------
@router.post(
    "/{run_id}/students/{student_id}/school-status",
    status_code=status.HTTP_200_OK,
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
    from backend.routers import reports as reports_router  # Local import avoids circular import at module load time

    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

    return reports_router.update_school_status_for_assignment(
        run_id=run_id,
        student_id=student_id,
        status_value=payload.status,
        db=db,
        operator=operator,
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
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
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
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])

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
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
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
    _get_operator_scoped_run_or_404(run_id, db, operator.id, "read", options=[joinedload(run_model.Run.route)])
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
