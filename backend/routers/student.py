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

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/students", tags=["Students"]  # Base path  # Swagger section
)


# -----------------------------------------------------------
# POST /students → Create new student
# -----------------------------------------------------------
@router.post(
    "/", response_model=schemas.StudentOut, status_code=status.HTTP_201_CREATED
)
def create_student(student: schemas.StudentCreate, db: Session = Depends(get_db)):
    """Add a new student and link to school, route, and stop."""
    # Validate school
    school = db.get(school_model.School, student.school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    # Optional: validate route
    if student.route_id:
        route = db.get(route_model.Route, student.route_id)
        if not route:
            raise HTTPException(status_code=404, detail="Route not found")
    # Optional: validate stop
    if student.stop_id:
        stop = db.get(stop_model.Stop, student.stop_id)
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")
    # Create record
    new_student = student_model.Student(**student.model_dump())
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


# -----------------------------------------------------------
# GET /students → Get all students
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.StudentOut])
def get_students(db: Session = Depends(get_db)):
    """Return all students in the system."""
    return db.query(student_model.Student).all()


# -----------------------------------------------------------
# GET /students/{student_id} → Get one student
# -----------------------------------------------------------
@router.get("/{student_id}", response_model=schemas.StudentOut)
def get_student(student_id: int, db: Session = Depends(get_db)):
    """Fetch student by ID."""
    student = db.get(student_model.Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


# -----------------------------------------------------------
# PUT /students/{student_id} → Update student info
# -----------------------------------------------------------
@router.put("/{student_id}", response_model=schemas.StudentOut)
def update_student(
    student_id: int, student_in: schemas.StudentCreate, db: Session = Depends(get_db)
):
    """Update student details or reassign route/stop."""
    student = db.get(student_model.Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    for key, value in student_in.model_dump().items():  # Apply updates field-by-field
        setattr(student, key, value)
    db.commit()
    db.refresh(student)
    return student


# -----------------------------------------------------------
# DELETE /students/{student_id} → Remove student
# -----------------------------------------------------------
@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(student_id: int, db: Session = Depends(get_db)):
    """Delete a student record."""
    student = db.get(student_model.Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    db.delete(student)
    db.commit()
    return None


# -----------------------------------------------------------
# GET /students/school/{school_id} → List by school
# -----------------------------------------------------------
@router.get("/school/{school_id}", response_model=List[schemas.StudentOut])
def get_students_by_school(school_id: int, db: Session = Depends(get_db)):
    """List all students belonging to a specific school."""
    school = db.get(school_model.School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return (
        db.query(student_model.Student)
        .filter(student_model.Student.school_id == school_id)
        .all()
    )


# -----------------------------------------------------------
# GET /students/route/{route_id} → List by route
# -----------------------------------------------------------
@router.get("/route/{route_id}", response_model=List[schemas.StudentOut])
def get_students_by_route(route_id: int, db: Session = Depends(get_db)):
    """List all students assigned to a given route."""
    route = db.get(route_model.Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return (
        db.query(student_model.Student)
        .filter(student_model.Student.route_id == route_id)
        .all()
    )
