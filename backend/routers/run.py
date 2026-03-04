# ===========================================================
# backend/routers/run.py — BST Run Router
# -----------------------------------------------------------
# Manages creation, listing, and timing (start/end) of runs.
# Each run links a driver, route, and run_type (AM, MIDDAY, PM, EXTRA).
# ===========================================================

from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI helpers
from sqlalchemy.orm import Session  # Database session
from datetime import datetime, timezone                 # Use timezone-aware UTC now (avoid utcnow() deprecation)
from typing import List  # For list responses
from database import get_db  # DB dependency
from backend import schemas  # Pydantic schemas
from backend.models import run as run_model  # Run model
from backend.models import driver as driver_model  # Driver model
from backend.models import route as route_model  # Route model
from backend.schemas.run import RunStart, RunOut
# --- Run Schemas (direct import to avoid __init__ re-export dependency) ---
from backend.schemas.run import RunStart  # Schema used to start/create a run (POST /runs)
# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(
    prefix="/runs", tags=["Runs"]  # Base URL path  # Swagger section title
)


# -----------------------------------------------------------
# POST /runs → Manually create a run (optional)
# -----------------------------------------------------------
@router.post("/", response_model=schemas.RunOut, status_code=status.HTTP_201_CREATED)
def create_run(run: RunStart, db: Session = Depends(get_db)):  # Strongly typed RunStart payload    """Create a new run manually (usually handled automatically)."""
    driver = db.get(driver_model.Driver, run.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    route = db.get(route_model.Route, run.route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    new_run = run_model.Run(**run.model_dump())
    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    return new_run


# -----------------------------------------------------------
# POST /runs/start → Start a run (matches tests)
# -----------------------------------------------------------


@router.post("/start", response_model=RunOut)
def start_run(run: RunStart, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, run.driver_id)
    route = db.get(route_model.Route, run.route_id)

    if not driver or not route:
        raise HTTPException(status_code=404, detail="Driver or Route not found")

    new_run = run_model.Run(
        driver_id=run.driver_id,
        route_id=run.route_id,
        run_type=run.run_type,
        start_time=datetime.now(timezone.utc).replace(tzinfo=None)         # UTC timestamp (naive) for DB compatibility; avoids utcnow() deprecation
    )

    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    return new_run  # ✅ REMOVE THE DOT


# -----------------------------------------------------------
# POST /runs/end → Driver ends an ongoing run
# -----------------------------------------------------------
@router.post("/end", response_model=schemas.RunOut)
def end_run(run_id: int, db: Session = Depends(get_db)):
    """End a run by recording the current UTC time."""
    run = db.get(run_model.Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.end_time:
        raise HTTPException(status_code=400, detail="Run already ended")

    # Record end time
    run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)         # UTC timestamp (naive) for DB compatibility; avoids utcnow() deprecation
    db.commit()
    db.refresh(run)
    return run


# -----------------------------------------------------------
# GET /runs → Retrieve all runs
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.RunOut])
def get_all_runs(db: Session = Depends(get_db)):
    """List all runs for all drivers and routes."""
    return db.query(run_model.Run).all()


# -----------------------------------------------------------
# GET /runs/{run_id} → Retrieve one run
# -----------------------------------------------------------
@router.get("/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    """Retrieve details for a specific run."""
    run = db.get(run_model.Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
