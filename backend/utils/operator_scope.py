from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, selectinload

from database import get_db
from backend.models import driver as driver_model
from backend.models.operator import Operator
from backend.models.operator import OperatorRouteAccess
from backend.models.route import Route
from backend.models.yard import Yard


DEFAULT_OPERATOR_NAME = "Default Operator"
ROUTE_ACCESS_PRIORITY = {
    "read": 1,
    "operate": 2,
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


def get_operator_scoped_record_or_404(
    *,
    db: Session,
    model,
    record_id: int,
    operator_id: int,
    detail: str,
):
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


def _route_access_satisfies(access_level: str | None, required_access: str) -> bool:
    if access_level == "owner":
        return True
    if access_level is None:
        return False
    return ROUTE_ACCESS_PRIORITY.get(access_level, 0) >= ROUTE_ACCESS_PRIORITY.get(required_access, 0)


def get_route_access_level(route: Route, operator_id: int) -> str | None:
    if route.operator_id == operator_id:
        return "owner"

    for grant in route.operator_access:
        if grant.operator_id == operator_id:
            return grant.access_level

    return None


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
    if route.operator_id != operator_id:
        raise HTTPException(status_code=404, detail="Route not found")


def ensure_same_operator(*records) -> None:
    operator_ids = {record.operator_id for record in records}
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

