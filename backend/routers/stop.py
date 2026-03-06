# ===========================================================
# backend/routers/stop.py — BST Stop Router
# -----------------------------------------------------------
# Handles CRUD for bus stops (pickup/dropoff) per route.
# - Enforces UNIQUE(route_id, sequence) with safe shifting
# - Supports append, insert, reorder, delete + normalize
# ===========================================================
# -----------------------------------------------------------
# Imports
# -----------------------------------------------------------
from typing import List  # List typing

from fastapi import APIRouter  # Router
from fastapi import Depends  # Dependency injection
from fastapi import HTTPException  # HTTP errors
from fastapi import status  # Status codes

from sqlalchemy import func  # SQL MAX()
from sqlalchemy import update  # Bulk UPDATE
from sqlalchemy.exc import IntegrityError  # DB constraint errors
from sqlalchemy.orm import Session  # DB session type

from database import get_db  # DB dependency

from backend.deps.admin import require_admin  # Admin dependency (used in Step 4B)

from backend.models import stop as stop_model  # Stop model module
from backend.models.stop import Stop  # Stop model class (normalize query)

from backend.schemas.stop import StopCreate  # Create schema
from backend.schemas.stop import StopOut  # Output schema
from backend import schemas  # Other stop schemas (StopUpdate/StopReorder)

from backend.utils.db_errors import raise_conflict_if_unique  # 409 on UNIQUE violation
from backend.schemas.stop import StopUpdate  # Schema used for partial stop updates (PUT /stops/{id})
# --- Stop Schemas (direct imports to avoid __init__ re-export dependency) ---
from backend.schemas.stop import StopUpdate  # Schema used for partial stop updates (drag pin / PATCH-like PUT)
from backend.schemas.stop import StopReorder  # Schema used for reordering stops (PUT /stops/{id}/reorder)
# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(  # Router instance
    prefix="/stops", tags=["Stops"]  # All endpoints under /stops  # Swagger group label
)


# -----------------------------------------------------------
# Safe block shifting helpers (collision-safe with UNIQUE(route_id, sequence))
# - Phase 1: move affected block into safe zone (+OFFSET)
# - Phase 2: bring back with final +/- shift applied
# - Uses bulk SQL UPDATE with synchronize_session=False (prevents ORM collisions)
# -----------------------------------------------------------
SHIFT_OFFSET = 100000  # Large offset to avoid collisions inside a route


def shift_block_up(db: Session, route_id: int, start_seq: int, end_seq: int) -> None:
    """Shift stops in range [start_seq..end_seq] down by +1 (increase sequence)."""
    if start_seq > end_seq:  # Invalid range => nothing to do
        return  # Exit early

    db.execute(  # Phase 1: move block into safe zone
        update(stop_model.Stop)  # UPDATE stops
        .where(stop_model.Stop.route_id == route_id)  # Only this route
        .where(stop_model.Stop.sequence >= start_seq)  # Start of impacted block
        .where(stop_model.Stop.sequence <= end_seq)  # End of impacted block
        .values(
            sequence=stop_model.Stop.sequence + SHIFT_OFFSET
        )  # sequence = sequence + OFFSET
        .execution_options(
            synchronize_session=False
        )  # Do not sync ORM state (prevents collisions)
    )

    db.execute(  # Phase 2: bring block back shifted +1
        update(stop_model.Stop)  # UPDATE stops
        .where(stop_model.Stop.route_id == route_id)  # Only this route
        .where(stop_model.Stop.sequence >= start_seq + SHIFT_OFFSET)  # Shifted start
        .where(stop_model.Stop.sequence <= end_seq + SHIFT_OFFSET)  # Shifted end
        .values(
            sequence=stop_model.Stop.sequence - SHIFT_OFFSET + 1
        )  # final = original + 1
        .execution_options(
            synchronize_session=False
        )  # Do not sync ORM state (prevents collisions)
    )


def shift_block_down(db: Session, route_id: int, start_seq: int, end_seq: int) -> None:
    """Shift stops in range [start_seq..end_seq] up by -1 (decrease sequence)."""
    if start_seq > end_seq:  # Invalid range => nothing to do
        return  # Exit early

    db.execute(  # Phase 1: move block into safe zone
        update(stop_model.Stop)  # UPDATE stops
        .where(stop_model.Stop.route_id == route_id)  # Only this route
        .where(stop_model.Stop.sequence >= start_seq)  # Start of impacted block
        .where(stop_model.Stop.sequence <= end_seq)  # End of impacted block
        .values(
            sequence=stop_model.Stop.sequence + SHIFT_OFFSET
        )  # sequence = sequence + OFFSET
        .execution_options(
            synchronize_session=False
        )  # Do not sync ORM state (prevents collisions)
    )

    db.execute(  # Phase 2: bring block back shifted -1
        update(stop_model.Stop)  # UPDATE stops
        .where(stop_model.Stop.route_id == route_id)  # Only this route
        .where(stop_model.Stop.sequence >= start_seq + SHIFT_OFFSET)  # Shifted start
        .where(stop_model.Stop.sequence <= end_seq + SHIFT_OFFSET)  # Shifted end
        .values(
            sequence=stop_model.Stop.sequence - SHIFT_OFFSET - 1
        )  # final = original - 1
        .execution_options(
            synchronize_session=False
        )  # Do not sync ORM state (prevents collisions)
    )


# -----------------------------------------------------------
# Normalize sequences for a single route (gap-free 1..N)
# - Keeps existing order (by current sequence ASC)
# - Uses 2-phase shift to avoid UNIQUE(route_id, sequence) collisions
# -----------------------------------------------------------
def normalize_route_sequences(db: Session, route_id: int) -> None:
    OFFSET = 100000  # Large offset to move rows into a safe, non-colliding range

    # 1) Load all stops for this route in current order
    stops = (
        db.query(Stop)  # Query Stop table
        .filter(Stop.route_id == route_id)  # Only stops for the given route
        .order_by(Stop.sequence.asc())  # Preserve current ordering by sequence
        .all()  # Materialize list
    )

    # 2) If no stops, nothing to normalize
    if not stops:  # Empty route => no work
        return  # Exit early

    # 3) Build desired mapping: stable 1..N in same order
    desired_by_id = {}  # stop_id -> new_sequence
    for idx, s in enumerate(stops):  # Walk stops in current sequence order
        desired_by_id[s.id] = idx + 1  # Assign normalized sequence starting at 1

    # 4) Fast exit if already normalized
    already_ok = True  # Assume OK until proven otherwise
    for s in stops:  # Check each stop
        if s.sequence != desired_by_id[s.id]:  # If any stop has a gap or mismatch
            already_ok = False  # Mark as not normalized
            break  # Stop checking
    if already_ok:  # If all sequences already 1..N
        return  # Nothing to do

    # 5) Phase 1: move all sequences to a safe zone (sequence + OFFSET)
    for s in stops:  # For each stop
        s.sequence = (
            s.sequence + OFFSET
        )  # Shift into safe zone to avoid unique collisions
    db.flush()  # Flush phase 1 to DB so phase 2 is safe

    # 6) Phase 2: write final normalized sequences (1..N)
    for s in stops:  # For each stop again
        s.sequence = desired_by_id[s.id]  # Set exact normalized value
    db.flush()  # Flush final normalized values


# -----------------------------------------------------------
# GET /stops/validate/{route_id}
# DEV TOOL — Validate route sequence integrity
# - Checks duplicates
# - Checks gaps
# - Ensures sequences are exactly 1..N
# - Read-only (no DB writes)
# -----------------------------------------------------------
@router.get("/validate/{route_id}")
def validate_route_sequences(
    route_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):

    stops = (
        db.query(stop_model.Stop)  # Load stops for this route
        .filter(stop_model.Stop.route_id == route_id)  # Filter by route
        .order_by(stop_model.Stop.sequence.asc())  # Order by sequence
        .all()  # Materialize list
    )

    if not stops:  # If route has no stops
        return {
            "route_id": route_id,
            "valid": True,
            "message": "No stops found (empty route).",
        }

    sequences = [s.sequence for s in stops]  # Extract sequence list
    expected = list(range(1, len(stops) + 1))  # Expected 1..N

    duplicates = len(sequences) != len(set(sequences))  # Check duplicate sequences
    gaps = sequences != expected  # Check gap-free condition

    return {
        "route_id": route_id,
        "valid": not duplicates and not gaps,
        "total_stops": len(stops),
        "sequences": sequences,
        "expected": expected,
        "has_duplicates": duplicates,
        "has_gaps": gaps,
    }


# -----------------------------------------------------------
# POST /stops/normalize/{route_id}
# ADMIN TOOL — Force repair route sequences
# - Rebuilds sequence as 1..N
# - Keeps current ordering
# - Uses collision-safe 2-phase logic
# ADMIN TOOL — Force repair route sequences
# -----------------------------------------------------------
@router.post("/normalize/{route_id}")
def force_normalize_route(
    route_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    try:  # Protected DB operation

        normalize_route_sequences(db, route_id)  # Repair sequence integrity
        db.commit()  # Commit normalization

        stops = (
            db.query(stop_model.Stop)
            .filter(stop_model.Stop.route_id == route_id)
            .order_by(stop_model.Stop.sequence.asc())
            .all()
        )

        return {
            "route_id": route_id,
            "status": "normalized",
            "total_stops": len(stops),
            "sequences": [s.sequence for s in stops],
        }

    # -----------------------------------------------------------
    # IntegrityError handling
    # -----------------------------------------------------------
    except IntegrityError as e:  # Catch DB constraint errors
        db.rollback()  # Roll back transaction safely
        raise_conflict_if_unique(
            db,
            e,
            constraint_name="uq_stops_route_sequence",
            sqlite_columns=("route_id", "sequence"),
            detail="Stop sequence conflict for this route",
        )
        raise HTTPException(status_code=400, detail="Integrity error")


# -----------------------------------------------------------
# POST /stops → Create stop (append or insert)
# - Append Mode: if sequence missing → MAX(sequence)+1
# - Insert Mode: if sequence provided → clamp + shift + insert
# -----------------------------------------------------------
@router.post("/", response_model=StopOut, status_code=201)
def create_stop(payload: StopCreate, db: Session = Depends(get_db)):

    try:  # Start protected DB operation

        # -----------------------------------------------------------
        # Read current max sequence for this route (used by both modes)
        # -----------------------------------------------------------
        max_seq = (  # Calculate current max sequence
            db.query(func.max(stop_model.Stop.sequence))  # SELECT MAX(sequence)
            .filter(stop_model.Stop.route_id == payload.route_id)  # WHERE route_id = X
            .scalar()  # Return scalar value
        )
        max_seq = max_seq or 0  # If no stops exist yet, treat as 0

        # -----------------------------------------------------------
        # Mode 1: Append Mode (client omitted sequence)
        # -----------------------------------------------------------
        if payload.sequence is None:  # If client did not send sequence
            seq = max_seq + 1  # Append to end (max+1)

        # -----------------------------------------------------------
        # Mode 2: Insert Mode (client provided sequence)
        # -----------------------------------------------------------
        else:
            target = payload.sequence  # Requested insert position
            target = max(
                1, min(target, max_seq + 1)
            )  # Clamp into valid range [1..max+1]

            if target <= max_seq:  # If inserting into the middle
                shift_block_up(
                    db, payload.route_id, target, max_seq
                )  # Shift [target..max] down by +1 (make room)

            db.expire_all()  # Reset ORM state after bulk UPDATEs

            seq = target  # New stop takes the target slot

        # -----------------------------------------------------------
        # Create stop record (force computed sequence)
        # - Auto-fill stop name if missing:
        #     1) Use provided name
        #     2) If name missing but address exists → use address
        #     3) If both missing → use "Stop {sequence}"
        # -----------------------------------------------------------
        data = payload.model_dump()  # Convert payload to dict
        data["sequence"] = seq  # Force final sequence into dict

        if not data.get("name") and data.get("address"):  # If name missing but address exists
            data["name"] = data["address"]  # Use address as stop name

        if not data.get("name"):  # If still missing
            data["name"] = f"Stop {seq}"  # Fallback name based on sequence

        stop = stop_model.Stop(**data)  # Build ORM object
        db.add(stop)  # Add to session
        db.commit()  # Commit once (atomic)
        db.refresh(stop)  # Refresh to load generated fields
        return stop  # Return created stop

    except IntegrityError as e:  # Catch DB constraint errors
        db.rollback()  # Roll back transaction safely
        raise_conflict_if_unique(  # Raise 409 if UNIQUE violated
            db,  # DB session (dialect detection)
            e,  # IntegrityError instance
            constraint_name="uq_stops_route_sequence",  # Postgres constraint name
            sqlite_columns=("route_id", "sequence"),  # SQLite message fallback keys
            detail="Stop sequence conflict for this route",  # Client-friendly 409 detail
        )
        raise HTTPException(
            status_code=400, detail="Integrity error"
        )  # Other integrity issues → 400
# -----------------------------------------------------------
# GET /stops → List stops (optionally filter by route_id)
# Always ordered by sequence ascending
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.StopOut])
def get_stops(route_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(stop_model.Stop)  # Base query

    if route_id is not None:  # If filtering by route
        query = query.filter(stop_model.Stop.route_id == route_id)  # Apply route filter

    query = query.order_by(
        stop_model.Stop.sequence.asc()
    )  # Ensure stops ordered by sequence
    return query.all()  # Return ordered results


# -----------------------------------------------------------
# PUT /stops/{stop_id} → Update stop info
# -----------------------------------------------------------
@router.put("/{stop_id}", response_model=schemas.StopOut)
def update_stop(
    stop_id: int, stop_in: StopUpdate, db: Session = Depends(get_db)
):
    stop = db.get(stop_model.Stop, stop_id)  # Load stop from DB
    if not stop:  # If stop does not exist
        raise HTTPException(status_code=404, detail="Stop not found")  # Return 404

    updates = stop_in.model_dump(exclude_none=True)  # Only apply provided fields
    for key, value in updates.items():  # Loop through fields
        setattr(stop, key, value)  # Update stop attributes

    db.commit()  # Save changes
    db.refresh(stop)  # Refresh instance
    return stop  # Return updated stop


# -----------------------------------------------------------
# DELETE /stops/{stop_id} → Remove stop
# - Deletes stop
# - Normalizes remaining stops to keep sequences gap-free
# -----------------------------------------------------------
@router.delete("/{stop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stop(stop_id: int, db: Session = Depends(get_db)):

    try:  # Begin protected transaction block

        stop = db.get(stop_model.Stop, stop_id)  # Fetch stop by primary key
        if not stop:  # If stop does not exist
            raise HTTPException(status_code=404, detail="Stop not found")  # Return 404

        route_id = stop.route_id  # Save route_id before deletion

        db.delete(stop)  # Mark stop for deletion
        db.flush()  # Apply deletion before renumbering

        normalize_route_sequences(
            db, route_id
        )  # Reassign sequences 1..N for this route

        db.commit()  # Commit entire operation atomically
        return None  # 204 No Content response

    # -----------------------------------------------------------
    # IntegrityError handling
    # - Convert UNIQUE(route_id, sequence) into HTTP 409
    # - Keep other integrity errors as HTTP 400
    # -----------------------------------------------------------
    except IntegrityError as e:  # Catch DB constraint issues
        db.rollback()  # Roll back transaction safely
        raise_conflict_if_unique(  # Raise 409 if UNIQUE violated
            db,  # DB session (dialect detection)
            e,  # IntegrityError instance
            constraint_name="uq_stops_route_sequence",  # Postgres constraint name
            sqlite_columns=("route_id", "sequence"),  # SQLite message fallback keys
            detail="Stop sequence conflict for this route",  # Client-friendly 409 detail
        )
        raise HTTPException(
            status_code=400, detail="Integrity error"
        )  # Other DB errors → 400


# -----------------------------------------------------------
# PUT /stops/{stop_id}/reorder → Move stop to new position
# - Moves stop out of range first (OFFSET)
# - Shifts impacted block with collision-safe bulk UPDATE
# -----------------------------------------------------------
@router.put("/{stop_id}/reorder", response_model=StopOut)
def reorder_stop(
    stop_id: int, payload: StopReorder, db: Session = Depends(get_db)
):

    try:  # Protected transaction

        stop = db.get(stop_model.Stop, stop_id)  # Load stop
        if not stop:  # If not found
            raise HTTPException(status_code=404, detail="Stop not found")  # Return 404

        route_id = stop.route_id  # Save route id
        old_seq = stop.sequence  # Save current position

        max_seq = (  # Get current max sequence in route
            db.query(func.max(stop_model.Stop.sequence))  # SELECT MAX(sequence)
            .filter(stop_model.Stop.route_id == route_id)  # WHERE route_id = ?
            .scalar()  # Return scalar
        ) or 0  # Default 0 if no rows

        # -----------------------------------------------------------
        # Clamp target position into valid range
        # -----------------------------------------------------------
        new_seq = max(1, min(payload.new_sequence, max_seq))  # Clamp into [1..max_seq]

        if new_seq == old_seq:  # If nothing changes
            return stop  # No operation needed

        OFFSET = 100000  # Safe offset

        stop.sequence = (
            stop.sequence + OFFSET
        )  # Phase 1: move current stop out of the way
        db.flush()  # Flush so the gap is real in DB

        # -----------------------------------------------------------
        # Shift impacted block (collision-safe)
        # -----------------------------------------------------------
        if new_seq < old_seq:  # Moving upward (e.g., 5 → 2)
            shift_block_up(
                db, route_id, new_seq, old_seq - 1
            )  # Shift [new..old-1] down by +1 (make room)
        else:  # Moving downward (e.g., 2 → 5)
            shift_block_down(
                db, route_id, old_seq + 1, new_seq
            )  # Shift [old+1..new] up by -1 (fill gap)

        db.expire_all()  # Reset ORM state after bulk UPDATEs

        stop = db.get(stop_model.Stop, stop_id)  # Reload stop (ensures fresh ORM state)
        stop.sequence = new_seq  # Place stop at new position

        db.commit()  # Commit all changes atomically
        db.refresh(stop)  # Reload updated stop
        return stop  # Return updated stop

    # -----------------------------------------------------------
    # IntegrityError handling
    # - Convert UNIQUE(route_id, sequence) into HTTP 409
    # - Keep other integrity errors as HTTP 400
    # -----------------------------------------------------------
    except IntegrityError as e:  # Catch DB constraint issues
        db.rollback()  # Roll back transaction safely
        raise_conflict_if_unique(  # Raise 409 if UNIQUE violated
            db,  # DB session (dialect detection)
            e,  # IntegrityError instance
            constraint_name="uq_stops_route_sequence",  # Postgres constraint name
            sqlite_columns=("route_id", "sequence"),  # SQLite message fallback keys
            detail="Stop sequence conflict for this route",  # Client-friendly 409 detail
        )
        raise HTTPException(
            status_code=400, detail="Integrity error"
        )  # Other DB errors → 400

