# ===========================================================
# backend/routers/stop.py - FleetOS Stop Router
# Manage run stop validation, normalization, and ordering.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from backend.deps.admin import require_admin
from backend.models.operator import Operator
from backend.models import school as school_model
from backend.models import stop as stop_model
from backend.models import run as run_model
from backend.models.stop import Stop, StopType
from backend.schemas.stop import RunStopCreate, RunStopUpdate, StopOut, StopUpdate, StopReorder
from backend.utils.db_errors import raise_conflict_if_unique
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.operator_scope import get_route_access_level
from backend.utils.run_setup import (
    ensure_run_is_planned_for_setup,
    get_run_or_404,
)

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
    payload: RunStopCreate | StopUpdate,
    db: Session,
    existing_stop: stop_model.Stop | None = None,
) -> dict:
    stop_type = payload.type if payload.type is not None else existing_stop.type if existing_stop else None
    if stop_type is None:
        raise HTTPException(status_code=422, detail="type is required")

    final_run_id = payload.run_id if getattr(payload, "run_id", None) is not None else run_id
    if final_run_id is None:
        raise HTTPException(status_code=422, detail="run_id is required")
    run = get_run_or_404(final_run_id, db)

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
        "route_id": run.route_id,
        "district_id": run.route.district_id if run.route else None,
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
# - Stop update helpers
# - Preserve run sequence integrity across update flows
# -----------------------------------------------------------
def _move_stop_within_run(db: Session, stop: stop_model.Stop, requested_sequence: int) -> stop_model.Stop:
    run_id = stop.run_id                                         # Preserve current run ownership
    old_sequence = stop.sequence                                 # Preserve current position for block shifting

    max_sequence = (
        db.query(func.max(stop_model.Stop.sequence))
        .filter(stop_model.Stop.run_id == run_id)
        .scalar()
    ) or 0

    new_sequence = max(1, min(requested_sequence, max_sequence)) # Clamp within existing run bounds
    if new_sequence == old_sequence:
        return stop

    stop.sequence = stop.sequence + SHIFT_OFFSET                 # Move row into safe range before shifting neighbors
    db.flush()

    if new_sequence < old_sequence:
        shift_block_up(db, run_id, new_sequence, old_sequence - 1)
    else:
        shift_block_down(db, run_id, old_sequence + 1, new_sequence)

    db.expire_all()
    stop = db.get(stop_model.Stop, stop.id)
    stop.sequence = new_sequence
    db.flush()
    return stop


def _update_stop_record(
    *,
    stop: stop_model.Stop,
    payload: StopUpdate | RunStopUpdate,
    db: Session,
    authoritative_run_id: int | None = None,
) -> stop_model.Stop:
    updates = payload.model_dump(exclude_none=True)              # Preserve existing null-ignore compatibility
    current_run_id = stop.run_id                                 # Save current run for gap normalization if moved

    if authoritative_run_id is not None and stop.run_id != authoritative_run_id:
        raise HTTPException(status_code=400, detail="Stop does not belong to run")

    target_run_id = authoritative_run_id
    if target_run_id is None:
        target_run_id = updates.get("run_id", stop.run_id)       # Generic compatibility path may still carry run_id

    ensure_run_is_planned_for_setup(get_run_or_404(current_run_id, db))  # Legacy update must not mutate active/completed source runs

    target_run = get_run_or_404(target_run_id, db)
    ensure_run_is_planned_for_setup(target_run)         # Legacy update must not mutate active/completed target runs

    requested_sequence = updates.get("sequence")
    school_sensitive_update = any(
        key in updates for key in {"type", "school_id", "name"}
    )                                                            # Only rerun school-stop workflow when relevant

    if school_sensitive_update or target_run_id != current_run_id:
        rebuilt = _build_stop_payload(
            run_id=target_run_id,                                # Path or compatibility authority
            payload=payload,                                     # Partial update payload
            db=db,                                               # Shared DB session
            existing_stop=stop,                                  # Preserve current stop values as defaults
        )
        update_values = {
            "run_id": rebuilt["run_id"],
            "type": rebuilt["type"],
            "name": rebuilt["name"],
            "school_id": rebuilt["school_id"],
            "address": rebuilt["address"],
            "planned_time": rebuilt["planned_time"],
            "latitude": rebuilt["latitude"],
            "longitude": rebuilt["longitude"],
        }
    else:
        update_values = {
            key: updates[key]
            for key in ("address", "planned_time", "latitude", "longitude")
            if key in updates
        }

    if target_run_id != current_run_id:
        new_sequence = _get_next_stop_sequence(db, target_run_id, requested_sequence)
        stop.run_id = target_run_id                              # Move to target run only after reserving target slot
        stop.sequence = new_sequence
    elif requested_sequence is not None:
        stop = _move_stop_within_run(db, stop, requested_sequence)

    for key, value in update_values.items():
        setattr(stop, key, value)

    if target_run_id != current_run_id:
        db.flush()
        normalize_run_sequences(db, current_run_id)              # Close the old run gap after cross-run compatibility move

    return stop


def _get_operator_scoped_stop_or_404(stop_id: int, db: Session, operator_id: int, required_access: str = "read") -> stop_model.Stop:
    stop = db.get(stop_model.Stop, stop_id)
    if not stop or not stop.run:
        raise HTTPException(status_code=404, detail="Stop not found")
    get_operator_scoped_route_or_404(
        db=db,
        route_id=stop.run.route_id,
        operator_id=operator_id,
        required_access=required_access,
    )
    return stop

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
    operator: Operator = Depends(get_operator_context),
):
    run = get_run_or_404(run_id, db)
    get_operator_scoped_route_or_404(db=db, route_id=run.route_id, operator_id=operator.id, required_access="read")
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
    operator: Operator = Depends(get_operator_context),
):
    try:
        run = get_run_or_404(run_id, db)
        route = get_operator_scoped_route_or_404(db=db, route_id=run.route_id, operator_id=operator.id, required_access="read")
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
        ensure_run_is_planned_for_setup(run)                    # Run-context setup is planned-only

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
def get_stops(
    run_id: int | None = None,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    query = db.query(stop_model.Stop)

    if run_id is not None:
        run = get_run_or_404(run_id, db)
        get_operator_scoped_route_or_404(db=db, route_id=run.route_id, operator_id=operator.id, required_access="read")
        query = query.filter(stop_model.Stop.run_id == run_id)

    query = query.order_by(stop_model.Stop.sequence.asc())
    stops = query.all()
    return [
        stop for stop in stops
        if stop.run and stop.run.route and get_route_access_level(stop.run.route, operator.id) is not None
    ]

# -----------------------------------------------------------
# - Update stop
# - Modify an existing stop record
# -----------------------------------------------------------
@router.put(
    "/{stop_id}",
    response_model=StopOut,
    summary="Update stop",
    description="Update an existing stop record by id. Legacy compatibility endpoint; only planned runs can be modified.",
    response_description="Updated stop",
)
def update_stop(
    stop_id: int,
    stop_in: StopUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    try:
        stop = _get_operator_scoped_stop_or_404(stop_id, db, operator.id, "read")
        ensure_run_is_planned_for_setup(get_run_or_404(stop.run_id, db))  # Legacy compatibility update must stay planned-only

        stop = _update_stop_record(
            stop=stop,                                         # Existing stop from generic path
            payload=stop_in,                                   # Compatibility update payload
            db=db,                                             # Shared DB session
        )
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
# Run-context stop update helper
# Update a stop inside the selected run context
# -----------------------------------------------------------
def update_run_stop(
    run_id: int,
    stop_id: int,
    payload: RunStopUpdate,
    db: Session,
):
    try:
        run = db.get(run_model.Run, run_id)                     # Path run is the authority in context mode
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        ensure_run_is_planned_for_setup(run)                    # Run-context setup is planned-only

        stop = db.get(stop_model.Stop, stop_id)
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")

        stop = _update_stop_record(
            stop=stop,                                         # Existing stop within run context
            payload=payload,                                   # Context payload without run_id
            db=db,                                             # Shared DB session
            authoritative_run_id=run_id,                       # Prevent cross-run movement in preferred flow
        )
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
def delete_stop(
    stop_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    try:
        stop = _get_operator_scoped_stop_or_404(stop_id, db, operator.id, "read")

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
    stop_id: int,
    payload: StopReorder,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    try:
        stop = _get_operator_scoped_stop_or_404(stop_id, db, operator.id, "read")

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

