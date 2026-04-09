# -----------------------------------------------------------
# - Post-Trip Router
# - Submit and read per-run post-trip inspections
# -----------------------------------------------------------
from datetime import datetime, timezone  # Timestamp helpers

from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI router helpers
from sqlalchemy.orm import Session, joinedload  # SQLAlchemy session and eager loading

from database import get_db  # Shared DB session dependency

from backend import schemas  # Shared schema exports
from backend.models.posttrip import PostTripInspection  # Post-trip persistence model
from backend.models.route import Route  # Route model for active bus resolution
from backend.models.run import Run  # Run model for context lookup
from backend.utils.posttrip_alerts import sync_posttrip_issue_alerts, sync_posttrip_neglect_alert_if_needed  # Post-trip alert sync helpers
from backend.utils.posttrip_status import evaluate_posttrip_phase2_status  # Read-only post-trip decision helper


router = APIRouter(prefix="/runs", tags=["Post-Trip Inspection"])


# -----------------------------------------------------------
# - Post-trip helpers
# - Resolve run context and the linked post-trip row safely
# -----------------------------------------------------------
def _get_run_with_route_or_404(run_id: int, db: Session) -> Run:
    run = (
        db.query(Run)
        .options(joinedload(Run.route))
        .filter(Run.id == run_id)
        .first()
    )                                                          # Load run with route for post-trip ownership fields
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _get_route_for_run_or_404(run: Run, db: Session) -> Route:
    route = run.route or db.get(Route, run.route_id)           # Prefer loaded route, fallback to direct lookup
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


def _get_posttrip_by_run(run_id: int, db: Session) -> PostTripInspection | None:
    return (
        db.query(PostTripInspection)
        .filter(PostTripInspection.run_id == run_id)
        .first()
    )                                                          # One post-trip row per run


def _resolve_active_bus_id_or_400(route: Route) -> int:
    active_bus_id = route.active_bus_id or route.bus_id        # Active bus is authoritative; compatibility bus_id is fallback
    if active_bus_id is None:
        raise HTTPException(status_code=400, detail="Route has no active bus assigned")
    return active_bus_id


# -----------------------------------------------------------
# - Submit post-trip phase 1
# - Create or update the run's post-trip record
# -----------------------------------------------------------
@router.post(
    "/{run_id}/posttrip/phase1",
    response_model=schemas.PostTripOut,
    status_code=status.HTTP_200_OK,
    summary="Submit Post-Trip Inspection Phase 1",
    description="Create or update the run's Post-Trip Inspection Phase 1 checklist using run context for ownership fields.",
    response_description="Post-Trip Inspection",
)
def submit_posttrip_phase1(
    run_id: int,
    payload: schemas.PostTripPhase1Submit,
    db: Session = Depends(get_db),
):
    run = _get_run_with_route_or_404(run_id, db)
    route = _get_route_for_run_or_404(run, db)
    active_bus_id = _resolve_active_bus_id_or_400(route)

    inspection = _get_posttrip_by_run(run.id, db)
    if inspection is None:
        inspection = PostTripInspection(
            run_id=run.id,
            bus_id=active_bus_id,
            route_id=route.id,
            driver_id=run.driver_id,
        )
        db.add(inspection)

    now = datetime.now(timezone.utc).replace(tzinfo=None)      # Shared phase 1 status timestamp
    inspection.bus_id = active_bus_id                         # Keep ownership fields aligned to current run context
    inspection.route_id = route.id
    inspection.driver_id = run.driver_id
    inspection.phase1_no_students_remaining = payload.phase1_no_students_remaining
    inspection.phase1_belongings_checked = payload.phase1_belongings_checked
    inspection.phase1_checked_sign_hung = payload.phase1_checked_sign_hung
    inspection.phase1_completed = True
    inspection.phase1_completed_at = now
    if inspection.phase2_completed is not True:
        inspection.phase2_pending_since = now                  # Phase 2 becomes the next pending step after phase 1
        inspection.phase2_status = "pending"
    inspection.last_driver_activity_at = now                  # Track latest meaningful post-trip interaction

    db.commit()
    db.refresh(inspection)
    return inspection


# -----------------------------------------------------------
# - Submit post-trip phase 2
# - Update the existing run post-trip record
# -----------------------------------------------------------
@router.post(
    "/{run_id}/posttrip/phase2",
    response_model=schemas.PostTripOut,
    status_code=status.HTTP_200_OK,
    summary="Submit Post-Trip Inspection Phase 2",
    description="Update the run's Post-Trip Inspection Phase 2 checklist after Phase 1 exists.",
    response_description="Post-Trip Inspection",
)
def submit_posttrip_phase2(
    run_id: int,
    payload: schemas.PostTripPhase2Submit,
    db: Session = Depends(get_db),
):
    _get_run_with_route_or_404(run_id, db)

    inspection = _get_posttrip_by_run(run_id, db)
    if inspection is None or inspection.phase1_completed is not True:
        raise HTTPException(status_code=400, detail="Post-Trip Inspection Phase 1 must be completed first")

    now = datetime.now(timezone.utc).replace(tzinfo=None)      # Shared phase 2 completion timestamp
    inspection.phase2_full_internal_recheck = payload.phase2_full_internal_recheck
    inspection.phase2_checked_to_cleared_switched = payload.phase2_checked_to_cleared_switched
    inspection.phase2_rear_button_triggered = payload.phase2_rear_button_triggered
    inspection.exterior_status = payload.exterior_status
    inspection.exterior_description = payload.exterior_description
    inspection.phase2_completed = True
    inspection.phase2_completed_at = now
    inspection.phase2_status = "completed"
    inspection.last_driver_activity_at = now                  # Track latest meaningful post-trip interaction

    db.flush()                                                 # Ensure updated post-trip state is visible to alert sync
    sync_posttrip_issue_alerts(inspection=inspection, db=db)   # Create or resolve post-trip major-defect alerts
    db.commit()
    db.refresh(inspection)
    return inspection


# -----------------------------------------------------------
# - Get post-trip by run
# - Return the stored post-trip inspection for one run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/posttrip",
    response_model=schemas.PostTripOut,
    summary="Get Post-Trip Inspection by Run",
    description="Return the Post-Trip Inspection linked to the selected run.",
    response_description="Post-Trip Inspection",
)
def get_posttrip_by_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    _get_run_with_route_or_404(run_id, db)

    inspection = _get_posttrip_by_run(run_id, db)
    if inspection is None:
        raise HTTPException(status_code=404, detail="Post-Trip Inspection not found")

    decision = evaluate_posttrip_phase2_status(inspection)                  # Compute read-only post-trip decision state
    sync_posttrip_neglect_alert_if_needed(
        inspection=inspection,
        decision=decision,
        db=db,
    )                                                                      # Read-triggered neglect alert sync only
    db.commit()

    response = schemas.PostTripOut.model_validate(inspection).model_dump()  # Start from ORM-backed post-trip output
    response.update(decision)                                               # Add transient read-only decision fields
    return response
