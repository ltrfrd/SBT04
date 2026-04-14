from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from database import get_db
from backend import schemas
from backend.models.associations import RouteDriverAssignment
from backend.models.district import District
from backend.models.operator import Operator
from backend.models.route import Route
from backend.models import run as run_model
from backend.models.school import School
from backend.models.student import Student
from backend.routers.route import _serialize_route, create_route_record
from backend.routers.school import create_school_record
from backend.utils.operator_scope import get_operator_context
from backend.utils.planning_scope import accessible_route_filter, accessible_school_filter


router = APIRouter(prefix="/districts", tags=["Districts"])


def _get_district_or_404(*, db: Session, district_id: int) -> District:
    district = db.get(District, district_id)
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    return district


@router.get(
    "/",
    response_model=list[schemas.DistrictOut],
    summary="List districts",
    description="Return all districts available as top-level planning workspaces.",
    response_description="District list",
)
def get_districts(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_operator_context),
):
    return (
        db.query(District)
        .order_by(District.name.asc(), District.id.asc())
        .all()
    )


@router.post(
    "/",
    response_model=schemas.DistrictOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create district",
    description="Create a district planning workspace.",
    response_description="Created district",
)
def create_district(
    payload: schemas.DistrictCreate,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_operator_context),
):
    district = District(**payload.model_dump())
    db.add(district)
    db.commit()
    db.refresh(district)
    return district


@router.get(
    "/{district_id}",
    response_model=schemas.DistrictOut,
    summary="Get district detail",
    description="Return one district planning workspace by id.",
    response_description="District detail",
)
def get_district(
    district_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_operator_context),
):
    return _get_district_or_404(db=db, district_id=district_id)


@router.get(
    "/{district_id}/schools",
    response_model=list[schemas.SchoolOut],
    summary="List district schools",
    description="Return schools in the selected district that are visible through current planning access rules.",
    response_description="District schools",
)
def get_district_schools(
    district_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    return (
        db.query(School)
        .filter(School.district_id == district_id)
        .filter(accessible_school_filter(operator.id))
        .order_by(School.name.asc(), School.id.asc())
        .all()
    )


@router.post(
    "/{district_id}/schools",
    response_model=schemas.SchoolOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create district school",
    description="Create a school under the selected district context.",
    response_description="Created school",
)
def create_district_school(
    district_id: int,
    school: schemas.SchoolCreate,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    new_school = create_school_record(
        school=school,
        db=db,
        district_id=district_id,
    )
    db.commit()
    db.refresh(new_school)
    return new_school


@router.get(
    "/{district_id}/routes",
    response_model=list[schemas.RouteOut],
    summary="List district routes",
    description="Return routes in the selected district that are visible through current planning access rules.",
    response_description="District routes",
)
def get_district_routes(
    district_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    routes = (
        db.query(Route)
        .options(
            selectinload(Route.schools),
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),
            selectinload(Route.runs).selectinload(run_model.Run.stops),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments),
        )
        .filter(Route.district_id == district_id)
        .filter(accessible_route_filter(operator.id))
        .order_by(Route.route_number.asc(), Route.id.asc())
        .all()
    )
    return [_serialize_route(route) for route in routes]


@router.post(
    "/{district_id}/routes",
    response_model=schemas.RouteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create district route",
    description="Create a route under the selected district context.",
    response_description="Created route",
    responses={
        409: {
            "description": "Route number already exists",
            "content": {"application/json": {"example": {"detail": "Route number already exists"}}},
        }
    },
)
def create_district_route(
    district_id: int,
    route: schemas.RouteCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    db_route = create_route_record(
        route=route,
        db=db,
        operator_id=operator.id,
        district_id=district_id,
    )
    db.commit()
    db.refresh(db_route)
    return _serialize_route(db_route)


@router.get(
    "/{district_id}/summary",
    response_model=schemas.DistrictSummaryOut,
    summary="Get district summary",
    description="Return lightweight planning counts for the selected district.",
    response_description="District summary",
)
def get_district_summary(
    district_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    return schemas.DistrictSummaryOut(
        district_id=district_id,
        schools_count=db.query(School).filter(School.district_id == district_id).count(),
        routes_count=db.query(Route).filter(Route.district_id == district_id).count(),
        students_count=db.query(Student).filter(Student.district_id == district_id).count(),
    )
