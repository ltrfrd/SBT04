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
# CREATE: Add new driver
# -----------------------------------------------------------
@router.post("/", response_model=schemas.DriverOut, status_code=status.HTTP_201_CREATED)
def create_driver(driver: schemas.DriverCreate, db: Session = Depends(get_db)):
    new_driver = driver_model.Driver(**driver.model_dump())
    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)
    return new_driver


# -----------------------------------------------------------
# READ: Get all drivers
# -----------------------------------------------------------
@router.get("/", response_model=List[schemas.DriverOut])
def get_drivers(db: Session = Depends(get_db)):
    return db.query(driver_model.Driver).all()


# -----------------------------------------------------------
# READ: Get driver by ID
# -----------------------------------------------------------
@router.get("/{driver_id}", response_model=schemas.DriverOut)
def get_driver(driver_id: int, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


# -----------------------------------------------------------
# READ: Get routes for one driver
# -----------------------------------------------------------
@router.get("/{driver_id}/routes", response_model=List[RouteOut])
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
# UPDATE: Modify driver
# -----------------------------------------------------------
@router.put("/{driver_id}", response_model=schemas.DriverOut)
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
# DELETE: Remove driver
# -----------------------------------------------------------
@router.delete("/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_driver(driver_id: int, db: Session = Depends(get_db)):
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    db.delete(driver)
    db.commit()
    return None
