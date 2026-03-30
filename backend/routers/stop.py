# ===========================================================
# backend/routers/stop.py - BST Stop Router
# Manage run stop validation, normalization, and ordering.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from backend.deps.admin import require_admin
from backend.models import school as school_model
from backend.models import stop as stop_model
from backend.models import run as run_model
from backend.models.stop import Stop, StopType
from backend.schemas.stop import RunStopCreate, StopCreate, StopOut, StopUpdate, StopReorder
from backend.utils.db_errors import raise_conflict_if_unique

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(prefix="/stops", tags=["Stops"])


# -----------------------------------------------------------
# - Stop reorder helpers
# - Keep run stop sequences contiguous during inserts and moves
# -----------------------------------------------------------
SHIFT_OFFSET = 100000  # Temporary sequence offset used to avoid unique collisions during moves


def shift_block_up(db: Session, run_id: int, start_seq: int, end_seq: int) -> None:
    if start_seq > end_seq:  # Ignore empty ranges
        return

    db.execute(
        update(stop_model.Stop)
        .where(stop_model.Stop.run_id == run_id)  # Only stops for this run
        .where(stop_model.Stop.sequence >= start_seq)  # Start of block to shift
        .where(stop_model.Stop.sequence <= end_seq)  # End of block to shift
        .values(sequence=stop_model.Stop.sequence + SHIFT_OFFSET)  # Move block into safe offset range
        .execution_options(synchronize_session=False)  # Keep bulk update behavior unchanged
    )

    db.execute(
        update(stop_model.Stop)
        .where(stop_model.Stop.run_id == run_id)  # Only stops for this run
        .where(stop_model.Stop.sequence >= start_seq + SHIFT_OFFSET)  # Shifted block start
        .where(stop_model.Stop.sequence <= end_seq + SHIFT_OFFSET)  # Shifted block end
        .values(sequence=stop_model.Stop.sequence - SHIFT_OFFSET + 1)  # Reinsert block one slot later
        .execution_options(synchronize_session=False)  # Keep bulk update behavior unchanged
    )


def shift_block_down(db: Session, run_id: int, start_seq: int, end_seq: int) -> None:
    if start_seq > end_seq:  # Ignore empty ranges
        return

    db.execute(
        update(stop_model.Stop)
        .where(stop_model.Stop.run_id == run_id)  # Only stops for this run
        .where(stop_model.Stop.sequence >= start_seq)  # Start of block to shift
        .where(stop_model.Stop.sequence <= end_seq)  # End of block to shift
        .values(sequence=stop_model.Stop.sequence + SHIFT_OFFSET)  # Move block into safe offset range
        .execution_options(synchronize_session=False)  # Keep bulk update behavior unchanged
    )

    db.execute(
        update(stop_model.Stop)
        .where(stop_model.Stop.run_id == run_id)  # Only stops for this run
        .where(stop_model.Stop.sequence >= start_seq + SHIFT_OFFSET)  # Shifted block start
        .where(stop_model.Stop.sequence <= end_seq + SHIFT_OFFSET)  # Shifted block end
        .values(sequence=stop_model.Stop.sequence - SHIFT_OFFSET - 1)  # Reinsert block one slot earlier
        .execution_options(synchronize_session=False)  # Keep bulk update behavior unchanged
    )


def normalize_run_sequences(db: Session, run_id: int) -> None:
    offset = 100000  # Temporary offset used while renumbering stops safely

    stops = (
        db.query(Stop)
        .filter(Stop.run_id == run_id)  # Only stops for this run
        .order_by(Stop.sequence.asc())  # Normalize from current sequence order
        .all()  # Materialize stop list
    )

    if not stops:  # Nothing to normalize
        return

    desired_by_id = {s.id: idx + 1 for idx, s in enumerate(stops)}  # Build contiguous target sequence map
    if all(s.sequence == desired_by_id[s.id] for s in stops):  # Skip work when already normalized
        return

    for s in stops:
        s.sequence = s.sequence + offset  # Move all rows into temporary safe range first
    db.flush()  # Persist temporary offset values before final renumbering

    for s in stops:
        s.sequence = desired_by_id[s.id]  # Apply contiguous sequence values
    db.flush()  # Persist normalized sequence order


# -----------------------------------------------------------
# Stop workflow helpers
# Validate school-stop rules and assign stable default values
# -----------------------------------------------------------
def _get_next_stop_sequence(db: Session, run_id: int, requested_sequence: int | None) -> int:
    max_seq = (
        db.query(func.max(stop_model.Stop.sequence))
        .filter(stop_model.Stop.run_id == run_id)
        .scalar()
    ) or 0

    if requested_sequence is None:
        return max_seq + 1

    target = max(1, min(requested_sequence, max_seq + 1))
    if target <= max_seq:
        shift_block_up(db, run_id, target, max_seq)
    db.expire_all()
    return target


def _build_stop_payload(
    *,
    run_id: int,
    payload: StopCreate | RunStopCreate | StopUpdate,
    db: Session,
    existing_stop: stop_model.Stop | None = None,
) -> dict:
    stop_type = payload.type if payload.type is not None else existing_stop.type if existing_stop else None
    if stop_type is None:
        raise HTTPException(status_code=422, detail="type is required")

    final_run_id = payload.run_id if getattr(payload, "run_id", None) is not None else run_id
    if final_run_id is None:
        raise HTTPException(status_code=422, detail="run_id is required")

    school_id = payload.school_id if payload.school_id is not None else None
    name = payload.name.strip() if isinstance(payload.name, str) and payload.name.strip() else None
    sequence = payload.sequence if payload.sequence is not None else existing_stop.sequence if existing_stop else None

    school = None
    if stop_type in {StopType.SCHOOL_ARRIVE, StopType.SCHOOL_DEPART}:
        if school_id is None:
            raise HTTPException(status_code=400, detail="school_id is required for school stops")

        school = db.get(school_model.School, school_id)
        if not school:
            raise HTTPException(status_code=404, detail="School not found")

        name = school.name                                      # School stop names always come from school name only
    else:
        school_id = None                                        # Regular stops never keep a school pointer

    if existing_stop is None:
        sequence = _get_next_stop_sequence(db, final_run_id, payload.sequence)

        if not name:
            if stop_type in {StopType.PICKUP, StopType.DROPOFF}:
                name = f"STOP {sequence}"                       # Operator-facing numbered fallback
            elif school:
                name = school.name

    elif existing_stop is not None:
        if name is None:
            if stop_type in {StopType.SCHOOL_ARRIVE, StopType.SCHOOL_DEPART} and school:
                name = school.name
            else:
                name = existing_stop.name
        if school_id is None:
            school_id = existing_stop.school_id

    return {
        "run_id": final_run_id,
        "sequence": sequence,
        "type": stop_type,
        "name": name,
        "school_id": school_id,
        "address": payload.address if payload.address is not None else existing_stop.address if existing_stop else None,
        "planned_time": payload.planned_time if payload.planned_time is not None else existing_stop.planned_time if existing_stop else None,
        "latitude": payload.latitude if payload.latitude is not None else existing_stop.latitude if existing_stop else None,
        "longitude": payload.longitude if payload.longitude is not None else existing_stop.longitude if existing_stop else None,
    }

# -----------------------------------------------------------
# - Validate run sequences
# - Check whether stop sequences are contiguous for a run
# -----------------------------------------------------------
@router.get(
    "/validate/{run_id}",
    summary="Validate run sequences",
    description="Check whether the stops for a run have contiguous sequence values.",
    response_description="Run stop sequence validation result",
)
def validate_run_sequences(
    run_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .order_by(stop_model.Stop.sequence.asc())
        .all()
    )

    if not stops:
        return {
            "run_id": run_id,
            "valid": True,
            "message": "No stops found (empty run).",
        }

    sequences = [s.sequence for s in stops]
    expected = list(range(1, len(stops) + 1))

    duplicates = len(sequences) != len(set(sequences))
    gaps = sequences != expected

    return {
        "run_id": run_id,
        "valid": not duplicates and not gaps,
        "total_stops": len(stops),
        "sequences": sequences,
        "expected": expected,
        "has_duplicates": duplicates,
        "has_gaps": gaps,
    }

# -----------------------------------------------------------
# - Normalize run sequences
# - Force stop sequences into contiguous order for a run
# -----------------------------------------------------------
@router.post(
    "/normalize/{run_id}",
    summary="Normalize run sequences",
    description="Force the stops for a run into contiguous sequence order.",
    response_description="Normalized run stop sequences",
)
def force_normalize_run(
    run_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    try:
        normalize_run_sequences(db, run_id)
        db.commit()

        stops = (
            db.query(stop_model.Stop)
            .filter(stop_model.Stop.run_id == run_id)
            .order_by(stop_model.Stop.sequence.asc())
            .all()
        )

        return {
            "run_id": run_id,
            "status": "normalized",
            "total_stops": len(stops),
            "sequences": [s.sequence for s in stops],
        }
    except IntegrityError as e:
        db.rollback()
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_stops_run_sequence",
            sqlite_columns=("run_id", "sequence"),
            detail="Stop sequence conflict for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")

# -----------------------------------------------------------
# - Create stop
# - Create a stop and place it within the run sequence
# -----------------------------------------------------------
@router.post(
    "/",
    response_model=StopOut,
    status_code=201,
    summary="Create stop",
    description="Create a stop for a run and place it in the requested sequence position.",
    response_description="Created stop",
)
def create_stop(payload: StopCreate, db: Session = Depends(get_db)):
    try:
        run = db.get(run_model.Run, payload.run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        data = _build_stop_payload(                             # Apply shared stop workflow rules
            run_id=payload.run_id,                              # Parent run from generic payload
            payload=payload,                                    # Incoming stop request
            db=db,                                              # Shared DB session
        )

        stop = stop_model.Stop(**data)
        db.add(stop)
        db.commit()
        db.refresh(stop)
        return stop

    except IntegrityError as e:
        db.rollback()
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_stops_run_sequence",
            sqlite_columns=("run_id", "sequence"),
            detail="Stop sequence conflict for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")


# -----------------------------------------------------------
# Run-context stop creation helper
# Create a stop inside the selected run context
# -----------------------------------------------------------
def create_run_stop(
    run_id: int,
    payload: RunStopCreate,
    db: Session,
):
    try:
        run = db.get(run_model.Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        data = _build_stop_payload(                             # Apply shared stop workflow rules
            run_id=run_id,                                      # Parent run from path context
            payload=payload,                                    # Incoming contextual payload
            db=db,                                              # Shared DB session
        )

        stop = stop_model.Stop(**data)
        db.add(stop)
        db.commit()
        db.refresh(stop)
        return stop

    except IntegrityError as e:
        db.rollback()
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_stops_run_sequence",
            sqlite_columns=("run_id", "sequence"),
            detail="Stop sequence conflict for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")

# -----------------------------------------------------------
# - List stops
# - Return stops with optional run filtering
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[StopOut],
    summary="List stops",
    description="Return all stops, optionally filtered to one run.",
    response_description="Stop list",
)
def get_stops(run_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(stop_model.Stop)

    if run_id is not None:
        query = query.filter(stop_model.Stop.run_id == run_id)

    query = query.order_by(stop_model.Stop.sequence.asc())
    return query.all()

# -----------------------------------------------------------
# - Update stop
# - Modify an existing stop record
# -----------------------------------------------------------
@router.put(
    "/{stop_id}",
    response_model=StopOut,
    summary="Update stop",
    description="Update an existing stop record by id.",
    response_description="Updated stop",
)
def update_stop(
    stop_id: int, stop_in: StopUpdate, db: Session = Depends(get_db)
):
    stop = db.get(stop_model.Stop, stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")

    updates = stop_in.model_dump(exclude_none=True)
    if "type" in updates or "school_id" in updates or "name" in updates:
        updates = _build_stop_payload(                          # Reapply school-stop naming rules on update
            run_id=stop.run_id,                                # Existing run context
            payload=stop_in,                                   # Partial update payload
            db=db,                                             # Shared DB session
            existing_stop=stop,                                # Update current stop in place
        )
    for key, value in updates.items():
        setattr(stop, key, value)

    db.commit()
    db.refresh(stop)
    return stop

# -----------------------------------------------------------
# - Delete stop
# - Remove a stop and normalize the remaining sequence order
# -----------------------------------------------------------
@router.delete(
    "/{stop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete stop",
    description="Delete a stop by id and normalize the remaining stop sequence order.",
    response_description="Stop deleted",
)
def delete_stop(stop_id: int, db: Session = Depends(get_db)):
    try:
        stop = db.get(stop_model.Stop, stop_id)
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")

        run_id = stop.run_id

        db.delete(stop)
        db.flush()

        normalize_run_sequences(db, run_id)

        db.commit()
        return None

    except IntegrityError as e:
        db.rollback()
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_stops_run_sequence",
            sqlite_columns=("run_id", "sequence"),
            detail="Stop sequence conflict for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")

# -----------------------------------------------------------
# - Reorder stop
# - Move an existing stop to a new sequence position
# -----------------------------------------------------------
@router.put(
    "/{stop_id}/reorder",
    response_model=StopOut,
    summary="Reorder stop",
    description="Move an existing stop to a new sequence position within the run.",
    response_description="Reordered stop",
)
def reorder_stop(
    stop_id: int, payload: StopReorder, db: Session = Depends(get_db)
):
    try:
        stop = db.get(stop_model.Stop, stop_id)
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")

        run_id = stop.run_id
        old_seq = stop.sequence

        max_seq = (
            db.query(func.max(stop_model.Stop.sequence))
            .filter(stop_model.Stop.run_id == run_id)
            .scalar()
        ) or 0

        new_seq = max(1, min(payload.new_sequence, max_seq))

        if new_seq == old_seq:
            return stop

        offset = 100000
        stop.sequence = stop.sequence + offset
        db.flush()

        if new_seq < old_seq:
            shift_block_up(db, run_id, new_seq, old_seq - 1)
        else:
            shift_block_down(db, run_id, old_seq + 1, new_seq)

        db.expire_all()

        stop = db.get(stop_model.Stop, stop_id)
        stop.sequence = new_seq

        db.commit()
        db.refresh(stop)
        return stop

    except IntegrityError as e:
        db.rollback()
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_stops_run_sequence",
            sqlite_columns=("run_id", "sequence"),
            detail="Stop sequence conflict for this run",
        )
        raise HTTPException(status_code=400, detail="Integrity error")
