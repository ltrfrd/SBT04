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
from backend.models.associations import StudentRunAssignment  # Runtime rider assignments
from backend.schemas.run import RunStart, RunOut
from backend.schemas.stop import StopOut
from backend.schemas.run import (  # Running board response schemas
    RunningBoardResponse,
    RunningBoardStop,
    RunningBoardStudent,
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
        start_time=datetime.now(timezone.utc).replace(tzinfo=None)  # Store naive UTC
    )
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
        current_stop_sequence=None,  # No stop reached yet
    )

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
            current_stop_sequence=run.current_stop_sequence,
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
    # Update live run progress
    # -------------------------------------------------------------------------
    run.current_stop_sequence = stop_sequence       # Save driver's current stop sequence

    db.commit()                                     # Save updated run
    db.refresh(run)                                 # Reload updated run

    return run                                      # Return updated run


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
        end_time=run.end_time,
        current_stop_sequence=run.current_stop_sequence,                          # End timestamp
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
    driver_id: int,                                       # Driver requesting live progress
    current_stop_sequence: int = Query(..., ge=1),       # Current stop sequence in the run
    db: Session = Depends(get_db),                       # Database session dependency
):
    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    driver = db.get(driver_model.Driver, driver_id)      # Load driver by ID

    if not driver:                                       # If driver not found
        raise HTTPException(status_code=404, detail="Driver not found")

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)
        .filter(run_model.Run.driver_id == driver_id)    # Only this driver
        .filter(run_model.Run.end_time.is_(None))        # Only active runs
        .order_by(run_model.Run.start_time.desc())       # Newest active run first
        .first()
    )

    if not active_run:                                   # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    # -------------------------------------------------------------------------
    # Reuse run progress endpoint logic
    # -------------------------------------------------------------------------
    return get_run_progress(
        run_id=active_run.id,                            # Use active run ID
        current_stop_sequence=current_stop_sequence,     # Forward current stop sequence
        db=db,                                           # Reuse same DB session
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

