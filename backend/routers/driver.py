# ===========================================================
# backend/routers/driver.py — BST Driver Router
# -----------------------------------------------------------
# Full CRUD + run start/end actions for drivers
# ===========================================================
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from backend import schemas
from backend.models import driver as driver_model
from backend.models.associations import RouteDriverAssignment
from backend.models.route import Route
from backend.schemas.driver import DriverUpdate
from backend.schemas.route import RouteOut
from backend.routers.route import _serialize_route

# -----------------------------------------------------------
# Router setup
# -----------------------------------------------------------
router = APIRouter(prefix="/drivers", tags=["Drivers"])


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
def create_driver(driver: schemas.DriverCreate, db: Session = Depends(get_db)):
    new_driver = driver_model.Driver(**driver.model_dump())
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
def get_drivers(db: Session = Depends(get_db)):
    return db.query(driver_model.Driver).all()

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
def get_driver(driver_id: int, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, driver_id)                         # Load one driver by primary key
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")     # Return not found when missing
    return driver                                                           # Return one driver object


# -----------------------------------------------------------
# - List routes for one driver
# - Return the driver's assigned route contexts for the workspace flow
# -----------------------------------------------------------
@router.get(
    "/{driver_id}/routes",
    response_model=List[RouteOut],
    summary="List driver routes",
    description=(
        "Return the route contexts assigned to the selected driver. "
        "This is the entry point for the real operator workflow: driver selects an assigned route, "
        "reviews that route's runs, then operates within the chosen run."
    ),
    response_description="Driver route list",
)
def get_driver_routes(driver_id: int, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    routes = (
        db.query(Route)
        .join(RouteDriverAssignment, RouteDriverAssignment.route_id == Route.id)
        .filter(RouteDriverAssignment.driver_id == driver_id)
        .distinct()
        .all()
    )
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
    driver_id: int, driver_in: DriverUpdate, db: Session = Depends(get_db)
):
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    update_data = driver_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(driver, key, value)

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
def delete_driver(driver_id: int, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    db.delete(driver)
    db.commit()
    return None
