# ===========================================================
# backend/routers/stop.py — BST Stop Router
# -----------------------------------------------------------
# Handles CRUD for bus stops (pickup/dropoff) per route.
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI imports
from sqlalchemy.orm import Session  # SQLAlchemy session
from typing import List  # For type hinting lists
from database import get_db  # DB dependency
from backend import schemas  # Stop schemas
from backend.models import stop as stop_model  # Stop model
from backend.models import route as route_model  # Route model (FK validation)

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/stops",  # All endpoints under /stops
    tags=["Stops"]    # Swagger group label
)

# -----------------------------------------------------------
# POST /stops → Create new stop
# -----------------------------------------------------------
@router.post("/", response_model=schemas.StopOut, status_code=status.HTTP_201_CREATED)
def create_stop(stop: schemas.StopCreate, db: Session = Depends(get_db)):
    """Add a new stop to a specific route."""
    # Validate route existence
    route = db.get(route_model.Route, stop.route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    # Create stop record
    new_stop = stop_model.Stop(**stop.model_dump())
    db.add(new_stop)
    db.commit()
    db.refresh(new_stop)
    return new_stop

# -----------------------------------------------------------
# GET /stops → List all stops
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.StopOut])
def get_stops(db: Session = Depends(get_db)):
    """Return all stops in the system."""
    return db.query(stop_model.Stop).all()

# -----------------------------------------------------------
# GET /stops/{stop_id} → Fetch single stop
# -----------------------------------------------------------
@router.get("/{stop_id}", response_model=schemas.StopOut)
def get_stop(stop_id: int, db: Session = Depends(get_db)):
    """Retrieve one stop by ID."""
    stop = db.get(stop_model.Stop, stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    return stop

# -----------------------------------------------------------
# PUT /stops/{stop_id} → Update stop info
# -----------------------------------------------------------
@router.put("/{stop_id}", response_model=schemas.StopOut)
def update_stop(stop_id: int, stop_in: schemas.StopUpdate, db: Session = Depends(get_db)):
    stop = db.get(stop_model.Stop, stop_id)                      # Load stop from DB
    if not stop:                                                 # If stop does not exist
        raise HTTPException(status_code=404, detail="Stop not found")

    updates = stop_in.model_dump(exclude_none=True)              # Only apply provided fields
    for key, value in updates.items():                           # Loop through fields
        setattr(stop, key, value)                                # Update stop attributes

    db.commit()                                                  # Save changes
    db.refresh(stop)                                             # Refresh instance
    return stop                                                  # Return updated stop
# -----------------------------------------------------------
# DELETE /stops/{stop_id} → Remove stop
# -----------------------------------------------------------
@router.delete("/{stop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stop(stop_id: int, db: Session = Depends(get_db)):
    """Delete a stop record."""
    stop = db.get(stop_model.Stop, stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    db.delete(stop)
    db.commit()
    return None