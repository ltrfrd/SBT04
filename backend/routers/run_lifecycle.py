# ===========================================================
# backend/routers/run_lifecycle.py - FleetOS Run Lifecycle Router
# -----------------------------------------------------------
# Lifecycle and planning endpoints split from the main run router.
# ===========================================================

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db

from backend import schemas
from backend.models import driver as driver_model
from backend.models import pretrip as pretrip_model
from backend.models import route as route_model
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models.associations import RouteDriverAssignment
from backend.models.associations import StudentRunAssignment
from backend.models.operator import Operator
from backend.models.run_event import RunEvent
from backend.schemas.run import RunCompleteOut, RunOut, RunUpdate
from backend.utils.operator_scope import (
    get_operator_context,
    get_operator_scoped_driver_or_404,
    get_operator_scoped_route_or_404,
)
from backend.utils.pretrip_alerts import create_missing_pretrip_alert_if_needed
from backend.routers.run_helpers import (
    _assert_unique_route_run_type,
    _get_operator_scoped_run_or_404,
    _get_run_assignments,
    _is_run_active,
    _require_posttrip_phase2_completed,
    _resolve_run_driver,
    _serialize_run,
)


router = APIRouter(tags=["Runs"])


# -----------------------------------------------------------
# - Start run
# - Start a prepared run only
# -----------------------------------------------------------
@router.post(
    "/start",
    response_model=RunOut,
    summary="Start run",
    description=(
        "Operational runtime endpoint. Start an existing prepared run only through the Route -> Run -> Stop -> Student workflow. "
        "A prepared run must already have stops and at least one runtime student assignment before start succeeds. "
        "At start time, the run driver is resolved from the single active route-driver assignment only. "
        "Primary/default assignment does not control runtime ownership by itself. "
        "This endpoint starts the run only and does not create stops, students, or StudentRunAssignment rows."
    ),
    response_description="Started run",
)
def start_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    target_run = _get_operator_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        "operate",
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        ],
    )

    if target_run.start_time is not None:
        raise HTTPException(status_code=400, detail="Run already started")

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=target_run.route_id,
        operator_id=operator.id,
        required_access="operate",
        options=[joinedload(route_model.Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )

    active_bus_id = route.active_bus_id or route.bus_id         # Active bus is authoritative; compatibility bus_id is fallback
    if active_bus_id is None:
        raise HTTPException(status_code=400, detail="Route has no active bus assigned")

    today_pretrip = (
        db.query(pretrip_model.PreTripInspection)
        .options(selectinload(pretrip_model.PreTripInspection.defects))
        .filter(pretrip_model.PreTripInspection.bus_id == active_bus_id)
        .filter(pretrip_model.PreTripInspection.inspection_date == date.today())
        .first()
    )  # Today's pre-trip for the resolved active bus only

    if not today_pretrip:
        create_missing_pretrip_alert_if_needed(
            db=db,
            bus_id=active_bus_id,
            route_id=route.id,
            run_id=target_run.id,
            scheduled_start_time=target_run.scheduled_start_time,
        )
        db.commit()                                             # Persist any missing-pretrip alert before returning the block response
        raise HTTPException(status_code=400, detail="No pre-trip found for active bus for today")

    if today_pretrip.fit_for_duty == "no":
        raise HTTPException(status_code=400, detail="Run blocked: driver marked not fit for duty")

    if any(defect.severity == "major" for defect in today_pretrip.defects):
        raise HTTPException(status_code=400, detail="Run blocked: major defect reported on pre-trip")

    resolved_driver_id = _resolve_run_driver(route)  # Resolve active driver at actual start time
    target_run.driver_id = resolved_driver_id        # Persist the current start-time driver on the run

    driver = db.get(driver_model.Driver, resolved_driver_id)  # Load resolved driver

    # -------------------------------------------------------------------------
    # Prevent driver from starting multiple active runs
    # -------------------------------------------------------------------------
    existing_active_run = (
        db.query(run_model.Run)
        .filter(run_model.Run.driver_id == resolved_driver_id)
        .filter(run_model.Run.start_time.is_not(None))
        .filter(run_model.Run.end_time.is_(None))
        .filter(run_model.Run.id != target_run.id)
        .first()
    )

    if existing_active_run:
        raise HTTPException(
            status_code=409,
            detail="Driver already has an active run"
        )

    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    # -------------------------------------------------------------------------
    # Require prepared stops before runtime start
    # -------------------------------------------------------------------------
    existing_stop_count = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == target_run.id)
        .count()
    )  # Determine whether this run already has its own stop plan

    if existing_stop_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Run has no stops. Prepare stops before starting the run."
        )

    # -------------------------------------------------------------------------
    # Require prepared runtime student assignments before runtime start
    # -------------------------------------------------------------------------
    existing_student_count = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == target_run.id)
        .count()
    )  # Determine whether this run already has runtime student assignments

    if existing_student_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Run has no students. Assign students before starting the run."
        )


    # -------------------------------------------------------------------------
    # Mark the selected run as started
    # -------------------------------------------------------------------------
    target_run.start_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Start timestamp
    target_run.current_stop_id = None                                        # Clear any stale planned location
    target_run.current_stop_sequence = None                                  # Reset live stop progress

    db.commit()               # Save started run only
    db.refresh(target_run)    # Reload saved run
    return _serialize_run(target_run)  # Return started run


# -----------------------------------------------------------
# - End run
# - End an active run by run id
# -----------------------------------------------------------
@router.post(
    "/end",
    response_model=schemas.RunOut,
    summary="End run",
    description="Operational runtime endpoint for ending one active run by run id.",
    response_description="Ended run",
)
def end_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")
    if run.start_time is None:
        raise HTTPException(status_code=400, detail="Run is not active")
    if run.end_time:
        raise HTTPException(status_code=400, detail="Run already ended")

    _require_posttrip_phase2_completed(run.id, db)             # Run cannot close until post-trip phase 2 is complete

    run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Set end timestamp
    db.commit()  # Save changes
    db.refresh(run)  # Reload updated run
    return run  # Return ended run


# -----------------------------------------------------------
# - End run by driver
# - End the newest active run for a specific driver
# -----------------------------------------------------------
@router.post(
    "/end_by_driver",
    response_model=schemas.RunOut,
    summary="End run by driver",
    description="Operational runtime endpoint for ending the newest active run for a specific driver.",
    response_description="Ended run",
)
def end_run_by_driver(
    driver_id: int,                         # Driver whose active run should be ended
    db: Session = Depends(get_db),          # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                      # Query Run table
        .filter(run_model.Run.driver_id == driver_id)  # Only this driver
        .filter(run_model.Run.start_time.is_not(None))  # Only started runs
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .order_by(run_model.Run.start_time.desc())  # Newest active run first
        .first()
    )

    # -------------------------------------------------------------------------
    # Validate active run exists
    # -------------------------------------------------------------------------
    if not active_run:                              # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    _require_posttrip_phase2_completed(active_run.id, db)      # Run cannot close until post-trip phase 2 is complete

    # -------------------------------------------------------------------------
    # End the active run
    # -------------------------------------------------------------------------
    active_run.end_time = datetime.now(timezone.utc).replace(tzinfo=None)  # Set end timestamp

    db.commit()                                     # Save changes
    db.refresh(active_run)                          # Reload updated run

    return active_run                               # Return ended run


# -----------------------------------------------------------
# - Complete Run
# - Mark a run as finished and lock further action updates
# -----------------------------------------------------------
@router.post(
    "/{run_id}/complete",
    response_model=RunCompleteOut,
    summary="Complete run",
    description=(
        "Mark an active run as completed, close it, and create no-show events for riders not picked up. "
        "This preserves flexible runtime stop history while locking further live rider actions."
    ),
    response_description="Run completion status",
)
def complete_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "operate")

    if not _is_run_active(run):  # Only active runs can be completed
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Prevent duplicate completion
    # -------------------------------------------------------------------------
    if run.is_completed:  # Run already finished
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is already completed",
        )

    # -------------------------------------------------------------------------
    # Mark completion fields
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC completion timestamp

    run.is_completed = True  # Lock run from further action updates
    run.completed_at = now  # Store completion time
    run.end_time = now  # Also close the run's end_time for summary/report use


    # -----------------------------------------------------------
    # Create automatic no-show events
    # - Students not picked up by completion time
    # -----------------------------------------------------------
    assignments = _get_run_assignments(run_id, db)                    # Load effective assignments for this run

    for assignment in assignments:
        if assignment.picked_up is True:                              # Skip students who boarded
            continue

        existing_no_show = (
            db.query(RunEvent)
            .filter(
                RunEvent.run_id == run.id,
                RunEvent.student_id == assignment.student_id,
                RunEvent.event_type == "STUDENT_NO_SHOW",
            )
            .first()
        )

        if existing_no_show:
            continue                                                  # Prevent duplicate no-show events

        no_show_event = RunEvent(
            run_id=run.id,
            stop_id=assignment.stop_id,                               # Keep related stop if available
            student_id=assignment.student_id,
            event_type="STUDENT_NO_SHOW",
        )

        db.add(no_show_event)                                         # Store automatic no-show event

    
    # -------------------------------------------------------------------------
    # Save changes
    # -------------------------------------------------------------------------
    db.add(run)  # Track updated run
    db.commit()  # Persist completion state
    db.refresh(run)  # Reload final values

    # -------------------------------------------------------------------------
    # Return confirmation
    # -------------------------------------------------------------------------
    return RunCompleteOut(
        id=run.id,
        is_completed=run.is_completed,
        completed_at=run.completed_at,
        message="Run completed successfully",
    )


# -----------------------------------------------------------
# - Update planned run
# - Correct the run type before the run has started
# -----------------------------------------------------------
@router.put(
    "/{run_id}",
    response_model=schemas.RunOut,
    summary="Update planned run",
    description="Update the run type for a planned run that has not started yet.",
    response_description="Updated run",
)
def update_run(
    run_id: int,
    payload: RunUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run with linked driver and route
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        "read",
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        ],
    )

    # -------------------------------------------------------------------------
    # Only planned runs may be updated
    # -------------------------------------------------------------------------
    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be updated")

    _assert_unique_route_run_type(
        route_id=run.route_id,
        normalized_run_type=payload.run_type,
        db=db,
        exclude_run_id=run.id,
    )
    run.run_type = payload.run_type  # Allow correction of the planned run label only
    if payload.scheduled_start_time is not None:
        run.scheduled_start_time = payload.scheduled_start_time  # Allow correction of planned start time before start
    if payload.scheduled_end_time is not None:
        run.scheduled_end_time = payload.scheduled_end_time  # Allow correction of planned end time before start

    db.commit()
    db.refresh(run)
    return _serialize_run(run)


# -----------------------------------------------------------
# - Delete planned run
# - Remove a run only before it has started
# -----------------------------------------------------------
@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete planned run",
    description="Delete a planned run that has not started yet.",
    response_description="Run deleted",
)
def delete_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = _get_operator_scoped_run_or_404(run_id, db, operator.id, "read")

    # -------------------------------------------------------------------------
    # Only planned runs may be deleted
    # -------------------------------------------------------------------------
    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be deleted")

    db.delete(run)
    db.commit()
    return None
