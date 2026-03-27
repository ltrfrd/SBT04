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
# - Create school
# - Register a new school in the system
# -----------------------------------------------------------
@router.post(
    "/",                                                        # Endpoint path
    response_model=schemas.SchoolOut,                           # Response schema
    status_code=status.HTTP_201_CREATED,                        # HTTP 201 on success
    summary="Create school",                                   # Swagger title
    description="Create a new school record.",                 # Swagger description
    response_description="Created school",                     # Swagger response text
)
def create_school(school: schemas.SchoolCreate, db: Session = Depends(get_db)):
    """Add a new school record to the database."""              # Internal docstring
    new_school = school_model.School(**school.model_dump())     # Convert schema → DB model
    db.add(new_school)                                         # Add to session
    db.commit()                                                # Persist to DB
    db.refresh(new_school)                                     # Reload with DB values
    return new_school                                          # Return created record

# -----------------------------------------------------------
# - List schools
# - Return all registered school records
# -----------------------------------------------------------
@router.get(
    "/",                                                        # Endpoint path
    response_model=List[schemas.SchoolOut],                     # Response schema (list of schools)
    summary="List schools",                                    # Swagger title
    description="Return all registered school records.",       # Swagger description
    response_description="School list",                        # Swagger response text
)
def get_schools(db: Session = Depends(get_db)):
    return db.query(school_model.School).all()                 # Fetch and return all school records

# -----------------------------------------------------------
# - Get school by id
# - Return a single school record
# -----------------------------------------------------------
@router.get(
    "/{school_id}",                                             # Endpoint path with school id
    response_model=schemas.SchoolOut,                           # Response schema
    summary="Get school",                                       # Swagger title
    description="Return a single school record by id.",         # Swagger description
    response_description="School record",                       # Swagger response text
)
def get_school(school_id: int, db: Session = Depends(get_db)):
    school = db.get(school_model.School, school_id)             # Load one school by primary key
    if not school:
        raise HTTPException(status_code=404, detail="School not found")  # Return 404 when missing
    return school                                               # Return the matching school record

# -----------------------------------------------------------
# - Update school
# - Modify an existing school record
# -----------------------------------------------------------
@router.put(
    "/{school_id}",                                             # Endpoint path with school id
    response_model=schemas.SchoolOut,                           # Response schema
    summary="Update school",                                    # Swagger title
    description="Update an existing school record by id.",      # Swagger description
    response_description="Updated school",                      # Swagger response text
)
def update_school(
    school_id: int, school_in: schemas.SchoolCreate, db: Session = Depends(get_db)
):
    school = db.get(school_model.School, school_id)             # Load existing school
    if not school:
        raise HTTPException(status_code=404, detail="School not found")  # Return 404 if missing

    update_data = school_in.model_dump(exclude_unset=True)      # Extract only provided fields
    for key, value in update_data.items():
        setattr(school, key, value)                            # Apply updates dynamically

    db.commit()                                                # Save changes
    db.refresh(school)                                         # Reload updated record
    return school                                              # Return updated school
# -----------------------------------------------------------
# - Delete school
# - Remove a school record from the system
# -----------------------------------------------------------
@router.delete(
    "/{school_id}",                                             # Endpoint path with school id
    status_code=status.HTTP_204_NO_CONTENT,                     # HTTP 204 on success
    summary="Delete school",                                    # Swagger title
    description="Delete a school record by id.",                # Swagger description
    response_description="School deleted",                      # Swagger response text
)
def delete_school(school_id: int, db: Session = Depends(get_db)):
    school = db.get(school_model.School, school_id)             # Load school by primary key
    if not school:
        raise HTTPException(status_code=404, detail="School not found")  # Return 404 if missing
    db.delete(school)                                           # Remove school from session
    db.commit()                                                 # Persist deletion
    return None                                                 # Return empty 204 response


# -----------------------------------------------------------
# - Assign route to school
# - Link a school with a route (many-to-many)
# -----------------------------------------------------------
@router.post(
    "/{school_id}/assign_route/{route_id}",                    # Endpoint path with school + route ids
    response_model=schemas.SchoolOut,                          # Response schema
    summary="Assign route to school",                          # Swagger title
    description="Link a school to a route. Prevents duplicate assignments.",  # Swagger description
    response_description="Updated school with route link",     # Swagger response text
)
def assign_route_to_school(
    school_id: int, route_id: int, db: Session = Depends(get_db)
):
    """Link an existing school to a route (many-to-many)."""   # Internal docstring
    school = db.get(school_model.School, school_id)             # Load school
    route = db.get(route_model.Route, route_id)                 # Load route
    if not school or not route:
        raise HTTPException(status_code=404, detail="School or Route not found")  # Validate existence

    if route not in school.routes:                              # Prevent duplicate links
        school.routes.append(route)                             # Attach route to school
        db.commit()                                             # Persist change
        db.refresh(school)                                      # Reload updated object

    return school                                               # Return updated school

# -----------------------------------------------------------
# - Unassign route from school
# - Remove a school-to-route link
# -----------------------------------------------------------
@router.delete(
    "/{school_id}/unassign_route/{route_id}",                  # Endpoint path with school + route ids
    response_model=schemas.SchoolOut,                          # Response schema
    summary="Unassign route from school",                      # Swagger title
    description="Remove the link between a school and a route.",  # Swagger description
    response_description="Updated school without route link",  # Swagger response text
)
def unassign_route_from_school(
    school_id: int, route_id: int, db: Session = Depends(get_db)
):
    """Remove a route association from a school."""            # Internal docstring
    school = db.get(school_model.School, school_id)            # Load school
    route = db.get(route_model.Route, route_id)                # Load route
    if not school or not route:
        raise HTTPException(status_code=404, detail="School or Route not found")  # Validate existence

    if route in school.routes:                                 # Only remove when linked
        school.routes.remove(route)                            # Detach route from school
        db.commit()                                            # Persist change
        db.refresh(school)                                     # Reload updated object

    return school                                              # Return updated school