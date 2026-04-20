# ===========================================================
# backend/routers/run_actions.py - FleetOS Run Actions Router
# -----------------------------------------------------------
# Runtime action endpoints split from the main run router.
# ===========================================================

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db

from backend import schemas
from backend.models.operator import Operator
from backend.models.run_event import RunEvent
from backend.schemas.run import (
    DropoffStudentRequest,
    DropoffStudentResponse,
    PickupStudentRequest,
    PickupStudentResponse,
)
from backend.utils.operator_scope import get_operator_context
from backend.routers.run_execution_helpers import (
    _assert_dropoff_transition_allowed,
    _assert_pickup_transition_allowed,
    _get_execution_scoped_run_or_404,
    _get_ordered_run_stops,
    _get_runtime_assignment_or_404,
    _get_runtime_run_or_404,
    _require_active_runtime_run,
    _require_current_runtime_stop,
    _resolve_runtime_stop_target_or_404,
    _set_run_current_stop,
)


router = APIRouter(tags=["Runs"])


# -----------------------------------------------------------
# Execution Action Endpoints
# -----------------------------------------------------------
# -----------------------------------------------------------
# - Arrive at stop
# - Mark actual runtime position with flexible stop movement
# -----------------------------------------------------------
@router.post(
    "/{run_id}/arrive_stop",
    response_model=schemas.RunOut,
    summary="Arrive at stop",
    description=(
        "Mark the run as arrived at an actual stop and update the live runtime location. "
        "Flexible stop execution is allowed: drivers may revisit earlier stops, jump ahead, or skip planned stops. "
        "Compatibility stop_sequence input remains supported, and optional stop_id may be used when available."
    ),
    response_description="Updated run state",
)
def arrive_at_stop(
    run_id: int,
    stop_sequence: int | None = Query(None, ge=1),  # Compatibility stop-sequence target
    stop_id: int | None = Query(None, ge=1),        # Optional explicit stop target for flexible movement
    db: Session = Depends(get_db),                  # Database session dependency
    operator: Operator = Depends(get_operator_context),
):
    _get_execution_scoped_run_or_404(run_id, db, operator.id)
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    stop = _resolve_runtime_stop_target_or_404(
        run_id=run_id,
        stop_id=stop_id,
        stop_sequence=stop_sequence,
        db=db,
    )                                                          # Allow explicit jumps, revisits, and backward movement

    return _set_run_current_stop(run=run, stop=stop, db=db)


# =============================================================================
# POST /runs/{run_id}/next_stop
# -----------------------------------------------------------------------------
# Purpose:
#   Convenience helper for moving to the next configured stop in stable order.
#   Flexible execution still uses arrive_stop as the authoritative location
#   setter, including revisits, backward movement, and jumps.
# =============================================================================
@router.post(
    "/{run_id}/next_stop",
    response_model=schemas.RunOut,
    summary="Advance to next configured stop (compatibility helper)",
    description=(
        "Compatibility convenience helper that moves the active run to the next configured stop in ordered stop-list order. "
        "This endpoint does not enforce the overall execution model; drivers may still use POST /runs/{run_id}/arrive_stop "
        "to revisit earlier stops, jump ahead, skip stops, or otherwise reflect actual runtime location."
    ),
    response_description="Updated run state",
)
def advance_to_next_stop(
    run_id: int,
    db: Session = Depends(get_db),                  # Database session dependency
    operator: Operator = Depends(get_operator_context),
):
    _get_execution_scoped_run_or_404(run_id, db, operator.id)
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    stops = _get_ordered_run_stops(run_id, db)      # Stable ordered list for convenience-only navigation

    if not stops:
        raise HTTPException(status_code=404, detail="No stops found for this run")

    if run.current_stop_id is None:
        next_stop = stops[0]                        # First convenience move starts at the first configured stop
    else:
        current_index = next(
            (index for index, stop in enumerate(stops) if stop.id == run.current_stop_id),
            None,
        )                                           # Resolve ordered position from the current actual stop id

        if current_index is None:
            next_stop = next(
                (
                    stop
                    for stop in stops
                    if run.current_stop_sequence is None or stop.sequence > run.current_stop_sequence
                ),
                None,
            )                                       # Conservative fallback if stored stop id is stale
        elif current_index + 1 < len(stops):
            next_stop = stops[current_index + 1]    # Move to the next configured stop in stable order
        else:
            next_stop = None                        # No later configured stop remains

    if not next_stop:
        raise HTTPException(status_code=404, detail="No next stop found for this run")

    return _set_run_current_stop(run=run, stop=next_stop, db=db)


# -----------------------------------------------------------
# - Pick up student
# - Record boarding at the run's current actual stop
# -----------------------------------------------------------
@router.post(
    "/{run_id}/pickup_student",
    response_model=PickupStudentResponse,
    summary="Pick up student",
    description=(
        "Mark a student as picked up at the run's current actual stop and log a PICKUP event. "
        "Rider actions follow the actual runtime location source of truth, not forward-only planned progression."
    ),
    response_description="Pickup confirmation",
)
def pickup_student(
    run_id: int,
    payload: PickupStudentRequest,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_execution_scoped_run_or_404(run_id, db, operator.id)
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    current_stop = _require_current_runtime_stop(run, db)  # Pickup must happen at the actual current stop
    assignment = _get_runtime_assignment_or_404(
        run_id=run_id,
        student_id=payload.student_id,
        db=db,
    )

    # -------------------------------------------------------------------------
    # Validate pickup transition from current runtime rider state
    # -------------------------------------------------------------------------
    _assert_pickup_transition_allowed(assignment)

    # -------------------------------------------------------------------------
    # Mark pickup fields using the current actual stop
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)
    
    assignment.picked_up = True  # Student has boarded
    assignment.picked_up_at = now  # Store pickup time
    assignment.is_onboard = True  # Student is now physically on the bus
    assignment.actual_pickup_stop_id = current_stop.id  # Record the actual boarding stop

    # -----------------------------------------------------------
    # Log pickup event
    # - Records actual stop used for pickup
    # -----------------------------------------------------------
    event = RunEvent(
        run_id=run.id,
        stop_id=current_stop.id,
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


# -----------------------------------------------------------
# - Drop off student
# - Record drop-off at the run's current actual stop
# -----------------------------------------------------------
@router.post(
    "/{run_id}/dropoff_student",
    response_model=DropoffStudentResponse,
    summary="Drop off student",
    description=(
        "Mark a student as dropped off at the run's current actual stop and log a DROPOFF event. "
        "Rider actions follow the actual runtime location source of truth, not forward-only planned progression."
    ),
    response_description="Drop-off confirmation",
)
def dropoff_student(
    run_id: int,
    payload: DropoffStudentRequest,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_execution_scoped_run_or_404(run_id, db, operator.id)
    run = _require_active_runtime_run(_get_runtime_run_or_404(run_id, db))
    current_stop = _require_current_runtime_stop(run, db)  # Dropoff must happen at the actual current stop
    assignment = _get_runtime_assignment_or_404(
        run_id=run_id,
        student_id=payload.student_id,
        db=db,
    )

    # -------------------------------------------------------------------------
    # Validate dropoff transition from current runtime rider state
    # -------------------------------------------------------------------------
    _assert_dropoff_transition_allowed(assignment)

    # -------------------------------------------------------------------------
    # Mark drop-off fields using the current actual stop
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc)  # Current UTC timestamp (timezone-aware)

    assignment.dropped_off = True  # Student has been dropped off
    assignment.dropped_off_at = now  # Store drop-off time
    assignment.is_onboard = False  # Student is no longer on the bus
    assignment.actual_dropoff_stop_id = current_stop.id  # Record the actual drop-off stop

    # -----------------------------------------------------------
    # Log DROPOFF event
    # - Records actual stop used for dropoff
    # -----------------------------------------------------------
    event = RunEvent(                                                        # Build dropoff event
        run_id=run.id,                                                       # Parent run
        stop_id=current_stop.id,                                             # Actual dropoff stop
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
