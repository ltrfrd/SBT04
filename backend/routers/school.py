# ===========================================================
# backend/routers/school.py - SBT School Router
# -----------------------------------------------------------
# Handles CRUD operations for schools and links them to routes.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from backend import schemas
from backend.models.company import Company
from backend.models import route as route_model
from backend.models import school as school_model
from backend.utils.company_scope import ensure_route_owner
from backend.utils.company_scope import ensure_same_company
from backend.utils.company_scope import get_company_context
from backend.utils.company_scope import get_company_scoped_record_or_404


router = APIRouter(
    prefix="/schools",
    tags=["Schools"],
)


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
    company: Company = Depends(get_company_context),
):
    new_school = school_model.School(
        **school.model_dump(),
        company_id=company.id,
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
    company: Company = Depends(get_company_context),
):
    return (
        db.query(school_model.School)
        .filter(school_model.School.company_id == company.id)
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
    company: Company = Depends(get_company_context),
):
    return get_company_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=school_id,
        company_id=company.id,
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
    company: Company = Depends(get_company_context),
):
    school = get_company_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=school_id,
        company_id=company.id,
        detail="School not found",
    )

    update_data = school_in.model_dump(exclude_unset=True)
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
    company: Company = Depends(get_company_context),
):
    school = get_company_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=school_id,
        company_id=company.id,
        detail="School not found",
    )
    db.delete(school)
    db.commit()
    return None


@router.post(
    "/{school_id}/assign_route/{route_id}",
    response_model=schemas.SchoolOut,
    summary="Assign route to school",
    description="Link a school to a route. Prevents duplicate assignments.",
    response_description="Updated school with route link",
)
def assign_route_to_school(
    school_id: int,
    route_id: int,
    db: Session = Depends(get_db),
    company: Company = Depends(get_company_context),
):
    school = get_company_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=school_id,
        company_id=company.id,
        detail="School or Route not found",
    )
    route = db.get(route_model.Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="School or Route not found")

    ensure_route_owner(route, company.id)
    ensure_same_company(school, route)

    if route not in school.routes:
        school.routes.append(route)
        db.commit()
        db.refresh(school)

    return school


@router.delete(
    "/{school_id}/unassign_route/{route_id}",
    response_model=schemas.SchoolOut,
    summary="Unassign route from school",
    description="Remove the link between a school and a route.",
    response_description="Updated school without route link",
)
def unassign_route_from_school(
    school_id: int,
    route_id: int,
    db: Session = Depends(get_db),
    company: Company = Depends(get_company_context),
):
    school = get_company_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=school_id,
        company_id=company.id,
        detail="School or Route not found",
    )
    route = db.get(route_model.Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="School or Route not found")

    ensure_route_owner(route, company.id)

    if route in school.routes:
        school.routes.remove(route)
        db.commit()
        db.refresh(school)

    return school
