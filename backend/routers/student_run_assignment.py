# ===========================================================
# backend/routers/student_run_assignment.py - BST Student Run Assignment Router
# -----------------------------------------------------------
# Expose read-only compatibility views for runtime assignment rows.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from backend.models.operator import Operator
from backend.models.associations import StudentRunAssignment
from backend.models import student as student_model
from backend.models import run as run_model
from backend.schemas.student_run_assignment import (
    StudentRunAssignmentCreate,
    StudentRunAssignmentOut,
)
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_record_or_404
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import get_student_for_planning_or_404

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
    status_code=status.HTTP_410_GONE,
    summary="Create student run assignment (disabled)",
    description=(
        "Direct raw StudentRunAssignment creation is retired. "
        "Canonical workflow-first placement is "
        "POST /districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students."
    ),
    response_description="Direct create blocked",
    include_in_schema=False,
)
def create_assignment(payload: StudentRunAssignmentCreate, db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Direct student run assignment creation is retired. "
            "Use POST /districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students."
        ),
    )

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
    operator: Operator = Depends(get_operator_context),
):
    run = db.get(run_model.Run, run_id)                          # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")  # Validate run exists
    get_operator_scoped_route_or_404(
        db=db,
        route_id=run.route_id,
        operator_id=operator.id,
        required_access="read",
    )

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
    operator: Operator = Depends(get_operator_context),
):
    if student_id is None:
        raise HTTPException(status_code=400, detail="student_id is required")  # Require student-scoped lookup

    student = get_student_for_planning_or_404(
        db=db,
        operator_id=operator.id,
        detail="Student not found",
        student_id=student_id,
    )

    assignments = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.student_id == student_id)
        .order_by(StudentRunAssignment.id.asc())
        .all()
    )                                                            # Load student assignments

    return assignments                                           # Return assignment list
# -----------------------------------------------------------
# - Delete assignment (blocked)
# - Prevent direct deletion to preserve stop-context integrity
# -----------------------------------------------------------
@router.delete(
    "/{assignment_id}",
    status_code=status.HTTP_410_GONE,
    summary="Delete student run assignment (disabled)",
    description=(
        "Direct assignment deletion is retired. "
        "Use the canonical contextual delete endpoint "
        "DELETE /districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students/{student_id}."
    ),
    response_description="Direct delete blocked",
    include_in_schema=False,
)
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Direct assignment deletion is retired. "
            "Use DELETE /districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students/{student_id}."
        ),
    )

