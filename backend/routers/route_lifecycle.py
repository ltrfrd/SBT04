from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from database import get_db

from backend.models.associations import RouteDriverAssignment
from backend.models.district import District
from backend.models.operator import Operator
from backend.models.route import Route
from backend.routers.route_helpers import _get_conflicting_route_or_none
from backend.routers.route_helpers import _serialize_route
from backend.routers.route_helpers import create_route_record
from backend.schemas.route import RouteCreate, RouteOut
from backend.utils.operator_scope import ensure_route_owner
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import get_schools_for_route_attachment_or_404
from backend.utils.planning_scope import validate_route_school_links


router = APIRouter(tags=["Routes"])


@router.post(
    "/",
    response_model=RouteOut,
    summary="Create route",
    description=(
        "Create a route with route_number and optional school_ids only. "
        "Bus assignment is handled separately. "
        "Driver assignment is also handled separately. "
        "Route numbers must be unique."
    ),
    response_description="Created route",
    responses={
        409: {
            "description": "Route number already exists",
            "content": {
                "application/json": {
                    "example": {"detail": "Route number already exists"}
                }
            },
        }
    },
)
def create_route(
    route: RouteCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    db_route = create_route_record(
        route=route,
        db=db,
        operator_id=operator.id,
    )
    db.commit()
    db.refresh(db_route)
    return _serialize_route(db_route)


@router.put(
    "/{route_id}",
    response_model=RouteOut,
    summary="Update route",
    description=(
        "Update one route with route_number and optional school_ids only. "
        "Bus assignment is handled separately. "
        "Driver assignment remains separate."
    ),
    response_description="Updated route",
)
def update_route(
    route_id: int,
    route_in: RouteCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
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
    ensure_route_owner(route, operator.id)

    update_data = route_in.model_dump(exclude_unset=True)
    school_ids = update_data.pop("school_ids", None)
    schools = None
    new_route_number = update_data.get("route_number", route.route_number)
    target_district_id = update_data.get("district_id", route.district_id)
    if target_district_id is None:
        raise HTTPException(status_code=400, detail="district_id is required")
    district = db.get(District, target_district_id)
    if not district:
        raise HTTPException(status_code=404, detail="District not found")

    if (
        new_route_number != route.route_number
        or target_district_id != route.district_id
    ):
        existing_route = _get_conflicting_route_or_none(
            db=db,
            route_number=new_route_number,
            district_id=target_district_id,
            operator_id=operator.id,
            exclude_route_id=route_id,
        )

        if existing_route:
            raise HTTPException(
                status_code=409,
                detail="Route number already exists",
            )
    for key, value in update_data.items():
        setattr(route, key, value)

    if school_ids is not None:
        schools = get_schools_for_route_attachment_or_404(
            db=db,
            school_ids=school_ids,
        )

    validate_route_school_links(
        route_district_id=target_district_id,
        route_operator_id=None,
        schools=schools if schools is not None else list(route.schools),
    )

    if school_ids is not None:
        route.schools = schools

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    ensure_route_owner(route, operator.id)
    db.delete(route)
    db.commit()
    return None
