# ===========================================================
# backend/routers/student.py — BST Student Router
# -----------------------------------------------------------
# Handles CRUD operations for students and route/school lookups.
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI core imports
from sqlalchemy.orm import Session  # For DB access
from sqlalchemy.orm import selectinload  # Eager-load route schools for validation
from typing import List  # For list responses

from database import get_db  # DB dependency
from backend import schemas  # Pydantic schemas
from backend.models import student as student_model  # Student model
from backend.models import school as school_model  # School validation
from backend.models import route as route_model  # Route validation
from backend.models import stop as stop_model  # Stop validation
from backend.models import associations as assoc_model  # Run assignment mapping
from backend.models import run as run_model  # Route->run join


# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/students",                                          # Base path
    tags=["Students"],                                           # Swagger section
)


# -----------------------------------------------------------
# - Student workflow helpers
# - Reuse validation and synchronization across update paths
# -----------------------------------------------------------
def _get_route_with_schools(route_id: int, db: Session) -> route_model.Route:
    route = (
        db.query(route_model.Route)
        .options(selectinload(route_model.Route.schools))
        .filter(route_model.Route.id == route_id)
        .first()
    )                                                           # Load route and assigned schools once
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


def _validate_route_school_membership(route: route_model.Route, school_id: int) -> None:
    route_school_ids = {school.id for school in route.schools}   # Keep school validation aligned with stop-context create flow
    if school_id not in route_school_ids:
        raise HTTPException(status_code=400, detail="School is not assigned to the run route")


def _get_stop_or_404(stop_id: int, db: Session) -> stop_model.Stop:
    stop = db.get(stop_model.Stop, stop_id)                      # Load stop once for route/assignment workflows
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    return stop


def _validate_compatibility_student_create_target(
    *,
    school_id: int,
    route_id: int | None,
    stop_id: int | None,
    db: Session,
) -> tuple[route_model.Route | None, stop_model.Stop | None]:
    route = _get_route_with_schools(route_id, db) if route_id is not None else None
    stop = _get_stop_or_404(stop_id, db) if stop_id is not None else None

    if stop is not None:
        run = stop.run                                           # Resolve stop hierarchy only when stop compatibility pointer is present
        if run is None:
            raise HTTPException(status_code=400, detail="Stop does not belong to route")

        if route is not None and run.route_id != route.id:
            raise HTTPException(status_code=400, detail="Stop does not belong to route")

        if route is None:
            route = _get_route_with_schools(run.route_id, db)    # Infer stop route for validation only

    return route, stop


def _validate_student_assignment_target(
    *,
    student: student_model.Student,
    route_id: int,
    run_id: int,
    stop_id: int,
    db: Session,
) -> tuple[route_model.Route, run_model.Run, stop_model.Stop]:
    route = _get_route_with_schools(route_id, db)                # Validate target route first
    run = db.get(run_model.Run, run_id)                          # Validate target run exists
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    stop = _get_stop_or_404(stop_id, db)                         # Validate target stop exists

    if run.route_id != route.id:
        raise HTTPException(status_code=400, detail="Run does not belong to route")

    if stop.run_id != run.id:
        raise HTTPException(status_code=400, detail="Stop does not belong to run")

    if run.end_time is not None or run.is_completed:
        raise HTTPException(status_code=400, detail="Run is completed")

    _validate_route_school_membership(route, student.school_id)  # Keep school-route safety

    return route, run, stop


def _sync_student_assignment_rows_for_assignment_move(
    *,
    student: student_model.Student,
    target_route: route_model.Route,
    target_run: run_model.Run,
    target_stop: stop_model.Stop,
    db: Session,
) -> None:
    assignments = (
        db.query(assoc_model.StudentRunAssignment)
        .join(run_model.Run, assoc_model.StudentRunAssignment.run_id == run_model.Run.id)
        .filter(assoc_model.StudentRunAssignment.student_id == student.id)
        .all()
    )                                                           # Load runtime rows once so movement stays synchronized

    target_assignment = None

    for assignment in assignments:
        run = assignment.run
        is_historical = run.end_time is not None or run.is_completed

        if assignment.run_id == target_run.id:
            target_assignment = assignment                       # Reuse existing target-run row when it exists

        if is_historical:
            continue                                            # Preserve completed runtime truth

        if run.route_id != target_route.id:
            db.delete(assignment)                               # Remove current/planned rows on other routes to avoid drift

    if target_assignment is None:
        target_assignment = assoc_model.StudentRunAssignment(
            student_id=student.id,
            run_id=target_run.id,
            stop_id=target_stop.id,
        )                                                       # Create planning/runtime row for the newly selected stop context
        db.add(target_assignment)
    else:
        target_assignment.stop_id = target_stop.id              # Repoint existing target-run row to the selected stop

    db.flush()


def _update_student_record(
    *,
    student: student_model.Student,
    payload: schemas.StopStudentUpdate,
    db: Session,
    authoritative_route_id: int | None = None,
    authoritative_stop: stop_model.Stop | None = None,
    assignment: assoc_model.StudentRunAssignment | None = None,
):
    updates = payload.model_dump(exclude_unset=True)             # Preserve partial-update compatibility

    target_route_id = authoritative_route_id if authoritative_route_id is not None else updates.get("route_id", student.route_id)
    target_stop_id = authoritative_stop.id if authoritative_stop is not None else updates.get("stop_id", student.stop_id)
    target_school_id = updates.get("school_id", student.school_id)

    route = None
    if target_route_id is not None:
        route = _get_route_with_schools(target_route_id, db)     # Needed for route-aware school validation

    school = db.get(school_model.School, target_school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    if route is not None:
        _validate_route_school_membership(route, target_school_id)

    stop = None
    if target_stop_id is not None:
        stop = db.get(stop_model.Stop, target_stop_id)
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")

    if route is not None and stop is not None and stop.run and stop.run.route_id != route.id:
        raise HTTPException(status_code=400, detail="Stop does not belong to route")

    # -----------------------------------------------------------
    # - Apply editable student fields
    # - Keep run-stop context authoritative for student field edits
    # -----------------------------------------------------------
    for field_name in ("name", "grade", "school_id"):
        if field_name in updates:
            setattr(student, field_name, updates[field_name])

    if authoritative_route_id is not None:
        student.route_id = authoritative_route_id                # Context route is authoritative

    if authoritative_stop is not None:
        student.stop_id = authoritative_stop.id                  # Context stop is authoritative

    if assignment is not None and authoritative_stop is not None:
        assignment.stop_id = authoritative_stop.id               # Keep StudentRunAssignment aligned with stop context

    db.flush()
    db.refresh(student)
    return student

# -----------------------------------------------------------
# - Create student
# - Register a student through the compatibility path
# - Preserve direct-create support while stop-context is preferred
# -----------------------------------------------------------
@router.post(
    "/",                                                         # Endpoint path
    response_model=schemas.StudentOut,                           # Response schema
    status_code=status.HTTP_201_CREATED,                         # HTTP 201 on success
    summary="Create student (secondary compatibility)",          # Swagger title
    description=(
        "Secondary compatibility endpoint for creating a student record directly. "
        "Preferred layered workflow is POST /runs/{run_id}/stops/{stop_id}/students so route and stop context are inherited automatically. "
        "Optional route_id and stop_id fields are legacy planning pointers for compatibility only."
    ),                                                           # Swagger description
    response_description="Created student",                      # Swagger response text
)
def create_student(student: schemas.StudentCompatibilityCreate, db: Session = Depends(get_db)):
    """Add a new student. Runtime run/stop mapping is managed in StudentRunAssignment."""  # Internal docstring
    school = db.get(school_model.School, student.school_id)      # Validate school exists
    if not school:
        raise HTTPException(status_code=404, detail="School not found")  # Return 404 when missing

    _validate_compatibility_student_create_target(
        school_id=student.school_id,                             # Compatibility create still anchors on a real school
        route_id=student.route_id,                               # Optional legacy planning route pointer
        stop_id=student.stop_id,                                 # Optional legacy planning stop pointer
        db=db,                                                   # Shared DB session
    )

    new_student = student_model.Student(**student.model_dump())  # Convert schema → DB model
    db.add(new_student)                                          # Add to session
    db.commit()                                                  # Persist to DB
    db.refresh(new_student)                                      # Reload with DB values
    return new_student                                           # Return created record


# -----------------------------------------------------------
# - List students
# - Return all registered student records
# -----------------------------------------------------------
@router.get(
    "/",                                                         # Endpoint path
    response_model=List[schemas.StudentOut],                     # Response schema
    summary="List students",                                     # Swagger title
    description="Return all registered student records.",        # Swagger description
    response_description="Student list",                         # Swagger response text
)
def get_students(db: Session = Depends(get_db)):
    """Return all students in the system."""                     # Internal docstring
    return db.query(student_model.Student).all()                 # Fetch and return all students


# -----------------------------------------------------------
# - Get student by id
# - Return a single student record
# -----------------------------------------------------------
@router.get(
    "/{student_id}",                                             # Endpoint path with student id
    response_model=schemas.StudentOut,                           # Response schema
    summary="Get student",                                       # Swagger title
    description="Return a single student record by id.",         # Swagger description
    response_description="Student record",                       # Swagger response text
)
def get_student(student_id: int, db: Session = Depends(get_db)):
    """Fetch student by ID."""                                   # Internal docstring
    student = db.get(student_model.Student, student_id)          # Load one student by primary key
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")  # Return 404 when missing
    return student                                               # Return matching student


# -----------------------------------------------------------
# - Update student assignment
# - Move a student to a different route and stop safely
# -----------------------------------------------------------
@router.put(
    "/{student_id}/assignment",
    response_model=schemas.StudentOut,
    summary="Update student assignment (maintenance)",
    description=(
        "Maintenance endpoint for correcting or moving a student to a different route, run, and stop after initial setup. "
        "This is not the normal creation workflow; preferred initial setup is POST /runs/{run_id}/stops/{stop_id}/students. "
        "Runtime assignment rows are synchronized safely when the move is valid."
    ),
    response_description="Updated student assignment",
)
def update_student_assignment(
    student_id: int,
    assignment_in: schemas.StudentAssignmentUpdate,
    db: Session = Depends(get_db),
):
    student = db.get(student_model.Student, student_id)          # Validate student exists
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    target_route, target_run, target_stop = _validate_student_assignment_target(
        student=student,
        route_id=assignment_in.route_id,
        run_id=assignment_in.run_id,
        stop_id=assignment_in.stop_id,
        db=db,
    )

    student.route_id = target_route.id                           # Update legacy planning route pointer
    student.stop_id = target_stop.id                             # Update legacy planning stop pointer

    _sync_student_assignment_rows_for_assignment_move(
        student=student,
        target_route=target_route,
        target_run=target_run,
        target_stop=target_stop,
        db=db,
    )

    db.commit()
    db.refresh(student)
    return student


# -----------------------------------------------------------
# - Delete student
# - Remove a student record from the system
# -----------------------------------------------------------
@router.delete(
    "/{student_id}",                                             # Endpoint path with student id
    status_code=status.HTTP_204_NO_CONTENT,                      # HTTP 204 on success
    summary="Delete student",                                    # Swagger title
    description="Delete a student record by id.",                # Swagger description
    response_description="Student deleted",                      # Swagger response text
)
def delete_student(student_id: int, db: Session = Depends(get_db)):
    """Delete a student record."""                               # Internal docstring
    student = db.get(student_model.Student, student_id)          # Load student by primary key
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")  # Return 404 when missing
    db.delete(student)                                           # Remove student from session
    db.commit()                                                  # Persist deletion
    return None                                                  # Return empty 204 response


# -----------------------------------------------------------
# - List students by school
# - Return students linked to one school
# -----------------------------------------------------------
@router.get(
    "/school/{school_id}",                                       # Endpoint path with school id
    response_model=List[schemas.StudentOut],                     # Response schema
    summary="List students by school",                           # Swagger title
    description="Return all students belonging to one school.",  # Swagger description
    response_description="Student list for school",              # Swagger response text
)
def get_students_by_school(school_id: int, db: Session = Depends(get_db)):
    """List all students belonging to a specific school."""      # Internal docstring
    school = db.get(school_model.School, school_id)              # Validate school exists
    if not school:
        raise HTTPException(status_code=404, detail="School not found")  # Return 404 when missing

    return (
        db.query(student_model.Student)                          # Start student query
        .filter(student_model.Student.school_id == school_id)    # Filter by school id
        .all()                                                   # Return matching students
    )


# -----------------------------------------------------------
# - List students by route
# - Return students assigned to runs on one route
# -----------------------------------------------------------
@router.get(
    "/route/{route_id}",                                         # Endpoint path with route id
    response_model=List[schemas.StudentOut],                     # Response schema
    summary="List students by route",                            # Swagger title
    description="Return students with at least one run assignment on the selected route.",  # Swagger description
    response_description="Student list for route",               # Swagger response text
)
def get_students_by_route(route_id: int, db: Session = Depends(get_db)):
    """List students with at least one run assignment on this route."""  # Internal docstring
    route = db.get(route_model.Route, route_id)                  # Validate route exists
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")  # Return 404 when missing

    return (
        db.query(student_model.Student)                          # Start student query
        .join(
            assoc_model.StudentRunAssignment,                    # Join runtime student assignments
            assoc_model.StudentRunAssignment.student_id == student_model.Student.id,  # Match student ids
        )
        .join(
            run_model.Run,                                       # Join runs
            run_model.Run.id == assoc_model.StudentRunAssignment.run_id,  # Match run ids
        )
        .filter(run_model.Run.route_id == route_id)              # Filter by route id
        .distinct()                                              # Avoid duplicate students
        .all()                                                   # Return matching students
    )
