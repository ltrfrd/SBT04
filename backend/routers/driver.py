# ===========================================================
# backend/routers/driver.py - FleetOS Driver Router
# -----------------------------------------------------------
# Full CRUD + run start/end actions for drivers
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from backend import schemas
from backend.models import driver as driver_model
from backend.models.yard import Yard
from backend.models.associations import RouteDriverAssignment
from backend.models.route import Route
from backend.schemas.driver import DriverUpdate
from backend.schemas.route import RouteOut
from backend.routers.route import _serialize_route
from backend.models.operator import Operator
from backend.utils.auth import hash_driver_pin
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_driver_or_404
from backend.utils.operator_scope import get_route_access_level

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(prefix="/drivers", tags=["Drivers"])


def _get_or_create_operator_yard(db: Session, operator_id: int) -> Yard:
    yard = (
        db.query(Yard)
        .filter(Yard.operator_id == operator_id)
        .order_by(Yard.id.asc())
        .first()
    )
    if yard:
        return yard

    yard = Yard(name="Main Yard", operator_id=operator_id)
    db.add(yard)
    db.flush()
    return yard


# -----------------------------------------------------------
# - Create driver
# - Register new driver in the system
# -----------------------------------------------------------
@router.post(
    "/",
    response_model=schemas.DriverOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create driver",
    description="Create a new driver record. Email must be unique.",
    response_description="Created driver",
)
def create_driver(
    driver: schemas.DriverCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    payload = driver.model_dump()
    pin = payload.pop("pin")
    yard = _get_or_create_operator_yard(db, operator.id)
    new_driver = driver_model.Driver(
        **payload,
        operator_id=operator.id,
        yard_id=yard.id,
        pin_hash=hash_driver_pin(pin),
    )
    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)
    return new_driver


# -----------------------------------------------------------
# - List drivers
# - Return all registered driver records
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[schemas.DriverOut],
    summary="List drivers",
    description="Return all registered driver records.",
    response_description="Driver list",
)
def get_drivers(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return (
        db.query(driver_model.Driver)
        .join(driver_model.Driver.yard)
        .filter(Yard.operator_id == operator.id)
        .all()
    )

# -----------------------------------------------------------
# - Get driver by id
# - Return a single driver record
# -----------------------------------------------------------
@router.get(
    "/{driver_id}",
    response_model=schemas.DriverOut,
    summary="Get driver",
    description="Return a single driver record by id.",
    response_description="Driver record",
)
def get_driver(
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )
    return driver                                                           # Return one driver object


# -----------------------------------------------------------
# - List routes for one driver
# - Return the driver's active route contexts for the workspace flow
# -----------------------------------------------------------
@router.get(
    "/{driver_id}/routes",
    response_model=List[RouteOut],
    summary="List driver routes",
    description=(
        "Return the route contexts where the selected driver is currently active. "
        "This is the entry point for the real operator workflow: driver selects an assigned route, "
        "reviews that route's runs, then operates within the chosen run. "
        "This endpoint is not full assignment history and is not a primary/default owner lookup."
    ),
    response_description="Driver route list",
)
def get_driver_routes(
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    candidate_routes = (
        db.query(Route)
        .join(RouteDriverAssignment, RouteDriverAssignment.route_id == Route.id)
        .filter(RouteDriverAssignment.driver_id == driver_id)
        .filter(RouteDriverAssignment.active.is_(True))
        .order_by(Route.route_number.asc(), Route.id.asc())
        .distinct()
        .all()
    )
    routes = [
        route
        for route in candidate_routes
        if driver.yard and get_route_access_level(route, driver.yard.operator_id) is not None
    ]
    return [_serialize_route(route) for route in routes]


# -----------------------------------------------------------
# - Update driver
# - Modify an existing driver record
# -----------------------------------------------------------
@router.put(
    "/{driver_id}",
    response_model=schemas.DriverOut,
    summary="Update driver",
    description="Update an existing driver record by id.",
    response_description="Updated driver",
)
def update_driver(
    driver_id: int,
    driver_in: DriverUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    update_data = driver_in.model_dump(exclude_unset=True)
    pin = update_data.pop("pin", None)
    for key, value in update_data.items():
        setattr(driver, key, value)
    if pin is not None:
        driver.pin_hash = hash_driver_pin(pin)

    db.commit()
    db.refresh(driver)
    return driver

# -----------------------------------------------------------
# - Delete driver
# - Remove a driver record from the system
# -----------------------------------------------------------
@router.delete(
    "/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete driver",
    description="Delete a driver record by id.",
    response_description="Driver deleted",
)
def delete_driver(
    driver_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )
    db.delete(driver)
    db.commit()
    return None

