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
# - Get run assignments
# - Return all student assignments for one run
# -----------------------------------------------------------
@router.get(
    "/{run_id}",
    response_model=List[StudentRunAssignmentOut],
    summary="Get run assignments",
    description="Return all student assignments for one run.",
    response_description="Student run assignments for the run",
)
def get_run_assignments(
    run_id: int,
    db: Session = Depends(get_db),
):
    run = db.get(run_model.Run, run_id)                          # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")  # Validate run exists

    assignments = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .order_by(StudentRunAssignment.id.asc())
        .all()
    )                                                            # Load run assignments

    return assignments                                           # Return assignment list


# -----------------------------------------------------------
# - List student assignments
# - Return assignments for one student across runs
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[StudentRunAssignmentOut],
    summary="List student assignments",
    description="Return student run assignments for one student. student_id is required.",
    response_description="Student run assignment list for the student",
)
def list_assignments(
    student_id: int | None = None,
    db: Session = Depends(get_db),
):
    if student_id is None:
        raise HTTPException(status_code=400, detail="student_id is required")  # Require student-scoped lookup

    student = db.get(student_model.Student, student_id)         # Load student
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")  # Validate student exists

    assignments = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.student_id == student_id)
        .order_by(StudentRunAssignment.id.asc())
        .all()
    )                                                            # Load student assignments

    return assignments                                           # Return assignment list

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
