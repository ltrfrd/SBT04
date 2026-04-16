from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db

from backend import schemas
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import RouteDriverAssignment
from backend.models.associations import StudentRunAssignment
from backend.models.operator import Operator
from backend.models.route import Route
from backend.routers.route_helpers import _serialize_route
from backend.routers.route_helpers import _serialize_route_detail
from backend.routers.run_helpers import _serialize_run
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import accessible_route_filter


router = APIRouter(tags=["Routes"])


@router.get(
    "/",
    response_model=List[schemas.RouteOut],
    summary="List routes",
    description="Return lightweight route summaries with school, driver, run, stop, and student counts for navigation.",
    response_description="Route summary list",
)
def get_routes(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    routes = (
        db.query(Route)
        .options(
            selectinload(Route.schools),
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),
            selectinload(Route.runs).selectinload(run_model.Run.stops),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments),
        )
        .filter(accessible_route_filter(operator.id))
        .order_by(Route.route_number.asc(), Route.id.asc())
        .all()
    )
    return [_serialize_route(route) for route in routes]


@router.get(
    "/{route_id}",
    response_model=schemas.RouteDetailOut,
    summary="Get route detail",
    description="Return one route with nested schools, driver assignments, runs, stops, and runtime student details.",
    response_description="Route detail",
)
def get_route(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = (
        db.query(Route)
        .options(
            selectinload(Route.schools),
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),
            selectinload(Route.runs).selectinload(run_model.Run.driver),
            selectinload(Route.runs).selectinload(run_model.Run.stops),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),
        )
        .filter(Route.id == route_id)
        .filter(accessible_route_filter(operator.id))
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return _serialize_route_detail(route)


@router.get(
    "/{route_id}/runs",
    response_model=List[schemas.RunOut],
    summary="List runs inside route",
    description="Return all planned runs that belong to the selected route.",
    response_description="Route runs",
)
def get_route_runs(
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

    runs = (
        db.query(run_model.Run)
        .filter(run_model.Run.route_id == route.id)
        .order_by(run_model.Run.id.asc())
        .all()
    )
    return [_serialize_run(run) for run in runs]


@router.get(
    "/{route_id}/stops",
    response_model=List[schemas.StopOut],
    summary="List stops inside route",
    description="Return all planned stops that belong to the selected route.",
    response_description="Route stops",
)
def get_route_stops(
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

    return (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.route_id == route.id)
        .order_by(stop_model.Stop.run_id.asc(), stop_model.Stop.sequence.asc(), stop_model.Stop.id.asc())
        .all()
    )


@router.get(
    "/{route_id}/students",
    response_model=List[schemas.StudentOut],
    summary="List students inside route",
    description="Return all planning-side student records linked directly to the selected route.",
    response_description="Route students",
)
def get_route_students(
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

    return (
        db.query(student_model.Student)
        .filter(student_model.Student.route_id == route.id)
        .order_by(student_model.Student.name.asc(), student_model.Student.id.asc())
        .all()
    )


@router.get("/{route_id}/schools", response_model=List[dict])
def get_route_schools(
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

    return [{"id": s.id, "name": s.name, "address": s.address} for s in route.schools]


@router.get(
    "/{route_id}/drivers",
    response_model=List[schemas.RouteDriverAssignmentOut],
    summary="List route driver assignments",
    description=(
        "Return all driver assignments for the route, including which assignment is currently active "
        "for operations and which assignment is the primary/default route owner. "
        "Operational run logic follows the active/current assignment only. "
        "Legacy date fields are not authoritative for live routing."
    ),
    response_description="Route driver assignment list",
)
def get_route_drivers(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )

    return [
        schemas.RouteDriverAssignmentOut(
            id=assignment.id,
            route_id=assignment.route_id,
            driver_id=assignment.driver_id,
            driver_name=assignment.driver.name if assignment.driver else None,
            active=assignment.active,
            is_primary=assignment.is_primary,
        )
        for assignment in sorted(
            route.driver_assignments,
            key=lambda assignment: (not assignment.active, not assignment.is_primary, assignment.id),
        )
    ]
