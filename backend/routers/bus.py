# ===========================================================
# backend/routers/bus.py - FleetOS Bus Router
# -----------------------------------------------------------
# Full CRUD for standalone bus records
# ===========================================================

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from database import get_db

from backend import schemas
from backend.models import bus as bus_model
from backend.models.associations import RouteDriverAssignment, StudentRunAssignment
from backend.models import run as run_model
from backend.models import student as student_model
from backend.models.operator import Operator
from backend.models.route import Route
from backend.models.yard import Yard
from backend.schemas.bus import BusUpdate
from backend.routers.route_helpers import _serialize_route_detail
from backend.utils.planning_scope import accessible_route_filter
from backend.utils.operator_scope import get_bus_operator_id
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_bus_or_404
from backend.utils.operator_scope import get_operator_scoped_yard_or_404


router = APIRouter(prefix="/buses", tags=["Buses"])

# -----------------------------------------------------------
# Mixed Planning + Execution Support Endpoints
# -----------------------------------------------------------
# -----------------------------------------------------------
# - Unique bus field guard
# - Keep stored bus number and license plate conflicts explicit
# -----------------------------------------------------------
def _validate_bus_uniqueness(
    *,
    db: Session,
    yard_id: int,
    unit_number: str | None = None,
    license_plate: str | None = None,
    exclude_bus_id: int | None = None,
) -> None:
    if unit_number is not None:
        query = (
            db.query(bus_model.Bus)
            .filter(bus_model.Bus.yard_id == yard_id)
            .filter(bus_model.Bus.unit_number == unit_number)
        )
        if exclude_bus_id is not None:
            query = query.filter(bus_model.Bus.id != exclude_bus_id)

        if query.first():
            raise HTTPException(status_code=409, detail="Bus number already exists")

    if license_plate is not None:
        query = (
            db.query(bus_model.Bus)
            .filter(bus_model.Bus.yard_id == yard_id)
            .filter(bus_model.Bus.license_plate == license_plate)
        )
        if exclude_bus_id is not None:
            query = query.filter(bus_model.Bus.id != exclude_bus_id)

        if query.first():
            raise HTTPException(status_code=409, detail="Bus license plate already exists")


# -----------------------------------------------------------
# - Create bus
# - Register a standalone bus record
# -----------------------------------------------------------
@router.post(
    "/",
    response_model=schemas.BusOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create bus",
    description="Create a standalone bus record. Bus Number and license plate must be unique.",
    response_description="Created bus",
)
def create_bus(
    bus: schemas.BusCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    payload = bus.model_dump()
    yard = get_operator_scoped_yard_or_404(
        db=db,
        yard_id=payload.pop("yard_id"),
        operator_id=operator.id,
        detail="Yard not found",
    )
    _validate_bus_uniqueness(
        db=db,
        yard_id=yard.id,
        unit_number=payload["bus_number"],
        license_plate=payload["license_plate"],
    )

    new_bus = bus_model.Bus(
        yard_id=yard.id,
        unit_number=payload["bus_number"],
        license_plate=payload["license_plate"],
        capacity=payload["capacity"],
        size=payload["size"],
    )
    db.add(new_bus)
    db.commit()
    db.refresh(new_bus)
    return new_bus


# -----------------------------------------------------------
# - List buses
# - Return all standalone bus records
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[schemas.BusOut],
    summary="List buses",
    description="Return all standalone bus records.",
    response_description="Bus list",
)
def get_buses(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return (
        db.query(bus_model.Bus)
        .join(bus_model.Bus.yard)
        .filter(Yard.operator_id == operator.id)
        .order_by(bus_model.Bus.unit_number.asc(), bus_model.Bus.id.asc())
        .all()
    )


# -----------------------------------------------------------
# - Get bus by id
# - Return a single bus record
# -----------------------------------------------------------
@router.get(
    "/{bus_id}",
    response_model=schemas.BusDetailOut,
    summary="Get bus",
    description="Return a single bus record by id with current assigned route details when present.",
    response_description="Bus record",
)
def get_bus(
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    bus = get_operator_scoped_bus_or_404(
        db=db,
        bus_id=bus_id,
        operator_id=operator.id,
        detail="Bus not found",
        options=[
            selectinload(bus_model.Bus.routes).selectinload(Route.schools),
            selectinload(bus_model.Bus.routes).selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),
            selectinload(bus_model.Bus.routes).selectinload(Route.runs).selectinload(run_model.Run.driver),
            selectinload(bus_model.Bus.routes).selectinload(Route.runs).selectinload(run_model.Run.stops),
            selectinload(bus_model.Bus.routes).selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),
            selectinload(bus_model.Bus.routes).selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),
        ],
    )

    bus_operator_id = get_bus_operator_id(bus)

    # Related route detail remains planning-visible on purpose; execution gating lives on run surfaces.
    visible_routes = (
        db.query(Route)
        .options(
            selectinload(Route.schools),
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),
            selectinload(Route.runs).selectinload(run_model.Run.driver),
            selectinload(Route.runs).selectinload(run_model.Run.stops),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),
        )
        .filter(Route.id.in_([route.id for route in bus.routes]))
        .filter(accessible_route_filter(bus_operator_id))
        .order_by(Route.route_number.asc(), Route.id.asc())
        .all()
    )

    return schemas.BusDetailOut(
        id=bus.id,
        bus_number=bus.unit_number,
        license_plate=bus.license_plate,
        capacity=bus.capacity,
        size=bus.size,
        assigned_routes=[
            _serialize_route_detail(route)
            for route in visible_routes
        ],
    )


# -----------------------------------------------------------
# - Update bus
# - Modify an existing bus record
# -----------------------------------------------------------
@router.put(
    "/{bus_id}",
    response_model=schemas.BusOut,
    summary="Update bus",
    description="Update an existing bus record by id.",
    response_description="Updated bus",
)
def update_bus(
    bus_id: int,
    bus_in: BusUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    bus = get_operator_scoped_bus_or_404(
        db=db,
        bus_id=bus_id,
        operator_id=operator.id,
        detail="Bus not found",
    )

    update_data = bus_in.model_dump(exclude_unset=True)
    _validate_bus_uniqueness(
        db=db,
        yard_id=bus.yard_id,
        unit_number=update_data.get("bus_number"),
        license_plate=update_data.get("license_plate"),
        exclude_bus_id=bus_id,
    )

    if "bus_number" in update_data:
        bus.unit_number = update_data["bus_number"]

    for key in ("license_plate", "capacity", "size"):
        if key in update_data:
            setattr(bus, key, update_data[key])

    db.commit()
    db.refresh(bus)
    return bus


# -----------------------------------------------------------
# - Delete bus
# - Remove a bus record from the system
# -----------------------------------------------------------
@router.delete(
    "/{bus_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete bus",
    description="Delete a bus record by id.",
    response_description="Bus deleted",
)
def delete_bus(
    bus_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    bus = get_operator_scoped_bus_or_404(
        db=db,
        bus_id=bus_id,
        operator_id=operator.id,
        detail="Bus not found",
    )

    db.delete(bus)
    db.commit()
    return None

