# -----------------------------------------------------------
# - Post-Trip Router
# - Submit and read per-run post-trip inspections
# -----------------------------------------------------------
from __future__ import annotations

from datetime import datetime, timezone  # Timestamp helpers

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status  # FastAPI router helpers
from sqlalchemy.orm import Session, joinedload, selectinload  # SQLAlchemy session and eager loading

from database import get_db  # Shared DB session dependency

from backend import schemas  # Shared schema exports
from backend.models.posttrip import PostTripInspection, PostTripPhoto  # Post-trip persistence models
from backend.models.route import Route  # Route model for active bus resolution
from backend.models.run import Run  # Run model for context lookup
from backend.utils.posttrip_alerts import sync_posttrip_issue_alerts, sync_posttrip_neglect_alert_if_needed  # Post-trip alert sync helpers
from backend.utils.posttrip_photos import (
    PHASE1,
    PHASE2,
    build_missing_photo_detail,
    get_required_photos_for_phase,
    remove_relative_media_file,
    require_valid_capture_token,
    save_camera_upload,
)
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
        .options(selectinload(PostTripInspection.photos))
        .filter(PostTripInspection.run_id == run_id)
        .first()
    )                                                          # One post-trip row per run


def _resolve_active_bus_id_or_400(route: Route) -> int:
    active_bus_id = route.active_bus_id or route.bus_id        # Active bus is authoritative; compatibility bus_id is fallback
    if active_bus_id is None:
        raise HTTPException(status_code=400, detail="Route has no active bus assigned")
    return active_bus_id


def _get_or_create_posttrip_inspection(*, run: Run, route: Route, db: Session) -> PostTripInspection:
    inspection = _get_posttrip_by_run(run.id, db)
    if inspection is None:
        inspection = PostTripInspection(
            run_id=run.id,
            bus_id=_resolve_active_bus_id_or_400(route),
            route_id=route.id,
            driver_id=run.driver_id,
        )
        db.add(inspection)
        db.flush()                                             # Allocate inspection id before photo rows are upserted
        inspection = _get_posttrip_by_run(run.id, db)
    if inspection is None:
        raise HTTPException(status_code=500, detail="Unable to initialize post-trip inspection")
    return inspection


def _assert_phase_is_editable(inspection: PostTripInspection, phase: str) -> None:
    if phase == PHASE1 and inspection.phase1_completed:
        raise HTTPException(status_code=400, detail="Post-Trip Phase 1 is already completed and photo replacement is locked")
    if phase == PHASE2 and inspection.phase2_completed:
        raise HTTPException(status_code=400, detail="Post-Trip Phase 2 is already completed and photo replacement is locked")


def _build_posttrip_response(inspection: PostTripInspection) -> dict[str, object]:
    decision = evaluate_posttrip_phase2_status(inspection)                  # Compute read-only post-trip decision state
    response = schemas.PostTripOut.model_validate(inspection).model_dump()  # Start from ORM-backed post-trip output
    response.update(decision)                                               # Add transient read-only decision fields
    return response


def _save_phase_photos(
    *,
    inspection: PostTripInspection,
    phase: str,
    uploads_by_field: dict[str, UploadFile | None],
    db: Session,
) -> tuple[list[str], list[str]]:
    missing_detail = build_missing_photo_detail(phase, uploads_by_field)
    if missing_detail:
        raise HTTPException(status_code=400, detail=missing_detail)

    saved_relative_paths: list[str] = []                     # New files to clean up on rollback
    previous_relative_paths: list[str] = []                  # Old files to remove after successful replacement

    existing_by_type = {photo.photo_type: photo for photo in inspection.photos}
    for requirement in get_required_photos_for_phase(phase):
        upload = uploads_by_field.get(requirement.field_name)
        if upload is None:
            raise HTTPException(status_code=400, detail="Photo required to complete this step")

        stored_file = save_camera_upload(
            upload=upload,
            run_id=inspection.run_id,
            phase=phase,
            photo_type=requirement.photo_type,
        )
        saved_relative_paths.append(stored_file["file_path"])

        photo_row = existing_by_type.get(requirement.photo_type)
        if photo_row is None:
            photo_row = PostTripPhoto(
                posttrip_inspection_id=inspection.id,
                run_id=inspection.run_id,
                phase=phase,
                photo_type=requirement.photo_type,
            )
            db.add(photo_row)
            inspection.photos.append(photo_row)
        elif photo_row.file_path != stored_file["file_path"]:
            previous_relative_paths.append(photo_row.file_path)

        photo_row.phase = phase
        photo_row.file_path = stored_file["file_path"]
        photo_row.mime_type = stored_file["mime_type"]
        photo_row.file_size_bytes = stored_file["file_size_bytes"]
        photo_row.source = stored_file["source"]
        photo_row.captured_at = stored_file["captured_at"]

    db.flush()                                               # Surface photo uniqueness or FK errors before phase flags flip
    return saved_relative_paths, previous_relative_paths


def _close_uploads(*uploads: UploadFile | None) -> None:
    for upload in uploads:
        if upload is None:
            continue
        upload.file.close()


# -----------------------------------------------------------
# - Submit post-trip phase 1
# - Create or update the run's post-trip record
# -----------------------------------------------------------
@router.post(
    "/{run_id}/posttrip/phase1",
    response_model=schemas.PostTripOut,
    status_code=status.HTTP_200_OK,
    summary="Submit Post-Trip Inspection Phase 1",
    description="Create or update the run's Post-Trip Inspection Phase 1 checklist and required camera photo using run context for ownership fields.",
    response_description="Post-Trip Inspection",
)
def submit_posttrip_phase1(
    run_id: int,
    request: Request,
    payload: schemas.PostTripPhase1Submit = Depends(schemas.PostTripPhase1Submit.as_form),
    capture_token: str = Form(...),
    phase1_rear_to_front_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    require_valid_capture_token(session=request.session, run_id=run_id, capture_token=capture_token)
    run = _get_run_with_route_or_404(run_id, db)
    route = _get_route_for_run_or_404(run, db)
    inspection = _get_or_create_posttrip_inspection(run=run, route=route, db=db)
    _assert_phase_is_editable(inspection, PHASE1)

    now = datetime.now(timezone.utc).replace(tzinfo=None)      # Shared phase 1 status timestamp
    saved_relative_paths: list[str] = []
    previous_relative_paths: list[str] = []

    try:
        inspection.bus_id = _resolve_active_bus_id_or_400(route)  # Keep ownership fields aligned to current run context
        inspection.route_id = route.id
        inspection.driver_id = run.driver_id

        saved_relative_paths, previous_relative_paths = _save_phase_photos(
            inspection=inspection,
            phase=PHASE1,
            uploads_by_field={
                "phase1_rear_to_front_image": phase1_rear_to_front_image,
            },
            db=db,
        )

        inspection.phase1_no_students_remaining = payload.phase1_no_students_remaining
        inspection.phase1_belongings_checked = payload.phase1_belongings_checked
        inspection.phase1_checked_sign_hung = payload.phase1_checked_sign_hung
        inspection.phase1_completed = True
        inspection.phase1_completed_at = now
        if inspection.phase2_completed is not True:
            inspection.phase2_pending_since = now              # Phase 2 becomes the next pending step after phase 1
            inspection.phase2_status = "pending"
        inspection.last_driver_activity_at = now              # Track latest meaningful post-trip interaction

        db.commit()
    except Exception:
        db.rollback()
        for relative_path in saved_relative_paths:
            remove_relative_media_file(relative_path)
        raise
    finally:
        _close_uploads(phase1_rear_to_front_image)

    for relative_path in previous_relative_paths:
        remove_relative_media_file(relative_path)

    inspection = _get_posttrip_by_run(run.id, db)
    if inspection is None:
        raise HTTPException(status_code=500, detail="Unable to reload post-trip inspection")
    return _build_posttrip_response(inspection)


# -----------------------------------------------------------
# - Submit post-trip phase 2
# - Update the existing run post-trip record
# -----------------------------------------------------------
@router.post(
    "/{run_id}/posttrip/phase2",
    response_model=schemas.PostTripOut,
    status_code=status.HTTP_200_OK,
    summary="Submit Post-Trip Inspection Phase 2",
    description="Update the run's Post-Trip Inspection Phase 2 checklist and required camera photos after Phase 1 exists.",
    response_description="Post-Trip Inspection",
)
def submit_posttrip_phase2(
    run_id: int,
    request: Request,
    payload: schemas.PostTripPhase2Submit = Depends(schemas.PostTripPhase2Submit.as_form),
    capture_token: str = Form(...),
    phase2_rear_to_front_image: UploadFile | None = File(None),
    phase2_cleared_sign_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    require_valid_capture_token(session=request.session, run_id=run_id, capture_token=capture_token)
    _get_run_with_route_or_404(run_id, db)

    inspection = _get_posttrip_by_run(run_id, db)
    if inspection is None or inspection.phase1_completed is not True:
        _close_uploads(phase2_rear_to_front_image, phase2_cleared_sign_image)
        raise HTTPException(status_code=400, detail="Post-Trip Inspection Phase 1 must be completed first")

    _assert_phase_is_editable(inspection, PHASE2)

    now = datetime.now(timezone.utc).replace(tzinfo=None)      # Shared phase 2 completion timestamp
    saved_relative_paths: list[str] = []
    previous_relative_paths: list[str] = []

    try:
        saved_relative_paths, previous_relative_paths = _save_phase_photos(
            inspection=inspection,
            phase=PHASE2,
            uploads_by_field={
                "phase2_rear_to_front_image": phase2_rear_to_front_image,
                "phase2_cleared_sign_image": phase2_cleared_sign_image,
            },
            db=db,
        )

        inspection.phase2_full_internal_recheck = payload.phase2_full_internal_recheck
        inspection.phase2_checked_to_cleared_switched = payload.phase2_checked_to_cleared_switched
        inspection.phase2_rear_button_triggered = payload.phase2_rear_button_triggered
        inspection.exterior_status = payload.exterior_status
        inspection.exterior_description = payload.exterior_description
        inspection.phase2_completed = True
        inspection.phase2_completed_at = now
        inspection.phase2_status = "completed"
        inspection.last_driver_activity_at = now              # Track latest meaningful post-trip interaction

        db.flush()                                             # Ensure updated post-trip state is visible to alert sync
        sync_posttrip_issue_alerts(inspection=inspection, db=db)  # Create or resolve post-trip major-defect alerts
        db.commit()
    except Exception:
        db.rollback()
        for relative_path in saved_relative_paths:
            remove_relative_media_file(relative_path)
        raise
    finally:
        _close_uploads(phase2_rear_to_front_image, phase2_cleared_sign_image)

    for relative_path in previous_relative_paths:
        remove_relative_media_file(relative_path)

    inspection = _get_posttrip_by_run(run_id, db)
    if inspection is None:
        raise HTTPException(status_code=500, detail="Unable to reload post-trip inspection")
    return _build_posttrip_response(inspection)


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

    inspection = _get_posttrip_by_run(run_id, db)
    if inspection is None:
        raise HTTPException(status_code=500, detail="Unable to reload post-trip inspection")
    response = schemas.PostTripOut.model_validate(inspection).model_dump()  # Start from ORM-backed post-trip output
    response.update(decision)                                               # Add transient read-only decision fields
    return response
