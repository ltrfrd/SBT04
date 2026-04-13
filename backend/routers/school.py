# ===========================================================
# backend/routers/school.py - FleetOS School Router
# -----------------------------------------------------------
# Handles CRUD operations for schools and links them to routes.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from backend import schemas
from backend.models.district import District
from backend.models.operator import Operator
from backend.models.operator import OperatorRouteAccess
from backend.models import route as route_model
from backend.models import school as school_model
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404


router = APIRouter(
    prefix="/schools",
    tags=["Schools"],
)

district_router = APIRouter(
    prefix="/districts",
    tags=["Schools"],
)


def _planning_relationship_matches(
    *,
    primary_district_id: int | None,
    primary_operator_id: int,
    secondary_district_id: int | None,
    secondary_operator_id: int,
) -> bool:
    if primary_district_id is not None and secondary_district_id is not None:
        return primary_district_id == secondary_district_id
    return primary_operator_id == secondary_operator_id


def _validate_route_school_planning_alignment(
    *,
    route: route_model.Route,
    school_district_id: int | None,
    school_operator_id: int,
) -> None:
    if not _planning_relationship_matches(
        primary_district_id=route.district_id,
        primary_operator_id=route.operator_id,
        secondary_district_id=school_district_id,
        secondary_operator_id=school_operator_id,
    ):
        raise HTTPException(status_code=400, detail="School does not match route district")


def _school_access_filter(operator_id: int):
    return or_(
        school_model.School.operator_id == operator_id,
        school_model.School.routes.any(
            or_(
                route_model.Route.operator_id == operator_id,
                route_model.Route.operator_access.any(OperatorRouteAccess.operator_id == operator_id),
            )
        ),
    )


def _get_school_for_planning_mutation_or_404(
    *,
    db: Session,
    school_id: int,
    operator_id: int,
    detail: str,
) -> school_model.School:
    school = (
        db.query(school_model.School)
        .filter(school_model.School.id == school_id)
        .filter(_school_access_filter(operator_id))
        .first()
    )
    if not school:
        raise HTTPException(status_code=404, detail=detail)
    return school


def _get_school_route_link_context_or_404(
    *,
    db: Session,
    school_id: int,
    route_id: int,
    operator_id: int,
) -> tuple[school_model.School, route_model.Route]:
    school = _get_school_for_planning_mutation_or_404(
        db=db,
        operator_id=operator_id,
        detail="School or Route not found",
        school_id=school_id,
    )
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator_id,
        required_access="read",
    )
    _validate_route_school_planning_alignment(
        route=route,
        school_district_id=school.district_id,
        school_operator_id=school.operator_id,
    )
    return school, route


@router.post(
    "/",
    response_model=schemas.SchoolOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create school",
    description="Create a new school record.",
    response_description="Created school",
)
def create_school(
    school: schemas.SchoolCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    new_school = school_model.School(
        **school.model_dump(),
        operator_id=operator.id,
    )
    db.add(new_school)
    db.commit()
    db.refresh(new_school)
    return new_school


@district_router.post(
    "/{district_id}/schools",
    response_model=schemas.SchoolOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create school under district",
    description="Create a new school record under the selected district context.",
    response_description="Created school",
)
def create_school_for_district(
    district_id: int,
    school: schemas.SchoolCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    district = db.get(District, district_id)
    if not district:
        raise HTTPException(status_code=404, detail="District not found")

    new_school = school_model.School(
        **school.model_dump(exclude={"district_id"}),
        district_id=district_id,
        operator_id=operator.id,
    )
    db.add(new_school)
    db.commit()
    db.refresh(new_school)
    return new_school


@router.get(
    "/",
    response_model=List[schemas.SchoolOut],
    summary="List schools",
    description="Return all registered school records.",
    response_description="School list",
)
def get_schools(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return (
        db.query(school_model.School)
        .filter(_school_access_filter(operator.id))
        .all()
    )


@router.get(
    "/{school_id}",
    response_model=schemas.SchoolOut,
    summary="Get school",
    description="Return a single school record by id.",
    response_description="School record",
)
def get_school(
    school_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    school = (
        db.query(school_model.School)
        .filter(school_model.School.id == school_id)
        .filter(_school_access_filter(operator.id))
        .first()
    )
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    return school


@router.put(
    "/{school_id}",
    response_model=schemas.SchoolOut,
    summary="Update school",
    description="Update an existing school record by id.",
    response_description="Updated school",
)
def update_school(
    school_id: int,
    school_in: schemas.SchoolCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    school = _get_school_for_planning_mutation_or_404(
        db=db,
        operator_id=operator.id,
        detail="School not found",
        school_id=school_id,
    )

    update_data = school_in.model_dump(exclude_unset=True)
    target_district_id = update_data.get("district_id", school.district_id)
    for route in school.routes:
        _validate_route_school_planning_alignment(
            route=route,
            school_district_id=target_district_id,
            school_operator_id=school.operator_id,
        )
    for key, value in update_data.items():
        setattr(school, key, value)

    db.commit()
    db.refresh(school)
    return school


@router.delete(
    "/{school_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete school",
    description="Delete a school record by id.",
    response_description="School deleted",
)
def delete_school(
    school_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    school = _get_school_for_planning_mutation_or_404(
        db=db,
        operator_id=operator.id,
        detail="School not found",
        school_id=school_id,
    )
    db.delete(school)
    db.commit()
    return None


@router.post(
    "/{school_id}/assign_route/{route_id}",
    response_model=schemas.SchoolOut,
    summary="Assign route to school",
    description="Link a school to a route while keeping the route as the planning source of truth. Prevents duplicate assignments.",
    response_description="Updated school with route link",
)
def assign_route_to_school(
    school_id: int,
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    school, route = _get_school_route_link_context_or_404(
        db=db,
        school_id=school_id,
        route_id=route_id,
        operator_id=operator.id,
    )

    if school not in route.schools:
        route.schools.append(school)
        db.commit()
    db.refresh(school)
    return school


@router.delete(
    "/{school_id}/unassign_route/{route_id}",
    response_model=schemas.SchoolOut,
    summary="Unassign route from school",
    description="Remove the link between a school and a route while keeping route context authoritative.",
    response_description="Updated school without route link",
)
def unassign_route_from_school(
    school_id: int,
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    school, route = _get_school_route_link_context_or_404(
        db=db,
        school_id=school_id,
        route_id=route_id,
        operator_id=operator.id,
    )

    if school in route.schools:
        route.schools.remove(school)
        db.commit()
    db.refresh(school)
    return school

