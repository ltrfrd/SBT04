# ===========================================================
# backend/routers/student.py — BST Student Router
# -----------------------------------------------------------
# Handles CRUD operations for students and route/school lookups.
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI core imports
from sqlalchemy.orm import Session  # For DB access
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
# - Create student
# - Register a new student in the system
# -----------------------------------------------------------
@router.post(
    "/",                                                         # Endpoint path
    response_model=schemas.StudentOut,                           # Response schema
    status_code=status.HTTP_201_CREATED,                         # HTTP 201 on success
    summary="Create student",                                    # Swagger title
    description="Create a new student record. School is required; route and stop are optional.",  # Swagger description
    response_description="Created student",                      # Swagger response text
)
def create_student(student: schemas.StudentCreate, db: Session = Depends(get_db)):
    """Add a new student. Runtime run/stop mapping is managed in StudentRunAssignment."""  # Internal docstring
    school = db.get(school_model.School, student.school_id)      # Validate school exists
    if not school:
        raise HTTPException(status_code=404, detail="School not found")  # Return 404 when missing

    if student.route_id:
        route = db.get(route_model.Route, student.route_id)      # Validate optional route
        if not route:
            raise HTTPException(status_code=404, detail="Route not found")  # Return 404 when missing

    if student.stop_id:
        stop = db.get(stop_model.Stop, student.stop_id)          # Validate optional stop
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")  # Return 404 when missing

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
# - Update student
# - Modify an existing student record
# -----------------------------------------------------------
@router.put(
    "/{student_id}",                                             # Endpoint path with student id
    response_model=schemas.StudentOut,                           # Response schema
    summary="Update student",                                    # Swagger title
    description="Update an existing student record by id.",      # Swagger description
    response_description="Updated student",                      # Swagger response text
)
def update_student(
    student_id: int,                                             # Student identifier
    student_in: schemas.StudentCreate,                           # Incoming update payload
    db: Session = Depends(get_db),                               # DB session dependency
):
    """Update student profile fields. Runtime run assignment is managed elsewhere."""  # Internal docstring
    student = db.get(student_model.Student, student_id)          # Load existing student
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")  # Return 404 when missing

    for key, value in student_in.model_dump().items():           # Apply updates field-by-field
        setattr(student, key, value)                             # Set each updated attribute

    db.commit()                                                  # Persist changes
    db.refresh(student)                                          # Reload updated record
    return student                                               # Return updated student


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