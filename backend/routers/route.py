from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from database import get_db

from backend.models.associations import RouteDriverAssignment
from backend.models.driver import Driver
from backend.models.route import Route
from backend.models.school import School
from backend.schemas.route import (
    RouteCreate,
    RouteDriverAssignmentCreate,
    RouteDriverAssignmentOut,
    RouteOut,
)
from backend.utils.route_driver_assignment import resolve_route_driver_assignment
from datetime import datetime, timezone

router = APIRouter(prefix="/routes", tags=["Routes"])


# -----------------------------------------------------------
# - Route serializer
# - Return stable route payloads with assignment context
# -----------------------------------------------------------
def _serialize_route(route: Route) -> RouteOut:
    active_driver_id = None  # Default when no active driver resolves
    active_driver_name = None  # Default when no active driver resolves

    try:
        active_assignment = resolve_route_driver_assignment(route)  # Resolve current route driver
        active_driver_id = active_assignment.driver_id  # Resolved driver identifier
        active_driver_name = active_assignment.driver.name if active_assignment.driver else None  # Resolved driver name
    except ValueError:
        pass  # Leave unresolved route driver fields empty

    return RouteOut(
        id=route.id,
        route_number=route.route_number,
        unit_number=route.unit_number,
        school_ids=[school.id for school in route.schools],
        active_driver_id=active_driver_id,
        active_driver_name=active_driver_name,
        driver_assignments=[
            RouteDriverAssignmentOut(
                id=assignment.id,
                route_id=assignment.route_id,
                driver_id=assignment.driver_id,
                driver_name=assignment.driver.name if assignment.driver else None,
                active=assignment.active,
            )
            for assignment in route.driver_assignments
        ],
    )

# -----------------------------------------------------------
# - Create route without driver assignment
# - Driver assignment happens in a separate step
# -----------------------------------------------------------
@router.post("/", response_model=RouteOut)
def create_route(route: RouteCreate, db: Session = Depends(get_db)):
    payload = route.model_dump(exclude_unset=True)
    school_ids = payload.pop("school_ids", [])

    db_route = Route(**payload)
    db.add(db_route)
    db.flush()

    if school_ids:
        db_route.schools = db.query(School).filter(School.id.in_(school_ids)).all()

    db.commit()
    db.refresh(db_route)
    return _serialize_route(db_route)


@router.get("/", response_model=List[RouteOut])
def get_routes(db: Session = Depends(get_db)):
    routes = (
        db.query(Route)
        .options(
            joinedload(Route.schools),
            joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver),
        )
        .all()
    )
    return [_serialize_route(route) for route in routes]


@router.get("/{route_id}", response_model=RouteOut)
def get_route(route_id: int, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(
            joinedload(Route.schools),
            joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver),
        )
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return _serialize_route(route)


@router.put("/{route_id}", response_model=RouteOut)
def update_route(route_id: int, route_in: RouteCreate, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(
            joinedload(Route.schools),
            joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver),
        )
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    update_data = route_in.model_dump(exclude_unset=True)
    school_ids = update_data.pop("school_ids", None)

    for key, value in update_data.items():
        setattr(route, key, value)

    if school_ids is not None:
        route.schools = db.query(School).filter(School.id.in_(school_ids)).all()

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: int, db: Session = Depends(get_db)):
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    db.delete(route)
    db.commit()
    return None


@router.get("/{route_id}/schools", response_model=List[dict])
def get_route_schools(route_id: int, db: Session = Depends(get_db)):
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    return [{"id": s.id, "name": s.name, "address": s.address} for s in route.schools]
# -----------------------------------------------------------
# - Assign driver to route
# - Enforce one active driver per route
# -----------------------------------------------------------
def _assign_driver_to_route(
    route: Route,
    driver_id: int,
    db: Session,
) -> RouteDriverAssignment:

    driver = db.get(Driver, driver_id)                           # Validate driver exists
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    # -----------------------------------------------------------
    # Deactivate all current active assignments
    # -----------------------------------------------------------
    active_assignments = (
        db.query(RouteDriverAssignment)
        .filter(RouteDriverAssignment.route_id == route.id)
        .filter(RouteDriverAssignment.active.is_(True))
        .all()
    )

    for assignment in active_assignments:
        assignment.active = False                                # Only one active driver allowed

    # -----------------------------------------------------------
    # Create new active assignment
    # -----------------------------------------------------------
    new_assignment = RouteDriverAssignment(
        route_id=route.id,
        driver_id=driver_id,
        active=True,
    )

    db.add(new_assignment)
    db.flush()

    return new_assignment

# -----------------------------------------------------------
# - Assign driver to route endpoint
# - Calls helper to enforce assignment rule
# -----------------------------------------------------------
@router.post("/{route_id}/assign_driver/{driver_id}", response_model=RouteDriverAssignmentOut)
def assign_driver_to_route(
    route_id: int,
    driver_id: int,
    db: Session = Depends(get_db),
):

    route = (
        db.query(Route)
        .options(joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver))
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    assignment = _assign_driver_to_route(route, driver_id, db)

    db.commit()
    db.refresh(assignment)

    return RouteDriverAssignmentOut(
        id=assignment.id,
        route_id=assignment.route_id,
        driver_id=assignment.driver_id,
        driver_name=assignment.driver.name if assignment.driver else None,
        active=assignment.active,
    )
# -----------------------------------------------------------
# Route driver assignment list
# - Return drivers assigned to one route
# -----------------------------------------------------------
@router.get("/{route_id}/drivers", response_model=List[RouteDriverAssignmentOut])
def get_route_drivers(route_id: int, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver))
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    return [
        RouteDriverAssignmentOut(
            id=assignment.id,
            route_id=assignment.route_id,
            driver_id=assignment.driver_id,
            driver_name=assignment.driver.name if assignment.driver else None,
            active=assignment.active,
        )
        for assignment in route.driver_assignments
    ]


# -----------------------------------------------------------
# Route driver assignment removal
# - Deactivate active assignments for one route and driver
# -----------------------------------------------------------
@router.delete("/{route_id}/unassign_driver/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_driver_from_route(route_id: int, driver_id: int, db: Session = Depends(get_db)):
    assignments = (
        db.query(RouteDriverAssignment)
        .filter(RouteDriverAssignment.route_id == route_id)
        .filter(RouteDriverAssignment.driver_id == driver_id)
        .filter(RouteDriverAssignment.active.is_(True))
        .all()
    )
    if not assignments:
        raise HTTPException(status_code=404, detail="Active route-driver assignment not found")

    # -----------------------------------------------------------
    # - Deactivate assignment
    # - No date tracking needed in current model
    # -----------------------------------------------------------
    for assignment in assignments:
        assignment.active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
