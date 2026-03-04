# ===========================================================
# backend/routers/school.py — BST School Router
# -----------------------------------------------------------
# Handles CRUD operations for schools and links them to routes.
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI tools
from sqlalchemy.orm import Session  # DB session type
from typing import List  # Type hint
from database import get_db  # DB dependency
from backend import schemas  # Pydantic schemas
from backend.models import school as school_model  # School model
from backend.models import route as route_model  # Route model (for linking)

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/schools",  # All endpoints under /schools
    tags=["Schools"],  # Swagger category label
)


# -----------------------------------------------------------
# CREATE: Add new school
# -----------------------------------------------------------
@router.post("/", response_model=schemas.SchoolOut, status_code=status.HTTP_201_CREATED)
def create_school(school: schemas.SchoolCreate, db: Session = Depends(get_db)):
    """Add a new school record to the database."""
    new_school = school_model.School(**school.model_dump())  # Convert schema → model
    db.add(new_school)
    db.commit()
    db.refresh(new_school)
    return new_school


# -----------------------------------------------------------
# READ: Get all schools
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.SchoolOut])
def get_schools(db: Session = Depends(get_db)):
    """Return a list of all registered schools."""
    return db.query(school_model.School).all()


# -----------------------------------------------------------
# READ: Get single school by ID
# -----------------------------------------------------------
@router.get("/{school_id}", response_model=schemas.SchoolOut)
def get_school(school_id: int, db: Session = Depends(get_db)):
    """Retrieve one school by its unique ID."""
    school = db.get(school_model.School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return school


# -----------------------------------------------------------
# UPDATE: Modify school information
# -----------------------------------------------------------
@router.put("/{school_id}", response_model=schemas.SchoolOut)
def update_school(
    school_id: int, school_in: schemas.SchoolCreate, db: Session = Depends(get_db)
):
    """Update school details (name, address, phone)."""
    school = db.get(school_model.School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    for key, value in school_in.model_dump().items():  # Update dynamic fields
        setattr(school, key, value)
    db.commit()
    db.refresh(school)
    return school


# -----------------------------------------------------------
# DELETE: Remove school
# -----------------------------------------------------------
@router.delete("/{school_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_school(school_id: int, db: Session = Depends(get_db)):
    """Delete a school record from the system."""
    school = db.get(school_model.School, school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    db.delete(school)
    db.commit()
    return None


# -----------------------------------------------------------
# ACTION: Link school to route
# -----------------------------------------------------------
@router.post("/{school_id}/assign_route/{route_id}", response_model=schemas.SchoolOut)
def assign_route_to_school(
    school_id: int, route_id: int, db: Session = Depends(get_db)
):
    """Link an existing school to a route (many-to-many)."""
    school = db.get(school_model.School, school_id)
    route = db.get(route_model.Route, route_id)
    if not school or not route:
        raise HTTPException(status_code=404, detail="School or Route not found")
    if route not in school.routes:  # Prevent duplicate links
        school.routes.append(route)
        db.commit()
        db.refresh(school)
    return school


# -----------------------------------------------------------
# ACTION: Unlink school from route
# -----------------------------------------------------------
@router.delete(
    "/{school_id}/unassign_route/{route_id}", response_model=schemas.SchoolOut
)
def unassign_route_from_school(
    school_id: int, route_id: int, db: Session = Depends(get_db)
):
    """Remove a route association from a school."""
    school = db.get(school_model.School, school_id)
    route = db.get(route_model.Route, route_id)
    if not school or not route:
        raise HTTPException(status_code=404, detail="School or Route not found")
    if route in school.routes:  # Only remove if linked
        school.routes.remove(route)
        db.commit()
        db.refresh(school)
    return school
