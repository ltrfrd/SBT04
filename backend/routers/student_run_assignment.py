# ===========================================================
# backend/routers/student_run_assignment.py - BST Student Run Assignment Router
# -----------------------------------------------------------
# Manage explicit runtime student-to-run assignment records.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from backend.models.associations import StudentRunAssignment
from backend.models import student as student_model
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.schemas.student_run_assignment import (
    StudentRunAssignmentCreate,
    StudentRunAssignmentOut,
)
from backend.utils.db_errors import raise_conflict_if_unique
from backend.utils.student_bus_absence import has_student_bus_absence

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(prefix="/student-run-assignments", tags=["StudentRunAssignments"])


# -----------------------------------------------------------
# - Create student run assignment
# - Assign a student to a run and stop
# -----------------------------------------------------------
@router.post(
    "/",
    response_model=StudentRunAssignmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create student run assignment",
    description="Create a student run assignment for a specific run and stop.",
    response_description="Created student run assignment",
)
def create_assignment(payload: StudentRunAssignmentCreate, db: Session = Depends(get_db)):
    student = db.get(student_model.Student, payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    run = db.get(run_model.Run, payload.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    stop = db.get(stop_model.Stop, payload.stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")

    if stop.run_id != payload.run_id:
        raise HTTPException(status_code=400, detail="Stop does not belong to run")

    if has_student_bus_absence(payload.student_id, run, db):
        raise HTTPException(status_code=409, detail="Student has a planned bus absence for this run")  # Do not create effective assignments for absent students

    try:
        assignment = StudentRunAssignment(**payload.model_dump())
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return assignment
    except IntegrityError as e:
        db.rollback()
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_student_run_assignment",
            sqlite_columns=("student_id", "run_id"),
            detail="Student is already assigned for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")

# -----------------------------------------------------------
# - List student run assignments
# - Return assignments with optional run and student filters
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[StudentRunAssignmentOut],
    summary="List student run assignments",
    description="Return student run assignments with optional run and student filters.",
    response_description="Student run assignment list",
)
def list_assignments(
    run_id: int | None = None,
    student_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(StudentRunAssignment)
    if run_id is not None:
        query = query.filter(StudentRunAssignment.run_id == run_id)
    if student_id is not None:
        query = query.filter(StudentRunAssignment.student_id == student_id)
    return query.all()

# -----------------------------------------------------------
# - Delete student run assignment
# - Remove one assignment by id
# -----------------------------------------------------------
@router.delete(
    "/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete student run assignment",
    description="Delete a student run assignment by id.",
    response_description="Student run assignment deleted",
)
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    assignment = db.get(StudentRunAssignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment)
    db.commit()
    return None
