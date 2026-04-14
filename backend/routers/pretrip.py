# -----------------------------------------------------------
# Pre-Trip Inspection Router
# - Create and read bus/day Pre-Trip Inspection records
# -----------------------------------------------------------
from datetime import date, datetime, timezone  # Date and timestamp helpers

from fastapi import APIRouter, Depends, HTTPException, Query, status  # FastAPI router helpers
from sqlalchemy.orm import Session, selectinload  # SQLAlchemy session and eager loading

from database import get_db  # Shared DB session dependency

from backend import schemas  # Shared schema exports
from backend.models.bus import Bus  # Bus model for FK validation
from backend.models.operator import Operator  # Operator model for tenant context
from backend.models.pretrip import PreTripDefect, PreTripInspection  # Pre-trip persistence models
from backend.models.yard import Yard
from backend.utils.operator_scope import get_operator_context  # Tenant auth dependency
from backend.utils.pretrip_alerts import sync_pretrip_issue_alerts  # Pre-trip alert sync helpers


router = APIRouter(prefix="/pretrips", tags=["Pre-Trip Inspection"])


def _get_pretrip_or_404(pretrip_id: int, db: Session, operator_id: int) -> PreTripInspection:
    inspection = (
        db.query(PreTripInspection)
        .options(
            selectinload(PreTripInspection.bus),
            selectinload(PreTripInspection.defects),
        )
        .join(Bus, PreTripInspection.bus_id == Bus.id)
        .join(Bus.yard)
        .filter(PreTripInspection.id == pretrip_id)
        .filter(Yard.operator_id == operator_id)
        .first()
    )                                                          # Load one inspection with nested defects, operator-scoped
    if not inspection:
        raise HTTPException(status_code=404, detail="Pre-Trip Inspection not found")
    return inspection


def _get_bus_by_number_or_404(bus_number: str, db: Session, operator_id: int) -> Bus:
    bus = (
        db.query(Bus)
        .join(Bus.yard)
        .filter(Bus.unit_number == bus_number)
        .filter(Yard.operator_id == operator_id)
        .first()
    )                                                          # Resolve the user-facing bus number within operator only
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    return bus


def _resolve_bus_or_404(
    payload: schemas.PreTripCreate | schemas.PreTripCorrect,
    db: Session,
    operator_id: int,
) -> Bus:
    if payload.bus_id is not None:
        bus = (
            db.query(Bus)
            .join(Bus.yard)
            .filter(Bus.id == payload.bus_id)
            .filter(Yard.operator_id == operator_id)
            .first()
        )                                                      # Scope bus_id resolution to operator
        if not bus:
            raise HTTPException(status_code=404, detail="Bus not found")
        return bus

    if payload.bus_number:
        return _get_bus_by_number_or_404(payload.bus_number, db, operator_id)

    raise HTTPException(status_code=400, detail="Invalid bus reference")


def _assert_pretrip_unique_for_bus_day(
    *,
    bus_id: int,
    inspection_date: date,
    db: Session,
    exclude_pretrip_id: int | None = None,
) -> None:
    query = (
        db.query(PreTripInspection)
        .filter(PreTripInspection.bus_id == bus_id)
        .filter(PreTripInspection.inspection_date == inspection_date)
    )                                                          # One pre-trip per bus/day
    if exclude_pretrip_id is not None:
        query = query.filter(PreTripInspection.id != exclude_pretrip_id)

    if query.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pre-Trip Inspection already exists for this bus today",
        )


def _assert_inspection_date_is_today(inspection_date: date) -> None:
    if inspection_date != date.today():
        raise HTTPException(status_code=400, detail="Inspection date must be today")


def _replace_pretrip_defects(
    *,
    inspection: PreTripInspection,
    defects: list[schemas.PreTripDefectCreate],
) -> None:
    inspection.defects.clear()                                 # Replace the final defect set atomically
    inspection.defects.extend(
        PreTripDefect(
            description=defect.description,
            severity=defect.severity,
        )
        for defect in defects
    )


def _serialize_pretrip_snapshot(inspection: PreTripInspection) -> dict:
    return {
        "bus_number": inspection.bus_number,
        "license_plate": inspection.license_plate,
        "driver_name": inspection.driver_name,
        "inspection_date": inspection.inspection_date.isoformat(),
        "inspection_time": inspection.inspection_time.isoformat(),
        "odometer": inspection.odometer,
        "inspection_place": inspection.inspection_place,
        "use_type": inspection.use_type,
        "brakes_checked": inspection.brakes_checked,
        "lights_checked": inspection.lights_checked,
        "tires_checked": inspection.tires_checked,
        "emergency_equipment_checked": inspection.emergency_equipment_checked,
        "fit_for_duty": inspection.fit_for_duty,
        "no_defects": inspection.no_defects,
        "signature": inspection.signature,
        "defects": [
            {
                "description": defect.description,
                "severity": defect.severity,
            }
            for defect in inspection.defects
        ],
    }                                                          # Preserve the prior final payload before correction


# -----------------------------------------------------------
# - Create Pre-Trip Inspection
# - Submit one final bus/day Pre-Trip Inspection with nested defects
# -----------------------------------------------------------
@router.post(
    "/",
    response_model=schemas.PreTripOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Pre-Trip Inspection",
    description="Create one final submitted Pre-Trip Inspection for a bus and inspection date with nested defect rows.",
    response_description="Created Pre-Trip Inspection",
)
def create_pretrip(
    payload: schemas.PreTripCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    bus = _resolve_bus_or_404(payload, db, operator.id)
    _assert_inspection_date_is_today(payload.inspection_date)
    _assert_pretrip_unique_for_bus_day(
        bus_id=bus.id,
        inspection_date=payload.inspection_date,
        db=db,
    )

    inspection = PreTripInspection(
        bus_id=bus.id,
        license_plate=payload.license_plate,
        driver_name=payload.driver_name,
        inspection_date=payload.inspection_date,
        inspection_time=payload.inspection_time,
        odometer=payload.odometer,
        inspection_place=payload.inspection_place,
        use_type=payload.use_type,
        brakes_checked=payload.brakes_checked,
        lights_checked=payload.lights_checked,
        tires_checked=payload.tires_checked,
        emergency_equipment_checked=payload.emergency_equipment_checked,
        fit_for_duty=payload.fit_for_duty,
        no_defects=payload.no_defects,
        signature=payload.signature,
    )
    _replace_pretrip_defects(inspection=inspection, defects=payload.defects)

    db.add(inspection)
    db.flush()                                                 # Allocate inspection id before syncing alerts
    sync_pretrip_issue_alerts(inspection=inspection, db=db)    # Create or resolve pre-trip issue alerts
    db.commit()
    db.refresh(inspection)
    return _get_pretrip_or_404(inspection.id, db, operator.id)


# -----------------------------------------------------------
# - List Pre-Trip Inspections
# - Return newest-first Pre-Trip Inspections with optional simple filters
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=list[schemas.PreTripOut],
    summary="List Pre-Trip Inspections",
    description="Return submitted Pre-Trip Inspections ordered newest first with optional bus and date filters.",
    response_description="Pre-Trip Inspection list",
)
def list_pretrips(
    bus_id: int | None = Query(default=None),
    inspection_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    query = (
        db.query(PreTripInspection)
        .options(
            selectinload(PreTripInspection.bus),
            selectinload(PreTripInspection.defects),
        )
        .join(Bus, PreTripInspection.bus_id == Bus.id)
        .join(Bus.yard)
        .filter(Yard.operator_id == operator.id)
    )                                                          # Base pre-trip query scoped to operator

    if bus_id is not None:
        bus = (
            db.query(Bus)
            .join(Bus.yard)
            .filter(Bus.id == bus_id)
            .filter(Yard.operator_id == operator.id)
            .first()
        )
        if not bus:
            raise HTTPException(status_code=404, detail="Bus not found")
        query = query.filter(PreTripInspection.bus_id == bus_id)

    if inspection_date is not None:
        query = query.filter(PreTripInspection.inspection_date == inspection_date)

    return (
        query.order_by(
            PreTripInspection.inspection_date.desc(),
            PreTripInspection.inspection_time.desc(),
            PreTripInspection.id.desc(),
        )
        .all()
    )


# -----------------------------------------------------------
# - Get Pre-Trip Inspection
# - Return one submitted Pre-Trip Inspection with nested defects
# -----------------------------------------------------------
@router.get(
    "/{pretrip_id}",
    response_model=schemas.PreTripOut,
    summary="Get Pre-Trip Inspection",
    description="Return one submitted Pre-Trip Inspection by id with nested defect rows.",
    response_description="Pre-Trip Inspection detail",
)
def get_pretrip(
    pretrip_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return _get_pretrip_or_404(pretrip_id, db, operator.id)


# -----------------------------------------------------------
# - Get today's bus Pre-Trip Inspection
# - Return today's submitted bus/day inspection when present
# -----------------------------------------------------------
@router.get(
    "/bus/{bus_id}/today",
    response_model=schemas.PreTripOut,
    summary="Get today's bus Pre-Trip Inspection",
    description="Return today's submitted Pre-Trip Inspection for the selected bus when it exists.",
    response_description="Today's bus Pre-Trip Inspection",
)
def get_bus_pretrip_today(
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    bus = (
        db.query(Bus)
        .join(Bus.yard)
        .filter(Bus.id == bus_id)
        .filter(Yard.operator_id == operator.id)
        .first()
    )
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")

    inspection = (
        db.query(PreTripInspection)
        .options(
            selectinload(PreTripInspection.bus),
            selectinload(PreTripInspection.defects),
        )
        .filter(PreTripInspection.bus_id == bus_id)
        .filter(PreTripInspection.inspection_date == date.today())
        .first()
    )                                                          # Today's bus/day inspection only
    if not inspection:
        raise HTTPException(status_code=404, detail="Pre-Trip Inspection not found")

    return inspection


# -----------------------------------------------------------
# - List bus Pre-Trip Inspections
# - Return newest-first submitted Pre-Trip Inspections for one bus
# -----------------------------------------------------------
@router.get(
    "/bus/{bus_id}",
    response_model=list[schemas.PreTripOut],
    summary="List bus Pre-Trip Inspections",
    description="Return submitted Pre-Trip Inspections for one bus ordered newest first.",
    response_description="Bus Pre-Trip Inspection list",
)
def list_bus_pretrips(
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    bus = (
        db.query(Bus)
        .join(Bus.yard)
        .filter(Bus.id == bus_id)
        .filter(Yard.operator_id == operator.id)
        .first()
    )
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")

    return (
        db.query(PreTripInspection)
        .options(
            selectinload(PreTripInspection.bus),
            selectinload(PreTripInspection.defects),
        )
        .filter(PreTripInspection.bus_id == bus_id)
        .order_by(
            PreTripInspection.inspection_date.desc(),
            PreTripInspection.inspection_time.desc(),
            PreTripInspection.id.desc(),
        )
        .all()
    )


# -----------------------------------------------------------
# - Correct Pre-Trip Inspection
# - Overwrite the final record while preserving prior payload
# -----------------------------------------------------------
@router.put(
    "/{pretrip_id}/correct",
    response_model=schemas.PreTripOut,
    summary="Correct Pre-Trip Inspection",
    description="Overwrite a submitted Pre-Trip Inspection, preserve the prior final payload, and replace defect rows with the corrected final version.",
    response_description="Corrected Pre-Trip Inspection",
)
def correct_pretrip(
    pretrip_id: int,
    payload: schemas.PreTripCorrect,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    inspection = _get_pretrip_or_404(pretrip_id, db, operator.id)
    bus = _resolve_bus_or_404(payload, db, operator.id)
    _assert_inspection_date_is_today(payload.inspection_date)
    _assert_pretrip_unique_for_bus_day(
        bus_id=bus.id,
        inspection_date=payload.inspection_date,
        db=db,
        exclude_pretrip_id=inspection.id,
    )

    inspection.original_payload = _serialize_pretrip_snapshot(inspection)  # Keep prior final values before overwrite
    inspection.bus_id = bus.id
    inspection.license_plate = payload.license_plate
    inspection.driver_name = payload.driver_name
    inspection.inspection_date = payload.inspection_date
    inspection.inspection_time = payload.inspection_time
    inspection.odometer = payload.odometer
    inspection.inspection_place = payload.inspection_place
    inspection.use_type = payload.use_type
    inspection.brakes_checked = payload.brakes_checked
    inspection.lights_checked = payload.lights_checked
    inspection.tires_checked = payload.tires_checked
    inspection.emergency_equipment_checked = payload.emergency_equipment_checked
    inspection.fit_for_duty = payload.fit_for_duty
    inspection.no_defects = payload.no_defects
    inspection.signature = payload.signature
    inspection.is_corrected = True
    inspection.corrected_by = payload.corrected_by
    inspection.corrected_at = datetime.now(timezone.utc).replace(tzinfo=None)

    _replace_pretrip_defects(inspection=inspection, defects=payload.defects)

    db.flush()                                                 # Ensure corrected row and defects are visible to alert sync
    sync_pretrip_issue_alerts(inspection=inspection, db=db)    # Reconcile pre-trip issue alerts after correction
    db.commit()
    db.refresh(inspection)
    return _get_pretrip_or_404(inspection.id, db, operator.id)

