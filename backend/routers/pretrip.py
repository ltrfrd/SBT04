# -----------------------------------------------------------
# Pre-Trip Router
# - Create, read, list, and correct bus/day pre-trip records
# -----------------------------------------------------------
from datetime import date, datetime, timezone  # Date and timestamp helpers

from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI router helpers
from sqlalchemy.orm import Session, selectinload  # SQLAlchemy session and eager loading

from database import get_db  # Shared DB session dependency

from backend import schemas  # Shared schema exports
from backend.models.bus import Bus  # Bus model for FK validation
from backend.models.pretrip import PreTripDefect, PreTripInspection  # Pre-trip persistence models
from backend.utils.pretrip_alerts import sync_pretrip_issue_alerts  # Alert sync helpers


router = APIRouter(prefix="/pretrips", tags=["PreTrips"])


# -----------------------------------------------------------
# - Pre-trip helpers
# - Keep duplicate checks and correction snapshots explicit
# -----------------------------------------------------------
def _get_pretrip_or_404(pretrip_id: int, db: Session) -> PreTripInspection:
    inspection = (
        db.query(PreTripInspection)
        .options(
            selectinload(PreTripInspection.bus),
            selectinload(PreTripInspection.defects),
        )
        .filter(PreTripInspection.id == pretrip_id)
        .first()
    )                                                          # Load one inspection with nested defects
    if not inspection:
        raise HTTPException(status_code=404, detail="Pre-trip not found")
    return inspection


def _get_bus_by_number_or_404(bus_number: str, db: Session) -> Bus:
    bus = (
        db.query(Bus)
        .filter(Bus.unit_number == bus_number)
        .first()
    )                                                          # Resolve the user-facing bus number to the stored bus row
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    return bus


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
            detail="Pre-trip already exists for this bus and inspection date",
        )


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
# - Create pre-trip
# - Submit one final bus/day pre-trip with nested defects
# -----------------------------------------------------------
@router.post(
    "/",
    response_model=schemas.PreTripOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create pre-trip",
    description="Create one final submitted pre-trip inspection for a bus and inspection date with nested defect rows.",
    response_description="Created pre-trip",
)
def create_pretrip(
    payload: schemas.PreTripCreate,
    db: Session = Depends(get_db),
):
    bus = _get_bus_by_number_or_404(payload.bus_number, db)
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
        fit_for_duty=payload.fit_for_duty,
        no_defects=payload.no_defects,
        signature=payload.signature,
    )
    _replace_pretrip_defects(inspection=inspection, defects=payload.defects)

    db.add(inspection)
    db.flush()                                                 # Allocate inspection id before creating alerts
    sync_pretrip_issue_alerts(inspection=inspection, db=db)    # Create or resolve pre-trip issue alerts
    db.commit()
    db.refresh(inspection)
    return _get_pretrip_or_404(inspection.id, db)


# -----------------------------------------------------------
# - Get pre-trip
# - Return one submitted pre-trip with nested defects
# -----------------------------------------------------------
@router.get(
    "/{pretrip_id}",
    response_model=schemas.PreTripOut,
    summary="Get pre-trip",
    description="Return one submitted pre-trip inspection by id with nested defect rows.",
    response_description="Pre-trip detail",
)
def get_pretrip(pretrip_id: int, db: Session = Depends(get_db)):
    return _get_pretrip_or_404(pretrip_id, db)


# -----------------------------------------------------------
# - Get today's bus pre-trip
# - Return today's submitted bus/day inspection when present
# -----------------------------------------------------------
@router.get(
    "/bus/{bus_id}/today",
    response_model=schemas.PreTripOut,
    summary="Get today's bus pre-trip",
    description="Return today's submitted pre-trip inspection for the selected bus when it exists.",
    response_description="Today's bus pre-trip",
)
def get_bus_pretrip_today(bus_id: int, db: Session = Depends(get_db)):
    if not db.get(Bus, bus_id):
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
        raise HTTPException(status_code=404, detail="Pre-trip not found")

    return inspection


# -----------------------------------------------------------
# - List bus pre-trips
# - Return newest-first submitted pre-trips for one bus
# -----------------------------------------------------------
@router.get(
    "/bus/{bus_id}",
    response_model=list[schemas.PreTripOut],
    summary="List bus pre-trips",
    description="Return submitted pre-trip inspections for one bus ordered newest first.",
    response_description="Bus pre-trip list",
)
def list_bus_pretrips(bus_id: int, db: Session = Depends(get_db)):
    if not db.get(Bus, bus_id):
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
# - Correct pre-trip
# - Overwrite the final record while preserving prior payload
# -----------------------------------------------------------
@router.put(
    "/{pretrip_id}/correct",
    response_model=schemas.PreTripOut,
    summary="Correct pre-trip",
    description="Overwrite a submitted pre-trip, preserve the prior final payload, and replace defect rows with the corrected final version.",
    response_description="Corrected pre-trip",
)
def correct_pretrip(
    pretrip_id: int,
    payload: schemas.PreTripCorrect,
    db: Session = Depends(get_db),
):
    inspection = _get_pretrip_or_404(pretrip_id, db)
    bus = _get_bus_by_number_or_404(payload.bus_number, db)
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
    inspection.fit_for_duty = payload.fit_for_duty
    inspection.no_defects = payload.no_defects
    inspection.signature = payload.signature
    inspection.is_corrected = True
    inspection.corrected_by = payload.corrected_by
    inspection.corrected_at = datetime.now(timezone.utc).replace(tzinfo=None)

    _replace_pretrip_defects(inspection=inspection, defects=payload.defects)

    db.flush()                                                 # Ensure corrected row and defects are available to alert sync
    sync_pretrip_issue_alerts(inspection=inspection, db=db)    # Create or resolve pre-trip issue alerts
    db.commit()
    db.refresh(inspection)
    return _get_pretrip_or_404(inspection.id, db)
