# ===========================================================
# backend/routers/school.py - FleetOS School Router
# -----------------------------------------------------------
# Handles CRUD operations for schools and links them to routes.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from backend import schemas
from backend.models.district import District
from backend.models.operator import Operator
from backend.models import route as route_model
from backend.models import school as school_model
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import (
    accessible_school_filter,
    get_school_for_planning_or_404,
    validate_planning_alignment,
    validate_route_school_alignment,
)


router = APIRouter(
    prefix="/schools",
    tags=["Schools"],
)


def _raise_district_planning_path_retired() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "School-route planning mutations now belong to district-nested route planning paths. "
            "Use /districts/{district_id}/routes/{route_id} to manage school links."
        ),
    )

def _get_school_for_planning_mutation_or_404(
    *,
    db: Session,
    school_id: int,
    operator_id: int,
    detail: str,
) -> school_model.School:
    return get_school_for_planning_or_404(
        db=db,
        school_id=school_id,
        operator_id=operator_id,
        detail=detail,
    )


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
    validate_route_school_alignment(
        route_district_id=route.district_id,
        route_operator_id=None,
        school=school,
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
    _: Operator = Depends(get_operator_context),
):
    new_school = create_school_record(
        school=school,
        db=db,
    )
    db.commit()
    db.refresh(new_school)
    return new_school


def create_school_record(
    *,
    school: schemas.SchoolCreate,
    db: Session,
    district_id: int | None = None,
) -> school_model.School:
    payload = school.model_dump()
    payload.pop("district_id", None)
    effective_district_id = district_id if district_id is not None else school.district_id
    if effective_district_id is None:
        raise HTTPException(status_code=400, detail="district_id is required")
    district = db.get(District, effective_district_id)
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    new_school = school_model.School(
        **payload,
        district_id=effective_district_id,
    )
    db.add(new_school)
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
        .filter(accessible_school_filter(operator.id))
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
    return get_school_for_planning_or_404(
        db=db,
        school_id=school_id,
        operator_id=operator.id,
        detail="School not found",
    )


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
    if target_district_id is None:
        raise HTTPException(status_code=400, detail="district_id is required")
    district = db.get(District, target_district_id)
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    for route in school.routes:
        validate_planning_alignment(
            primary_district_id=route.district_id,
            primary_operator_id=None,
            secondary_district_id=target_district_id,
            secondary_operator_id=None,
            detail="School does not match route district",
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
    include_in_schema=False,
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
    _raise_district_planning_path_retired()
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
    include_in_schema=False,
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
    _raise_district_planning_path_retired()
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

