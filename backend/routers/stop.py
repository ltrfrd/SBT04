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
from sqlalchemy import func                              # For MAX() query
from fastapi import HTTPException                        # For clean API errors
from backend.schemas.stop import StopCreate, StopOut
from backend.models.stop import Stop
# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/stops",  # All endpoints under /stops
    tags=["Stops"]    # Swagger group label
)

# -----------------------------------------------------------
# POST /stops → Create stop (auto sequence if missing)
# -----------------------------------------------------------
@router.post("/", response_model=StopOut, status_code=201)
def create_stop(payload: StopCreate, db: Session = Depends(get_db)):

    # -----------------------------------------------------------
    # Decide sequence (auto if missing)
    # -----------------------------------------------------------
    if payload.sequence is None:                                      # If client omitted sequence
        max_seq = (
            db.query(func.max(Stop.sequence))                         # SELECT MAX(sequence)
            .filter(Stop.route_id == payload.route_id)                # WHERE route_id = X
            .scalar()                                                 # Get single value
        )
        seq = (max_seq or 0) + 1                                      # Next sequence
    else:
        seq = payload.sequence                                        # Use provided sequence

    # -----------------------------------------------------------
    # Block duplicate sequence per route
    # -----------------------------------------------------------
    exists = (
        db.query(Stop)
        .filter(Stop.route_id == payload.route_id)                    # Same route
        .filter(Stop.sequence == seq)                                 # Same sequence
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Stop sequence already exists for this route")

    # -----------------------------------------------------------
    # Create stop record
    # -----------------------------------------------------------
    data = payload.model_dump()                                       # Convert to dict
    data["sequence"] = seq                                            # Force sequence value

    stop = Stop(**data)                                               # Build ORM object
    db.add(stop)                                                      # Add to session
    db.commit()                                                       # Save
    db.refresh(stop)                                                  # Reload
    return stop                                                       # Return created stop

    # -----------------------------------------------------------
    # Create stop record
    # -----------------------------------------------------------
    stop = Stop(**payload.model_dump())                  # Convert schema to dict
    db.add(stop)                                         # Add to session
    db.commit()                                          # Save changes
    db.refresh(stop)                                     # Reload with DB-generated id
    return stop                                          # Return created stop

# -----------------------------------------------------------
# GET /stops → List all stops
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.StopOut])
def get_stops(db: Session = Depends(get_db)):
    """Return all stops in the system."""
    return db.query(stop_model.Stop).all()

# -----------------------------------------------------------
# GET /stops → List stops (optionally filter by route_id)
# Always ordered by sequence ascending
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.StopOut])
def get_stops(route_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(stop_model.Stop)                         # Base query

    if route_id is not None:                                  # If filtering by route
        query = query.filter(stop_model.Stop.route_id == route_id)  # Apply route filter

    query = query.order_by(stop_model.Stop.sequence.asc())    # Ensure stops ordered by sequence

    return query.all()                                        # Return ordered results
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