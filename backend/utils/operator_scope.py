from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, selectinload

from database import get_db
from backend.models import bus as bus_model
from backend.models.dispatcher import Dispatcher
from backend.models import driver as driver_model
from backend.models.operator import Operator
from backend.models.operator import OperatorRouteAccess
from backend.models.route import Route
from backend.models.yard import Yard


# -----------------------------------------------------------
# Yard-domain operator scope helpers
# -----------------------------------------------------------
DEFAULT_OPERATOR_NAME = "Default Operator"
ROUTE_ACCESS_PRIORITY = {
    "read": 1,
    "operate": 2,
    "owner": 3,
}


def get_or_create_default_operator(db: Session) -> Operator:
    operator = (
        db.query(Operator)
        .order_by(Operator.id.asc())
        .first()
    )
    if operator:
        return operator

    operator = Operator(name=DEFAULT_OPERATOR_NAME)
    db.add(operator)
    db.commit()
    db.refresh(operator)
    return operator


def get_operator_context(
    request: Request,
    db: Session = Depends(get_db),
) -> Operator:
    session_operator_id = request.session.get("operator_id")
    if session_operator_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    operator = db.get(Operator, int(session_operator_id))
    if not operator:
        raise HTTPException(status_code=404, detail="Operator not found")
    return operator


def get_operator_scoped_yard_or_404(
    *,
    db: Session,
    yard_id: int,
    operator_id: int,
    detail: str,
) -> Yard:
    yard = (
        db.query(Yard)
        .filter(Yard.id == yard_id)
        .filter(Yard.operator_id == operator_id)
        .first()
    )
    if not yard:
        raise HTTPException(status_code=404, detail=detail)
    return yard


def get_operator_scoped_record_or_404(
    *,
    db: Session,
    model,
    record_id: int,
    operator_id: int,
    detail: str,
):
    if model is driver_model.Driver:
        return get_operator_scoped_driver_or_404(
            db=db,
            driver_id=record_id,
            operator_id=operator_id,
            detail=detail,
        )
    if model is bus_model.Bus:
        return get_operator_scoped_bus_or_404(
            db=db,
            bus_id=record_id,
            operator_id=operator_id,
            detail=detail,
        )

    record = (
        db.query(model)
        .filter(model.id == record_id)
        .filter(model.operator_id == operator_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail=detail)
    return record


def get_operator_scoped_driver_or_404(
    *,
    db: Session,
    driver_id: int,
    operator_id: int,
    detail: str,
):
    driver = (
        db.query(driver_model.Driver)
        .join(driver_model.Driver.yard)
        .filter(driver_model.Driver.id == driver_id)
        .filter(Yard.operator_id == operator_id)
        .first()
    )
    if not driver:
        raise HTTPException(status_code=404, detail=detail)
    return driver


def get_operator_scoped_dispatcher_or_404(
    *,
    db: Session,
    dispatcher_id: int,
    operator_id: int,
    detail: str,
) -> Dispatcher:
    dispatcher = (
        db.query(Dispatcher)
        .join(Dispatcher.yard)
        .filter(Dispatcher.id == dispatcher_id)
        .filter(Yard.operator_id == operator_id)
        .first()
    )
    if not dispatcher:
        raise HTTPException(status_code=404, detail=detail)
    return dispatcher


def get_operator_scoped_bus_or_404(
    *,
    db: Session,
    bus_id: int,
    operator_id: int,
    detail: str,
    options: list | None = None,
):
    query = db.query(bus_model.Bus).join(bus_model.Bus.yard)
    if options:
        query = query.options(*options)

    bus = (
        query
        .filter(bus_model.Bus.id == bus_id)
        .filter(Yard.operator_id == operator_id)
        .first()
    )
    if not bus:
        raise HTTPException(status_code=404, detail=detail)
    return bus


def get_driver_operator_id(driver: driver_model.Driver) -> int:
    if not driver.yard:
        raise HTTPException(status_code=400, detail="Driver is missing yard assignment")
    return driver.yard.operator_id


def get_bus_operator_id(bus: bus_model.Bus) -> int:
    if not bus.yard:
        raise HTTPException(status_code=400, detail="Bus is missing yard assignment")
    return bus.yard.operator_id


def get_record_operator_id(record) -> int:
    if isinstance(record, driver_model.Driver):
        return get_driver_operator_id(record)
    if isinstance(record, bus_model.Bus):
        return get_bus_operator_id(record)
    return record.operator_id


def _route_access_satisfies(access_level: str | None, required_access: str) -> bool:
    if access_level == "owner":
        return True
    if access_level is None:
        return False
    return ROUTE_ACCESS_PRIORITY.get(access_level, 0) >= ROUTE_ACCESS_PRIORITY.get(required_access, 0)


def get_route_access_level(route: Route, operator_id: int) -> str | None:
    resolved_access_level = None
    for grant in route.operator_access:
        if grant.operator_id == operator_id:
            if resolved_access_level is None:
                resolved_access_level = grant.access_level
                continue
            if ROUTE_ACCESS_PRIORITY.get(grant.access_level, 0) > ROUTE_ACCESS_PRIORITY.get(resolved_access_level, 0):
                resolved_access_level = grant.access_level

    return resolved_access_level


def get_operator_scoped_route_or_404(
    *,
    db: Session,
    route_id: int,
    operator_id: int,
    required_access: str = "read",
    options: list | None = None,
) -> Route:
    query = db.query(Route).options(selectinload(Route.operator_access))
    if options:
        query = query.options(*options)

    route = (
        query
        .filter(Route.id == route_id)
        .first()
    )
    if not route or not _route_access_satisfies(get_route_access_level(route, operator_id), required_access):
        raise HTTPException(status_code=404, detail="Route not found")
    return route


def ensure_route_owner(route: Route, operator_id: int) -> None:
    if not _route_access_satisfies(get_route_access_level(route, operator_id), "owner"):
        raise HTTPException(status_code=404, detail="Route not found")


def ensure_same_operator(*records) -> None:
    operator_ids = {get_record_operator_id(record) for record in records}
    if len(operator_ids) > 1:
        raise HTTPException(status_code=400, detail="Cross-operator association is not allowed")


def create_operator_route_access(
    *,
    route_id: int,
    operator_id: int,
    access_level: str,
) -> OperatorRouteAccess:
    return OperatorRouteAccess(
        route_id=route_id,
        operator_id=operator_id,
        access_level=access_level,
    )

