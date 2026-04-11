from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, selectinload

from database import get_db
from backend.models.company import Company
from backend.models.company import CompanyRouteAccess
from backend.models.route import Route


DEFAULT_COMPANY_NAME = "Default Company"
ROUTE_ACCESS_PRIORITY = {
    "read": 1,
    "operate": 2,
}


def get_or_create_default_company(db: Session) -> Company:
    company = (
        db.query(Company)
        .order_by(Company.id.asc())
        .first()
    )
    if company:
        return company

    company = Company(name=DEFAULT_COMPANY_NAME)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def get_company_context(
    request: Request,
    db: Session = Depends(get_db),
) -> Company:
    session_company_id = request.session.get("company_id")
    if session_company_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    company = db.get(Company, int(session_company_id))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def get_company_scoped_record_or_404(
    *,
    db: Session,
    model,
    record_id: int,
    company_id: int,
    detail: str,
):
    record = (
        db.query(model)
        .filter(model.id == record_id)
        .filter(model.company_id == company_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail=detail)
    return record


def _route_access_satisfies(access_level: str | None, required_access: str) -> bool:
    if access_level == "owner":
        return True
    if access_level is None:
        return False
    return ROUTE_ACCESS_PRIORITY.get(access_level, 0) >= ROUTE_ACCESS_PRIORITY.get(required_access, 0)


def get_route_access_level(route: Route, company_id: int) -> str | None:
    if route.company_id == company_id:
        return "owner"

    for grant in route.company_access:
        if grant.company_id == company_id:
            return grant.access_level

    return None


def get_company_scoped_route_or_404(
    *,
    db: Session,
    route_id: int,
    company_id: int,
    required_access: str = "read",
    options: list | None = None,
) -> Route:
    query = db.query(Route).options(selectinload(Route.company_access))
    if options:
        query = query.options(*options)

    route = (
        query
        .filter(Route.id == route_id)
        .first()
    )
    if not route or not _route_access_satisfies(get_route_access_level(route, company_id), required_access):
        raise HTTPException(status_code=404, detail="Route not found")
    return route


def ensure_route_owner(route: Route, company_id: int) -> None:
    if route.company_id != company_id:
        raise HTTPException(status_code=404, detail="Route not found")


def ensure_same_company(*records) -> None:
    company_ids = {record.company_id for record in records}
    if len(company_ids) > 1:
        raise HTTPException(status_code=400, detail="Cross-company association is not allowed")


def create_company_route_access(
    *,
    route_id: int,
    company_id: int,
    access_level: str,
) -> CompanyRouteAccess:
    return CompanyRouteAccess(
        route_id=route_id,
        company_id=company_id,
        access_level=access_level,
    )
