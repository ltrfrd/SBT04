from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from database import get_db
from backend import schemas
from backend.models.associations import RouteDriverAssignment
from backend.models.district import District
from backend.models.operator import Operator
from backend.models.route import Route
from backend.models import run as run_model
from backend.models.run import Run
from backend.models.school import School
from backend.models.stop import Stop
from backend.models.student import Student
from backend.models.yard import Yard
from backend.routers import route_lifecycle as route_lifecycle_router
from backend.routers import route_setup_routes as route_setup_router
from backend.routers.route_helpers import _serialize_route
from backend.routers.school import create_school_record
from backend.schemas.run import RouteRunCreate, RunUpdate
from backend.schemas.stop import RunStopCreate, StopUpdate
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import accessible_route_filter, accessible_school_filter
from backend.utils.planning_scope import get_route_run_or_404
from backend.utils.planning_scope import get_route_stop_or_404


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
    route_payload = route.model_copy(update={"district_id": district_id})
    return route_lifecycle_router.create_route(
        route=route_payload,
        db=db,
        operator=operator,
    )


def _get_district_scoped_route_or_404(
    *,
    db: Session,
    district_id: int,
    route_id: int,
    operator_id: int,
) -> Route:
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator_id,
        required_access="operate",
    )
    if route.district_id != district_id:
        raise HTTPException(status_code=404, detail="Route not found for district")
    return route


def _get_district_scoped_run_or_404(
    *,
    db: Session,
    district_id: int,
    route_id: int,
    run_id: int,
    operator_id: int,
) -> tuple[Route, Run]:
    route = _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator_id,
    )
    run = get_route_run_or_404(route_id=route.id, run_id=run_id, db=db)
    return route, run


def _get_district_scoped_stop_or_404(
    *,
    db: Session,
    district_id: int,
    route_id: int,
    stop_id: int,
    operator_id: int,
) -> tuple[Route, Stop]:
    route = _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator_id,
    )
    stop = get_route_stop_or_404(route_id=route.id, stop_id=stop_id, db=db)
    return route, stop


@router.put(
    "/{district_id}/routes/{route_id}",
    response_model=schemas.RouteOut,
    summary="Update district route",
    description="Update a route under the selected district context. The path district_id and route_id are authoritative.",
    response_description="Updated route",
)
def update_district_route(
    district_id: int,
    route_id: int,
    route_in: schemas.RouteCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator.id,
    )
    route_payload = route_in.model_copy(update={"district_id": district_id})
    return route_lifecycle_router.update_route(
        route_id=route_id,
        route_in=route_payload,
        db=db,
        operator=operator,
    )


@router.delete(
    "/{district_id}/routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete district route",
    description="Delete a route under the selected district context. The path district_id and route_id are authoritative.",
    response_description="Route deleted",
)
def delete_district_route(
    district_id: int,
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator.id,
    )
    return route_lifecycle_router.delete_route(
        route_id=route_id,
        db=db,
        operator=operator,
    )


@router.post(
    "/{district_id}/routes/{route_id}/runs",
    response_model=schemas.RunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create run inside district route",
    description="Create a planned run under the selected district route context without changing existing route-scoped endpoints.",
    response_description="Created run",
)
def create_district_route_run(
    district_id: int,
    route_id: int,
    payload: RouteRunCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator.id,
    )
    return route_setup_router.create_route_run(
        route_id=route_id,
        payload=payload,
        db=db,
        operator=operator,
    )


@router.put(
    "/{district_id}/routes/{route_id}/runs/{run_id}",
    response_model=schemas.RunOut,
    summary="Update run inside district route",
    description="Update one planned run under the selected district route context. The path district_id, route_id, and run_id are authoritative.",
    response_description="Updated run",
)
def update_district_route_run(
    district_id: int,
    route_id: int,
    run_id: int,
    payload: RunUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_run_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        run_id=run_id,
        operator_id=operator.id,
    )
    return route_setup_router.update_route_run(
        route_id=route_id,
        run_id=run_id,
        payload=payload,
        db=db,
        operator=operator,
    )


@router.delete(
    "/{district_id}/routes/{route_id}/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete run inside district route",
    description="Delete one planned run under the selected district route context. The path district_id, route_id, and run_id are authoritative.",
    response_description="Run deleted",
)
def delete_district_route_run(
    district_id: int,
    route_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_run_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        run_id=run_id,
        operator_id=operator.id,
    )
    return route_setup_router.delete_route_run(
        route_id=route_id,
        run_id=run_id,
        db=db,
        operator=operator,
    )


@router.post(
    "/{district_id}/routes/{route_id}/runs/{run_id}/stops",
    response_model=schemas.StopOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create stop inside district route run",
    description="Create one planned stop under the selected district route-run context without changing existing route-scoped endpoints.",
    response_description="Created stop",
)
def create_district_route_run_stop(
    district_id: int,
    route_id: int,
    run_id: int,
    payload: RunStopCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_run_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        run_id=run_id,
        operator_id=operator.id,
    )
    return route_setup_router.create_route_run_stop(
        route_id=route_id,
        run_id=run_id,
        payload=payload,
        db=db,
        operator=operator,
    )


@router.put(
    "/{district_id}/routes/{route_id}/stops/{stop_id}",
    response_model=schemas.StopOut,
    summary="Update stop inside district route",
    description="Update one planned stop under the selected district route context. The path district_id, route_id, and stop_id are authoritative.",
    response_description="Updated stop",
)
def update_district_route_stop(
    district_id: int,
    route_id: int,
    stop_id: int,
    payload: StopUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_stop_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        stop_id=stop_id,
        operator_id=operator.id,
    )
    return route_setup_router.update_route_stop(
        route_id=route_id,
        stop_id=stop_id,
        payload=payload,
        db=db,
        operator=operator,
    )


@router.delete(
    "/{district_id}/routes/{route_id}/stops/{stop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete stop inside district route",
    description="Delete one planned stop under the selected district route context. The path district_id, route_id, and stop_id are authoritative.",
    response_description="Stop deleted",
)
def delete_district_route_stop(
    district_id: int,
    route_id: int,
    stop_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    _get_district_scoped_stop_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        stop_id=stop_id,
        operator_id=operator.id,
    )
    return route_setup_router.delete_route_stop(
        route_id=route_id,
        stop_id=stop_id,
        db=db,
        operator=operator,
    )


@router.post(
    "/{district_id}/routes/{route_id}/assign-yard/{yard_id}",
    summary="Assign district route to yard",
    description="Link a district-backed route to one yard owned by the acting operator through district planning context.",
)
def assign_district_route_to_yard(
    district_id: int,
    route_id: int,
    yard_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    route = _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator.id,
    )

    yard = db.get(Yard, yard_id)
    if not yard:
        raise HTTPException(status_code=404, detail="Yard not found")
    if yard.operator_id != operator.id:
        raise HTTPException(status_code=403, detail="Yard is not allowed for this route")

    if all(existing_yard.id != yard.id for existing_yard in route.yards):
        route.yards.append(yard)

    db.commit()
    return {"district_id": district_id, "route_id": route_id, "yard_id": yard_id}


@router.delete(
    "/{district_id}/routes/{route_id}/assign-yard/{yard_id}",
    summary="Unassign district route from yard",
    description="Remove one yard link from a district-backed route through district planning context.",
)
def unassign_district_route_from_yard(
    district_id: int,
    route_id: int,
    yard_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_district_or_404(db=db, district_id=district_id)
    route = _get_district_scoped_route_or_404(
        db=db,
        district_id=district_id,
        route_id=route_id,
        operator_id=operator.id,
    )

    yard = db.get(Yard, yard_id)
    if not yard:
        raise HTTPException(status_code=404, detail="Yard not found")
    if yard.operator_id != operator.id:
        raise HTTPException(status_code=403, detail="Yard is not allowed for this route")

    linked_yard = next((existing_yard for existing_yard in route.yards if existing_yard.id == yard.id), None)
    if linked_yard is not None:
        route.yards.remove(linked_yard)

    db.commit()
    return {"district_id": district_id, "route_id": route_id, "yard_id": yard_id}


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
