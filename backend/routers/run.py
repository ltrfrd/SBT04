# ============================================================
# Run router for BusTrack operational workflows
# ============================================================

# -----------------------------
# Imports
# -----------------------------

# -----------------------------
# Router / Model / Schema
# -----------------------------

# -----------------------------
# Logic
# -----------------------------

# =============================================================================
# backend/routers/run.py — SBT02 Run Router
# -----------------------------------------------------------------------------
# Responsibilities:
#   - Create runs
#   - Start and end runs
#   - List runs with optional filters
#   - Return one run by ID
#   - Return ordered stops for a run
#   - Return running board data for a run
#
# Data model notes:
#   - Route -> Runs
#   - Run -> Stops
#   - Runtime rider mapping uses StudentRunAssignment
#   - Legacy student.route_id and student.stop_id are NOT the source of truth
#     for running board logic
# =============================================================================

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload  # Used for eager loading relationships
from database import get_db
from backend import schemas
from backend.models import run as run_model
from backend.models import driver as driver_model
from backend.models import route as route_model
from backend.models import stop as stop_model
from backend.models.run import Run                            # Run model
from backend.models.associations import StudentRunAssignment  # Runtime rider assignments
from backend.schemas.run import RunStart, RunOut
from backend.models.run_event import RunEvent                  # Run timeline event model
from backend.models import student as student_model  # Student model for replay names
from backend.schemas.run import RunReplayOut, RunReplayEventOut, RunReplaySummaryOut
from backend.schemas.run import RunTimelineOut                 # Timeline response schema
from backend.schemas.stop import StopOut
from backend.schemas.run import (  # Running board response schemas
    RunningBoardResponse,
    RunningBoardStop,
    RunningBoardStudent,
)
from backend.schemas.run import (
    PickupStudentRequest,
    PickupStudentResponse,
    DropoffStudentRequest,
    DropoffStudentResponse,
    OnboardStudentsResponse,
    OnboardStudentItem,
    RunOccupancySummaryResponse,
)
router = APIRouter(prefix="/runs", tags=["Runs"])


# =============================================================================
# POST /runs/
# Create a run directly
# =============================================================================
@router.post("/", response_model=schemas.RunOut, status_code=status.HTTP_201_CREATED)
def create_run(run: RunStart, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, run.driver_id)  # Validate driver exists
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    route = db.get(route_model.Route, run.route_id)  # Validate route exists
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

        # -------------------------------------------------------------------------
    # Prevent driver from having multiple active runs
    # -------------------------------------------------------------------------
    existing_active_run = (
        db.query(run_model.Run)                      # Query Run table
        .filter(run_model.Run.driver_id == run.driver_id)  # Same driver
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .first()
    )

    if existing_active_run:                         # If active run already exists
        raise HTTPException(
            status_code=409,
            detail="Driver already has an active run"
        )
    new_run = run_model.Run(
        **run.model_dump(),  # Copy input payload fields
        start_time=datetime.now(timezone.utc).replace(tzinfo=None),  # Store naive UTC
        current_stop_id=None,  # Start with no actual stop location recorded
        current_stop_sequence=None,  # Start with no actual stop sequence recorded
    )  # Build the new run record
    db.add(new_run)  # Add run to session
    db.commit()  # Save to DB
    db.refresh(new_run)  # Reload saved object
    return new_run  # Return created run

# =============================================================================
# POST /runs/start
# Start a run
# =============================================================================
@router.post("/start", response_model=RunOut)
def start_run(run: RunStart, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, run.driver_id)  # Load driver
    route = db.get(route_model.Route, run.route_id)  # Load route

    # -------------------------------------------------------------------------
    # Prevent driver from starting multiple active runs
    # -------------------------------------------------------------------------
    existing_active_run = (
        db.query(run_model.Run)
        .filter(run_model.Run.driver_id == run.driver_id)
        .filter(run_model.Run.end_time.is_(None))
        .first()
    )

    if existing_active_run:  # Driver already has an active run
        raise HTTPException(
            status_code=409,
            detail="Driver already has an active run"
        )

    if not driver or not route:  # Validate references
        raise HTTPException(status_code=404, detail="Driver or Route not found")

    # -------------------------------------------------------------------------
    # Create the new run first
    # -------------------------------------------------------------------------
    new_run = run_model.Run(
        driver_id=run.driver_id,  # Assigned driver
        route_id=run.route_id,  # Assigned route
        run_type=run.run_type,  # AM / PM / other
        start_time=datetime.now(timezone.utc).replace(tzinfo=None),  # Start timestamp
        current_stop_id=None,  # Start with no actual stop location recorded
        current_stop_sequence=None,  # No stop reached yet
    )  # Build the started run record

    db.add(new_run)  # Add run to session
    db.flush()  # Get new_run.id before copying stops

    # -------------------------------------------------------------------------
    # Find the most recent source run on the same route that has stops
    # -------------------------------------------------------------------------
    source_run = (
        db.query(run_model.Run)
        .join(stop_model.Stop, stop_model.Stop.run_id == run_model.Run.id)
        .filter(run_model.Run.route_id == run.route_id)
        .filter(run_model.Run.id != new_run.id)
        .order_by(run_model.Run.start_time.desc(), run_model.Run.id.desc())
        .first()
    )

    # -------------------------------------------------------------------------
    # Copy stops from source run into the new run
    # -------------------------------------------------------------------------
    if source_run:
        source_stops = (
            db.query(stop_model.Stop)
            .filter(stop_model.Stop.run_id == source_run.id)
            .order_by(
                stop_model.Stop.sequence.asc(),
                stop_model.Stop.id.asc(),
            )
            .all()
        )

        for stop in source_stops:
            db.add(
                stop_model.Stop(
                    sequence=stop.sequence,  # Keep stop order
                    type=stop.type,  # Keep stop type
                    run_id=new_run.id,  # Attach copied stop to new run
                    name=stop.name,  # Keep stop name
                    address=stop.address,  # Keep stop address
                    planned_time=stop.planned_time,  # Keep planned time
                    latitude=stop.latitude,  # Keep latitude
                    longitude=stop.longitude,  # Keep longitude
                )
            )

    db.commit()  # Save run and copied stops
    db.refresh(new_run)  # Reload saved object
    return new_run  # Return started run


# =============================================================================
# POST /runs/end
# End an active run
# =============================================================================
@router.post("/end", response_model=schemas.RunOut)
def end_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(run_model.Run, run_id)  # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.end_time:
        raise HTTPException(status_code=400, detail="Run already ended")

    run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Set end timestamp
    db.commit()  # Save changes
    db.refresh(run)  # Reload updated run
    return run  # Return ended run

# =============================================================================
# POST /runs/end_by_driver
# End the current active run for a specific driver
#
# Rules:
#   - driver_id is required
#   - driver must exist
#   - only active run can be ended
#   - if multiple active runs exist, end the newest one
# =============================================================================
@router.post("/end_by_driver", response_model=schemas.RunOut)
def end_run_by_driver(
    driver_id: int,                         # Driver whose active run should be ended
    db: Session = Depends(get_db)          # Database session dependency
):

    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    driver = db.get(driver_model.Driver, driver_id)  # Load driver by ID

    if not driver:                                   # If driver not found
        raise HTTPException(status_code=404, detail="Driver not found")

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                      # Query Run table
        .filter(run_model.Run.driver_id == driver_id)  # Only this driver
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .order_by(run_model.Run.start_time.desc())  # Newest active run first
        .first()
    )

    # -------------------------------------------------------------------------
    # Validate active run exists
    # -------------------------------------------------------------------------
    if not active_run:                              # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    # -------------------------------------------------------------------------
    # End the active run
    # -------------------------------------------------------------------------
    active_run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Set end timestamp

    db.commit()                                     # Save changes
    db.refresh(active_run)                          # Reload updated run

    return active_run                               # Return ended run

# =============================================================================
# GET /runs/
# ---------------------------------------------------------------------------
# Returns a list of runs.
#
# Supports optional filters:
#   - driver_id  → filter runs belonging to a specific driver
#   - route_id   → filter runs belonging to a specific route
#   - run_type   → filter runs by type (ex: AM, PM)
#   - active     → filter active or completed runs
#
# Notes:
#   active=True   → runs where end_time IS NULL (still in progress)
#   active=False  → runs where end_time IS NOT NULL (already ended)
#
# If no filters are provided, all runs are returned.
#
# Enriched fields returned:
#   - driver_name
#   - route_number
# =============================================================================
@router.get("/", response_model=List[schemas.RunOut])
def get_all_runs(
    driver_id: int | None = None,          # Optional filter: driver
    route_id: int | None = None,           # Optional filter: route
    run_type: str | None = None,           # Optional filter: run type
    active: bool | None = None,            # Optional filter: active/ended
    db: Session = Depends(get_db)          # Database session dependency
):

    # -------------------------------------------------------------------------
    # Start base query with eager-loaded relationships
    # -------------------------------------------------------------------------
    query = (
        db.query(run_model.Run)            # Query Run table
        .options(
            joinedload(run_model.Run.driver),  # Eager load linked driver
            joinedload(run_model.Run.route),   # Eager load linked route
        )
    )

    # -------------------------------------------------------------------------
    # Apply driver filter
    # -------------------------------------------------------------------------
    if driver_id is not None:              # If driver filter provided
        query = query.filter(
            run_model.Run.driver_id == driver_id
        )

    # -------------------------------------------------------------------------
    # Apply route filter
    # -------------------------------------------------------------------------
    if route_id is not None:               # If route filter provided
        query = query.filter(
            run_model.Run.route_id == route_id
        )

    # -------------------------------------------------------------------------
    # Apply run type filter
    # -------------------------------------------------------------------------
    if run_type is not None:               # If run_type filter provided
        query = query.filter(
            run_model.Run.run_type == run_type
        )

    # -------------------------------------------------------------------------
    # Apply active/ended filter
    # -------------------------------------------------------------------------
    if active is True:                     # Only runs currently active
        query = query.filter(
            run_model.Run.end_time.is_(None)
        )

    if active is False:                    # Only runs that already ended
        query = query.filter(
            run_model.Run.end_time.is_not(None)
        )

    # -------------------------------------------------------------------------
    # Execute query in newest-first order
    # -------------------------------------------------------------------------
    runs = query.order_by(
        run_model.Run.start_time.desc()    # Newest runs first
    ).all()

    # -------------------------------------------------------------------------
    # Build enriched response list
    # -------------------------------------------------------------------------
    return [
        schemas.RunOut(
            id=run.id,                                     # Run ID
            driver_id=run.driver_id,                       # Driver ID
            route_id=run.route_id,                         # Route ID
            run_type=run.run_type,                         # Run type
            start_time=run.start_time,                     # Start timestamp
            end_time=run.end_time,                         # End timestamp
            current_stop_id=run.current_stop_id,           # Current actual stop ID
            current_stop_sequence=run.current_stop_sequence,  # Current actual stop sequence
            driver_name=run.driver.name if run.driver else None,            # Driver name
            route_number=run.route.route_number if run.route else None,     # Route number
        )
        for run in runs
    ]
# =============================================================================
# GET /runs/active
# Return the current active run for one driver
#
# Rules:
#   - driver_id is required
#   - active run = end_time IS NULL
#   - if no active run exists for that driver, return 404
#   - if multiple active runs exist, return the newest one
# =============================================================================
@router.get("/active", response_model=schemas.RunOut)
def get_active_run(
    driver_id: int,                         # Driver to check for active run
    db: Session = Depends(get_db)          # Database session dependency
):

    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    driver = db.get(driver_model.Driver, driver_id)  # Load driver by ID

    if not driver:                                   # If driver not found
        raise HTTPException(status_code=404, detail="Driver not found")

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                      # Query Run table
        .filter(run_model.Run.driver_id == driver_id)  # Only this driver
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .order_by(run_model.Run.start_time.desc())  # Newest active run first
        .first()
    )

    # -------------------------------------------------------------------------
    # Return result or 404
    # -------------------------------------------------------------------------
    if not active_run:                              # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    return active_run                               # Return active run

# =============================================================================
# GET /runs/{run_id}/stops
# Return ordered stops for a specific run
#
# Ordering:
#   - sequence ascending
#   - id ascending
# =============================================================================
@router.get("/{run_id}/stops", response_model=List[StopOut])
def get_run_stops(run_id: int, db: Session = Depends(get_db)):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = db.get(run_model.Run, run_id)  # Load run by ID

    if not run:  # If run does not exist
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Load stops in stable order
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)   # Only stops for this run
        .order_by(
            stop_model.Stop.sequence.asc(),         # Primary stable order
            stop_model.Stop.id.asc(),               # Secondary stable order
        )
        .all()
    )

    return stops  # Return ordered stop list


# =============================================================================
# POST /runs/{run_id}/arrive_stop
# Mark the driver as arrived at a specific stop in the run
#
# Rules:
#   - run must exist
#   - run must still be active
#   - stop sequence must exist in that run
#   - updates run.current_stop_sequence
# =============================================================================
@router.post("/{run_id}/arrive_stop", response_model=schemas.RunOut)
def arrive_at_stop(
    run_id: int,
    stop_sequence: int = Query(..., ge=1),          # Stop sequence reached by driver
    db: Session = Depends(get_db),                  # Database session dependency
):
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = db.get(run_model.Run, run_id)             # Load run by ID

    if not run:                                     # If run does not exist
        raise HTTPException(status_code=404, detail="Run not found")

    if run.end_time is not None:                    # If run already ended
        raise HTTPException(status_code=400, detail="Run has already ended")

    # -------------------------------------------------------------------------
    # Validate stop exists in this run
    # -------------------------------------------------------------------------
    stop = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)   # Only stops in this run
        .filter(stop_model.Stop.sequence == stop_sequence)
        .first()
    )

    if not stop:                                    # If stop sequence not found
        raise HTTPException(
            status_code=404,
            detail="Stop sequence not found for this run",
        )

    # -------------------------------------------------------------------------
    # Update live run location
    # -------------------------------------------------------------------------
    run.current_stop_id = stop.id                   # Save the actual current stop ID
    run.current_stop_sequence = stop.sequence       # Save the actual current stop sequence
    # -----------------------------------------------------------
    # Log ARRIVE event
    # - Records the bus's latest stop visit
    # -----------------------------------------------------------
    event = RunEvent(                                                        # Build arrive event
        run_id=run.id,                                                       # Parent run
        stop_id=stop.id,                                                     # Current stop
        event_type="ARRIVE",                                                 # Event type
    )
    db.add(event)                                                            # Add event to current transaction
    
    db.commit()                                     # Save updated run
    db.refresh(run)                                 # Reload updated run

    return run                                      # Return updated run

# =============================================================================
# POST /runs/{run_id}/next_stop
# -----------------------------------------------------------------------------
# Purpose:
#   Advance the run to the next stop without requiring the driver to know the
#   stop sequence number.
# =============================================================================
@router.post("/{run_id}/next_stop", response_model=schemas.RunOut)
def advance_to_next_stop(
    run_id: int,
    db: Session = Depends(get_db),                  # Database session dependency
):
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = db.get(run_model.Run, run_id)             # Load run by ID

    if not run:                                     # If run does not exist
        raise HTTPException(status_code=404, detail="Run not found")

    if run.end_time is not None:                    # If run already ended
        raise HTTPException(status_code=400, detail="Run has already ended")

    # -------------------------------------------------------------------------
    # Load ordered stops for this run
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)   # Only stops in this run
        .order_by(stop_model.Stop.sequence.asc(), stop_model.Stop.id.asc())
        .all()
    )

    if not stops:                                   # If run has no stops
        raise HTTPException(status_code=404, detail="No stops found for this run")

    # -------------------------------------------------------------------------
    # Resolve next stop sequence
    # -------------------------------------------------------------------------
    if run.current_stop_sequence is None:           # No progress stored yet
        next_sequence = 1                           # Start at first stop
    else:
        next_sequence = run.current_stop_sequence + 1  # Advance to next stop

    # -------------------------------------------------------------------------
    # Validate next stop exists in this run
    # -------------------------------------------------------------------------
    next_stop = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)   # Only stops in this run
        .filter(stop_model.Stop.sequence == next_sequence)
        .first()
    )

    if not next_stop:                               # No further stop available
        raise HTTPException(status_code=404, detail="No next stop found for this run")

    # -------------------------------------------------------------------------
    # Persist progress
    # -------------------------------------------------------------------------
    run.current_stop_id = next_stop.id              # Save the resolved next stop ID
    run.current_stop_sequence = next_stop.sequence  # Save the resolved next stop sequence
    db.commit()                                     # Persist update
    db.refresh(run)                                 # Reload updated run

    return run                                      # Return updated run

# =============================================================================
# POST /runs/{run_id}/pickup_student
# -----------------------------------------------------------------------------
# Mark a student as picked up during an active run.
#
# Purpose:
#   - confirm boarding at the current stop
#   - store pickup timestamp
#   - mark student as onboard
#
# Validation:
#   - run must exist
#   - run must be started / active
#   - run must currently be at a stop
#   - student must be assigned to this run
#   - student's assigned stop must match current stop sequence
#   - student must not already be picked up
# =============================================================================
@router.post("/{run_id}/pickup_student", response_model=PickupStudentResponse)
def pickup_student(
    run_id: int,
    payload: PickupStudentRequest,
    db: Session = Depends(get_db),
):
    # -------------------------------------------------------------------------
    # Load the target run
    # -------------------------------------------------------------------------
    run = db.query(run_model.Run).filter(run_model.Run.id == run_id).first()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # -------------------------------------------------------------------------
    # Ensure the run is active
    # -------------------------------------------------------------------------
    if run.start_time is None or run.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Ensure the driver is currently positioned at a stop
    # -------------------------------------------------------------------------
    if run.current_stop_sequence is None or run.current_stop_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not currently at a stop",
        )

    # -------------------------------------------------------------------------
    # Load the student assignment for this run
    # -------------------------------------------------------------------------
    # joinedload() is used so the assigned stop is available immediately.
    assignment = (
        db.query(StudentRunAssignment)
        .options(joinedload(StudentRunAssignment.stop))
        .filter(
            StudentRunAssignment.run_id == run_id,
            StudentRunAssignment.student_id == payload.student_id,
        )
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student is not assigned to this run",
        )

    # -------------------------------------------------------------------------
    # Prevent duplicate pickup
    # -------------------------------------------------------------------------
    if assignment.picked_up is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been picked up",
        )

    # -------------------------------------------------------------------------
    # Mark pickup fields
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)
    
    assignment.picked_up = True  # Student has boarded
    assignment.picked_up_at = now  # Store pickup time
    assignment.is_onboard = True  # Student is now physically on the bus
    assignment.actual_pickup_stop_id = run.current_stop_id  # Record the actual boarding stop

    # -----------------------------------------------------------
    # Log pickup event
    # - Records actual stop used for dropoff
    # -----------------------------------------------------------
    event = RunEvent(
        run_id=run.id,
        stop_id=run.current_stop_id,
        student_id=assignment.student_id,
        event_type="PICKUP",
    )

    db.add(event)                                                           # Add event to current transaction
    # -------------------------------------------------------------------------
    # Save changes
    # -------------------------------------------------------------------------
    db.commit()  # Persist pickup state
    db.refresh(assignment)  # Reload updated assignment from DB

    # -------------------------------------------------------------------------
    # Return clean API response
    # -------------------------------------------------------------------------
    return PickupStudentResponse(
        message="Student picked up successfully",
        run_id=run.id,
        student_id=assignment.student_id,
        picked_up=assignment.picked_up,
        is_onboard=assignment.is_onboard,
        picked_up_at=assignment.picked_up_at,
    )

# =============================================================================
# POST /runs/{run_id}/dropoff_student
# -----------------------------------------------------------------------------
# Mark a student as dropped off during an active run.
#
# Purpose:
#   - confirm drop-off at the current stop
#   - store drop-off timestamp
#   - mark student as no longer onboard
#
# Validation:
#   - run must exist
#   - run must be started / active
#   - run must currently be at a stop
#   - student must be assigned to this run
#   - student's assigned stop must match current stop sequence
#   - student must currently be onboard
#   - student must not already be dropped off
# =============================================================================
@router.post("/{run_id}/dropoff_student", response_model=DropoffStudentResponse)
def dropoff_student(
    run_id: int,
    payload: DropoffStudentRequest,
    db: Session = Depends(get_db),
):
    # -------------------------------------------------------------------------
    # Load the target run
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)
        .filter(run_model.Run.id == run_id)
        .first()
    )  # Find run by ID

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # -------------------------------------------------------------------------
    # Ensure the run has started and is still active
    # -------------------------------------------------------------------------
    if run.start_time is None or run.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Ensure the run is currently positioned at a stop
    # -------------------------------------------------------------------------
    if run.current_stop_sequence is None or run.current_stop_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not currently at a stop",
        )

    # -------------------------------------------------------------------------
    # Load the student's runtime assignment and assigned stop
    # -------------------------------------------------------------------------
    assignment = (
        db.query(StudentRunAssignment)
        .options(joinedload(StudentRunAssignment.stop))
        .filter(
            StudentRunAssignment.run_id == run_id,
            StudentRunAssignment.student_id == payload.student_id,
        )
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student is not assigned to this run",
        )

    # -------------------------------------------------------------------------
    # Ensure the student is currently onboard before drop-off
    # -------------------------------------------------------------------------
    if assignment.picked_up is not True or assignment.is_onboard is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is not currently onboard",
        )

    # -------------------------------------------------------------------------
    # Prevent duplicate drop-off
    # -------------------------------------------------------------------------
    if assignment.dropped_off is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has already been dropped off",
        )

    # -------------------------------------------------------------------------
    # Mark drop-off fields
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)

    assignment.dropped_off = True  # Student has been dropped off
    assignment.dropped_off_at = now  # Store drop-off time
    assignment.is_onboard = False  # Student is no longer on the bus
    assignment.actual_dropoff_stop_id = run.current_stop_id  # Record the actual drop-off stop

    # -----------------------------------------------------------
    # Log DROPOFF event
    # - Records actual stop used for dropoff
    # -----------------------------------------------------------
    event = RunEvent(                                                        # Build dropoff event
        run_id=run.id,                                                       # Parent run
        stop_id=run.current_stop_id,                                         # Actual dropoff stop
        student_id=assignment.student_id,                                    # Dropped-off student
        event_type="DROPOFF",                                                # Event type
    )
    db.add(event)                                                            # Add event to current transaction
    
    # -------------------------------------------------------------------------
    # Save changes
    # -------------------------------------------------------------------------
    db.commit()  # Persist drop-off state
    db.refresh(assignment)  # Reload updated assignment from DB

    # -------------------------------------------------------------------------
    # Return clean API response
    # -------------------------------------------------------------------------
    return DropoffStudentResponse(
        message="Student dropped off successfully",
        run_id=run.id,
        student_id=assignment.student_id,
        dropped_off=assignment.dropped_off,
        is_onboard=assignment.is_onboard,
        dropped_off_at=assignment.dropped_off_at,
    )

# -------------------------------------------------------------------------
# GET /runs/{run_id}/timeline
# - Returns ordered ARRIVE / PICKUP / DROPOFF events for a run
# - Oldest first so the full run can be replayed in order
# -------------------------------------------------------------------------
@router.get("/{run_id}/timeline", response_model=RunTimelineOut)
def get_run_timeline(run_id: int, db: Session = Depends(get_db)):

    run = db.get(run_model.Run, run_id)                                   # Load run by ID
    if not run:                                                           # If run does not exist
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    events = (
        db.query(RunEvent)                                                # Query run events
        .filter(RunEvent.run_id == run_id)                                # Only this run
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())            # Stable oldest-first ordering
        .all()                                                            # Materialize list
    )

    return RunTimelineOut(                                                # Build timeline response
        run_id=run_id,                                                    # Parent run ID
        total_events=len(events),                                         # Event count
        events=events,                                                    # Ordered event rows
    )

# =============================================================================
# GET /runs/{run_id}/replay
# Return a human-readable replay stream for a specific run
#
# Purpose:
# - Converts raw run events into readable admin/debug output
# - Includes stop names, student names, onboard count, and summary totals
# =============================================================================
@router.get("/{run_id}/replay", response_model=RunReplayOut)
def get_run_replay(run_id: int, db: Session = Depends(get_db)):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = db.get(run_model.Run, run_id)  # Load run by ID
    if not run:  # If run does not exist
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Load all run events in stable chronological order
    # -------------------------------------------------------------------------
    raw_events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)  # Only events for this run
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())  # Stable time order
        .all()
    )

    # -------------------------------------------------------------------------
    # Build replay rows with readable context
    # -------------------------------------------------------------------------
    replay_events: list[RunReplayEventOut] = []  # Final replay rows
    onboard_count = 0  # Live bus occupancy during replay

    total_arrivals = 0  # Summary counter
    total_pickups = 0  # Summary counter
    total_dropoffs = 0  # Summary counter

    for event in raw_events:
        stop_name = None  # Default when stop is missing
        student_name = None  # Default when student is missing

        # ---------------------------------------------------------------------
        # Resolve stop context
        # ---------------------------------------------------------------------
        if event.stop_id is not None:
            stop = db.get(stop_model.Stop, event.stop_id)  # Load stop by ID
            stop_name = stop.name if stop else None  # Safe stop name

        # ---------------------------------------------------------------------
        # Resolve student context
        # ---------------------------------------------------------------------
        if event.student_id is not None:
            student = db.get(student_model.Student, event.student_id)  # Load student
            student_name = student.name if student else None  # Safe student name

        # ---------------------------------------------------------------------
        # Convert raw event into readable replay message
        # ---------------------------------------------------------------------
        if event.event_type == "ARRIVE":
            total_arrivals += 1  # Count arrival events

            if stop_name:
                message = f"Bus arrived at {stop_name}"  # Human-readable arrival
            elif event.stop_id is not None:
                message = f"Bus arrived at Stop {event.stop_id}"  # Fallback arrival
            else:
                message = "Bus arrived at an unknown stop"  # Safety fallback

        elif event.event_type == "PICKUP":
            total_pickups += 1  # Count pickup events
            onboard_count += 1  # Occupancy increases after pickup

            if student_name and stop_name:
                message = f"{student_name} picked up at {stop_name}"  # Full pickup message
            elif event.student_id is not None and stop_name:
                message = f"Student {event.student_id} picked up at {stop_name}"  # Partial fallback
            elif student_name and event.stop_id is not None:
                message = f"{student_name} picked up at Stop {event.stop_id}"  # Partial fallback
            else:
                message = "Student picked up"  # Safety fallback

        elif event.event_type == "DROPOFF":
            total_dropoffs += 1  # Count dropoff events
            onboard_count = max(0, onboard_count - 1)  # Never allow negative occupancy

            if student_name and stop_name:
                message = f"{student_name} dropped off at {stop_name}"  # Full dropoff message
            elif event.student_id is not None and stop_name:
                message = f"Student {event.student_id} dropped off at {stop_name}"  # Partial fallback
            elif student_name and event.stop_id is not None:
                message = f"{student_name} dropped off at Stop {event.stop_id}"  # Partial fallback
            else:
                message = "Student dropped off"  # Safety fallback

        else:
            message = f"Run event: {event.event_type}"  # Unknown/future event fallback

        # ---------------------------------------------------------------------
        # Save replay event row
        # ---------------------------------------------------------------------
        replay_events.append(
            RunReplayEventOut(
                id=event.id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                stop_id=event.stop_id,
                stop_name=stop_name,
                student_id=event.student_id,
                student_name=student_name,
                onboard_count=onboard_count,
                message=message,
            )
        )

    # -------------------------------------------------------------------------
    # Return replay response with summary
    # -------------------------------------------------------------------------
    return RunReplayOut(
        run_id=run.id,
        events=replay_events,
        summary=RunReplaySummaryOut(
            total_events=len(replay_events),
            total_arrivals=total_arrivals,
            total_pickups=total_pickups,
            total_dropoffs=total_dropoffs,
        ),
    )
# =============================================================================
# GET /runs/{run_id}/onboard_students
# -----------------------------------------------------------------------------
# Return all students currently onboard the bus for an active run.
#
# Purpose:
#   - allow drivers to see who is still on the bus
#   - allow dispatch to monitor live bus occupancy
#
# Data source:
#   StudentRunAssignment where:
#       run_id == run_id
#       is_onboard == True
#
# Students are returned ordered by stop sequence.
# =============================================================================
@router.get("/{run_id}/onboard_students", response_model=OnboardStudentsResponse)
def get_onboard_students(
    run_id: int,
    db: Session = Depends(get_db),
):
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)
        .filter(run_model.Run.id == run_id)
        .first()
    )

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # -------------------------------------------------------------------------
    # Ensure run is active
    # -------------------------------------------------------------------------
    if run.start_time is None or run.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Load onboard assignments with related student + stop
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),
            joinedload(StudentRunAssignment.stop),
        )
        .filter(
            StudentRunAssignment.run_id == run_id,
            StudentRunAssignment.is_onboard == True,
        )
        .all()
    )

    # -------------------------------------------------------------------------
    # Sort students by stop sequence
    # -------------------------------------------------------------------------
    assignments.sort(key=lambda a: a.stop.sequence if a.stop else 0)

    # -------------------------------------------------------------------------
    # Build response items
    # -------------------------------------------------------------------------
    students = []

    for a in assignments:
        students.append(
            OnboardStudentItem(
                student_id=a.student.id,
                student_name=a.student.name,
                stop_id=a.stop.id,
                stop_name=a.stop.name,
                stop_sequence=a.stop.sequence,
                picked_up_at=a.picked_up_at,
            )
        )

    # -------------------------------------------------------------------------
    # Return structured response
    # -------------------------------------------------------------------------
    return OnboardStudentsResponse(
        run_id=run_id,
        total_onboard_students=len(students),
        students=students,
    )


# =============================================================================
# Get Run Occupancy Summary
# -----------------------------------------------------------------------------
# Purpose:
#   Return a quick student occupancy summary for one run.
#
# Summary includes:
#   - total assigned students
#   - total picked up
#   - total dropped off
#   - total currently onboard
#   - total not yet boarded
#
# Notes:
#   Runtime state is derived from StudentRunAssignment.
#   This keeps summary logic aligned with pickup/dropoff/onboard endpoints.
# =============================================================================
@router.get(
    "/{run_id}/occupancy_summary",
    response_model=RunOccupancySummaryResponse,
    summary="Get run occupancy summary",
)
def get_run_occupancy_summary(
    run_id: int,
    db: Session = Depends(get_db),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = db.query(Run).filter(Run.id == run_id).first()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found.",
        )

    # -------------------------------------------------------------------------
    # Load all runtime student assignments for this run
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .all()
    )

    # -------------------------------------------------------------------------
    # Calculate occupancy counts from runtime assignment flags
    # -------------------------------------------------------------------------
    total_assigned_students = len(assignments)  # All students assigned to this run

    total_picked_up = sum(
        1 for assignment in assignments if assignment.picked_up
    )  # Picked up at least once

    total_dropped_off = sum(
        1 for assignment in assignments if assignment.dropped_off
    )  # Dropped off

    total_currently_onboard = sum(
        1 for assignment in assignments if assignment.is_onboard
    )  # Currently on the bus

    total_not_yet_boarded = sum(
        1 for assignment in assignments if not assignment.picked_up
    )  # Assigned but not picked up yet

    # -------------------------------------------------------------------------
    # Return occupancy summary
    # -------------------------------------------------------------------------
    return RunOccupancySummaryResponse(
        run_id=run.id,
        route_id=run.route_id,
        run_type=run.run_type,
        total_assigned_students=total_assigned_students,
        total_picked_up=total_picked_up,
        total_dropped_off=total_dropped_off,
        total_currently_onboard=total_currently_onboard,
        total_not_yet_boarded=total_not_yet_boarded,
    )
# =============================================================================
# GET /runs/{run_id}
# Return one run by ID with enriched display fields
# =============================================================================
@router.get("/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):

    # -------------------------------------------------------------------------
    # Load run with linked driver and route
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)                         # Query Run table
        .options(
            joinedload(run_model.Run.driver),           # Eager load driver
            joinedload(run_model.Run.route),            # Eager load route
        )
        .filter(run_model.Run.id == run_id)             # Match requested run ID
        .first()
    )

    if not run:                                         # If run not found
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Return enriched run response
    # -------------------------------------------------------------------------
    return schemas.RunOut(
        id=run.id,                                      # Run ID
        driver_id=run.driver_id,                        # Driver ID
        route_id=run.route_id,                          # Route ID
        run_type=run.run_type,                          # Run type
        start_time=run.start_time,                      # Start timestamp
        end_time=run.end_time,                          # End timestamp
        current_stop_id=run.current_stop_id,            # Current actual stop ID
        current_stop_sequence=run.current_stop_sequence,  # Current actual stop sequence
        driver_name=run.driver.name if run.driver else None,              # Driver name
        route_number=run.route.route_number if run.route else None,       # Route number
    )


# =============================================================================
# GET /runs/{run_id}/running_board
# Returns the operational running board for one run
# Source of truth for riders is StudentRunAssignment, not legacy student fields
# =============================================================================
@router.get("/{run_id}/running_board", response_model=RunningBoardResponse)
def get_running_board(run_id: int, db: Session = Depends(get_db)):

    # -------------------------------------------------------------------------
    # Load the run
    # -------------------------------------------------------------------------
    run = db.get(run_model.Run, run_id)  # Retrieve run by ID

    if not run:  # If run does not exist
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Load run stops ordered by sequence
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)  # Query Stop table
        .filter(stop_model.Stop.run_id == run_id)  # Only stops belonging to this run
        .order_by(stop_model.Stop.sequence.asc())  # Ensure correct stop order
        .all()
    )

    # -------------------------------------------------------------------------
    # Load student assignments for this run
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)  # Query assignment table
        .options(joinedload(StudentRunAssignment.student))  # Load linked student
        .filter(StudentRunAssignment.run_id == run_id)  # Only this run
        .all()
    )

    # -------------------------------------------------------------------------
    # Group assignments by stop
    # -------------------------------------------------------------------------
    assignments_by_stop = {}  # Dictionary {stop_id: [students]}

    for assignment in assignments:  # Loop through assignments

        stop_id = assignment.stop_id  # Stop where student boards

        if stop_id is None:  # Skip invalid assignments
            continue

        if stop_id not in assignments_by_stop:  # Create list for stop
            assignments_by_stop[stop_id] = []

        student = assignment.student  # Get student object

        if student:  # If student exists
            assignments_by_stop[stop_id].append(
                RunningBoardStudent(
                    student_id=student.id,  # Student ID
                    student_name=student.name,  # Student display name
                )
            )

    # -------------------------------------------------------------------------
    # Build running board rows
    # -------------------------------------------------------------------------
    running_stops = []  # Final stop list
    cumulative_load = 0  # Running onboard count

    for stop in stops:  # Iterate through ordered stops

        stop_students = assignments_by_stop.get(stop.id, [])  # Students for stop
        student_count = len(stop_students)  # Riders boarding here

        load_change = student_count  # Boardings at this stop
        cumulative_load += load_change  # Update onboard count

        running_stops.append(
            RunningBoardStop(
                stop_id=stop.id,  # Stop ID
                sequence=stop.sequence,  # Stop order
                planned_time=str(stop.planned_time) if stop.planned_time else None,  # Time
                lat=stop.latitude,  # Latitude
                lng=stop.longitude,  # Longitude
                student_count_at_stop=student_count,  # Riders here
                load_change=load_change,  # Boardings
                cumulative_load=cumulative_load,  # Bus load after stop
                students=stop_students,  # Student list
            )
        )

    # -------------------------------------------------------------------------
    # Return full running board
    # -------------------------------------------------------------------------
    return RunningBoardResponse(
        run_id=run.id,  # Run identifier
        route_id=run.route_id,  # Parent route
        run_name=getattr(run, "name", None),  # Optional run label
        total_stops=len(stops),  # Stop count
        total_assigned_students=len(assignments),  # Rider count
        stops=running_stops,  # Running board rows
    )

# =============================================================================
# GET /runs/{run_id}/assignments
# Returns all student assignments for a specific run
# =============================================================================
@router.get("/{run_id}/assignments")
def get_run_assignments(
    run_id: int,                         # Run identifier
    db: Session = Depends(get_db)        # Database session dependency
):

    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = db.get(run_model.Run, run_id)  # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Load assignments with student and stop
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),  # Load student
            joinedload(StudentRunAssignment.stop),     # Load stop
        )
        .filter(StudentRunAssignment.run_id == run_id)
        .all()
    )

    # -------------------------------------------------------------------------
    # Apply stable ordering in Python
    # -------------------------------------------------------------------------
    assignments.sort(
        key=lambda a: (
            a.stop.sequence if a.stop and a.stop.sequence is not None else 999999,  # Stop order
            a.id,                                                                   # Stable tie-breaker
        )
    )

    # -------------------------------------------------------------------------
    # Build response
    # -------------------------------------------------------------------------
    result = []

    for a in assignments:
        result.append({
            "student_id": a.student.id if a.student else None,
            "student_name": a.student.name if a.student else None,
            "stop_id": a.stop_id,
            "stop_name": a.stop.name if a.stop else None,
            "sequence": a.stop.sequence if a.stop else None,
            "run_type": run.run_type.value,  # Convert enum to plain string
        })

    return result

# =============================================================================
# GET /runs/{run_id}/summary
# Returns a compact operational summary for one run
# =============================================================================
@router.get("/{run_id}/summary", response_model=schemas.RunSummaryOut)
def get_run_summary(run_id: int, db: Session = Depends(get_db)):

    # -------------------------------------------------------------------------
    # Load run with driver and route
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)
        .options(
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        )
        .filter(run_model.Run.id == run_id)
        .first()
    )

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # -------------------------------------------------------------------------
    # Load run stops
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .all()
    )

    # -------------------------------------------------------------------------
    # Load student assignments
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .all()
    )

    # -------------------------------------------------------------------------
    # Determine run status
    # -------------------------------------------------------------------------
    status = "active" if run.end_time is None else "ended"

    # -------------------------------------------------------------------------
    # Compute current load
    # -------------------------------------------------------------------------
    current_load = len(assignments)

    # -------------------------------------------------------------------------
    # Return summary
    # -------------------------------------------------------------------------
    return schemas.RunSummaryOut(
        run_id=run.id,
        driver_id=run.driver_id,
        driver_name=run.driver.name if run.driver else None,
        route_id=run.route_id,
        route_number=run.route.route_number if run.route else None,
        run_type=run.run_type,
        start_time=run.start_time,
        end_time=run.end_time,
        status=status,
        total_stops=len(stops),
        total_assigned_students=len(assignments),
        current_load=current_load,
    )

# =============================================================================
# GET /runs/progress/by_driver
# Returns live progress for the newest active run of a driver
#
# Purpose:
#   - Driver/client sends driver_id instead of run_id
#   - Reuses the same progress logic already built for a run
# =============================================================================
@router.get("/progress/by_driver", response_model=schemas.RunProgressOut)
def get_run_progress_by_driver(
    driver_id: int,                                                   # Driver whose active run we want
    current_stop_sequence: int | None = Query(None),                  # Optional manual override
    db: Session = Depends(get_db)                                     # Database session
):
    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    driver = db.get(driver_model.Driver, driver_id)                   # Load driver by ID
    if not driver:                                                    # If driver not found
        raise HTTPException(status_code=404, detail="Driver not found")

    # -------------------------------------------------------------------------
    # Find the newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                                       # Query runs
        .filter(run_model.Run.driver_id == driver_id)                 # Same driver
        .filter(run_model.Run.end_time.is_(None))                     # Only active runs
        .order_by(run_model.Run.start_time.desc(), run_model.Run.id.desc())  # Newest first
        .first()
    )

    # -------------------------------------------------------------------------
    # Validate active run exists
    # -------------------------------------------------------------------------
    if not active_run:                                                # No active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    # -------------------------------------------------------------------------
    # Resolve stop sequence priority:
    # 1) explicit query param
    # 2) stored run progress
    # 3) default to first stop
    # -------------------------------------------------------------------------
    resolved_sequence = (
        current_stop_sequence                                         # Manual override from query param
        if current_stop_sequence is not None
        else active_run.current_stop_sequence                         # Stored run progress if present
    )

    if resolved_sequence is None:                                     # Nothing stored yet
        resolved_sequence = 1                                         # Default to first stop

    # -------------------------------------------------------------------------
    # Reuse the existing run progress logic
    # -------------------------------------------------------------------------
    return get_run_progress(
        run_id=active_run.id,                                         # Active run ID
        current_stop_sequence=resolved_sequence,                      # Final resolved sequence
        db=db                                                         # Same database session
    )
# =============================================================================
# Live Run Progress
# -----------------------------------------------------------------------------
# Returns the current stop and next stop for a run based on the provided
# current stop sequence.
#
# This is a read-only operational endpoint for live driver workflow.
# It does not persist progress yet.
# =============================================================================
@router.get("/{run_id}/progress", response_model=schemas.RunProgressOut)
def get_run_progress(
    run_id: int,
    current_stop_sequence: int = Query(..., ge=1),   # Current stop sequence in the run
    db: Session = Depends(get_db),
):
    # -------------------------------------------------------------------------
    # Load run with related driver and route for display fields
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)
        .options(
            joinedload(run_model.Run.driver),         # Load driver for driver_name if needed later
            joinedload(run_model.Run.route),          # Load route for route_number
        )
        .filter(run_model.Run.id == run_id)
        .first()
    )

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.end_time is not None:  # Run already completed
        raise HTTPException(
            status_code=400,
            detail="Run has already ended"
    )

    # -------------------------------------------------------------------------
    # Load run stops in stable order
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .order_by(
            stop_model.Stop.sequence.asc(),           # Primary stable order
            stop_model.Stop.id.asc(),                 # Secondary stable order
        )
        .all()
    )

    if not stops:
        raise HTTPException(status_code=404, detail="No stops found for this run")

    # -------------------------------------------------------------------------
    # Find current stop by sequence
    # -------------------------------------------------------------------------
    current_index = None

    for index, stop in enumerate(stops):
        if stop.sequence == current_stop_sequence:
            current_index = index
            break

    if current_index is None:
        raise HTTPException(
            status_code=404,
            detail="Current stop sequence not found for this run",
        )

    current_stop = stops[current_index]                              # Current stop object
    next_stop = stops[current_index + 1] if current_index + 1 < len(stops) else None  # Next stop if exists

    # -------------------------------------------------------------------------
    # Build live progress response
    # -------------------------------------------------------------------------
    return schemas.RunProgressOut(
        run_id=run.id,
        route_id=run.route_id,
        route_number=run.route.route_number if run.route else None,
        run_type=run.run_type,

        total_stops=len(stops),
        current_stop_index=current_index + 1,                        # Convert to 1-based position
        remaining_stops=len(stops) - current_index,                  # Includes current stop

        current_stop_id=current_stop.id,
        current_stop_name=current_stop.name,
        current_stop_sequence=current_stop.sequence,
        current_stop_planned_time=current_stop.planned_time,

        next_stop_id=next_stop.id if next_stop else None,
        next_stop_name=next_stop.name if next_stop else None,
        next_stop_sequence=next_stop.sequence if next_stop else None,
        next_stop_planned_time=next_stop.planned_time if next_stop else None,
    )

