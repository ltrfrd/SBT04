from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db

from backend import schemas
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import RouteDriverAssignment
from backend.models.operator import Operator
from backend.models.route import Route
from backend.models.school import School
from backend.routers.route_helpers import _create_route_run_stop
from backend.routers.run_helpers import _assert_unique_route_run_type
from backend.routers.run_helpers import _create_planned_run
from backend.routers.run_helpers import _serialize_run
from backend.schemas.run import RouteRunCreate, RunUpdate
from backend.schemas.stop import RunStopCreate, StopOut, StopUpdate
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.planning_scope import get_route_run_or_404
from backend.utils.planning_scope import get_route_stop_or_404
from backend.utils.planning_scope import get_route_student_or_404


router = APIRouter(tags=["Routes"])


def _raise_district_planning_path_retired() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Route planning mutations now belong to district-nested planning paths. "
            "Use /districts/{district_id}/routes/{route_id}/... planning endpoints."
        ),
    )


def _create_route_run_internal(
    *,
    route_id: int,
    payload: RouteRunCreate,
    db: Session,
    operator: Operator,
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver)],
    )

    new_run = _create_planned_run(
        route=route,
        run_type=payload.run_type,
        scheduled_start_time=payload.scheduled_start_time,
        scheduled_end_time=payload.scheduled_end_time,
        db=db,
    )
    db.commit()
    db.refresh(new_run)
    return _serialize_run(new_run)


def _update_route_run_internal(
    *,
    route_id: int,
    run_id: int,
    payload: RunUpdate,
    db: Session,
    operator: Operator,
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    run = get_route_run_or_404(route_id=route.id, run_id=run_id, db=db)

    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be updated")

    _assert_unique_route_run_type(
        route_id=route.id,
        normalized_run_type=payload.run_type,
        db=db,
        exclude_run_id=run.id,
    )
    run.run_type = payload.run_type
    if payload.scheduled_start_time is not None:
        run.scheduled_start_time = payload.scheduled_start_time
    if payload.scheduled_end_time is not None:
        run.scheduled_end_time = payload.scheduled_end_time

    db.commit()
    db.refresh(run)
    return _serialize_run(run)


def _delete_route_run_internal(
    *,
    route_id: int,
    run_id: int,
    db: Session,
    operator: Operator,
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    run = get_route_run_or_404(route_id=route.id, run_id=run_id, db=db)

    if run.start_time is not None:
        raise HTTPException(status_code=400, detail="Only planned runs can be deleted")

    db.delete(run)
    db.commit()
    return None


def _create_route_run_stop_internal(
    *,
    route_id: int,
    run_id: int,
    payload: RunStopCreate,
    db: Session,
    operator: Operator,
):
    return _create_route_run_stop(
        route_id=route_id,
        run_id=run_id,
        payload=payload,
        db=db,
        operator=operator,
    )


def _update_route_stop_internal(
    *,
    route_id: int,
    stop_id: int,
    payload: StopUpdate,
    db: Session,
    operator: Operator,
):
    from backend.routers import stop as stop_router

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    stop = get_route_stop_or_404(route_id=route.id, stop_id=stop_id, db=db)

    updated_stop = stop_router._update_stop_record(
        stop=stop,
        payload=schemas.RunStopUpdate(
            sequence=payload.sequence,
            type=payload.type,
            name=payload.name,
            school_id=payload.school_id,
            address=payload.address,
            planned_time=payload.planned_time,
            latitude=payload.latitude,
            longitude=payload.longitude,
        ),
        db=db,
        authoritative_run_id=stop.run_id,
    )
    db.commit()
    db.refresh(updated_stop)
    return updated_stop


def _delete_route_stop_internal(
    *,
    route_id: int,
    stop_id: int,
    db: Session,
    operator: Operator,
):
    from backend.routers import stop as stop_router

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    stop = get_route_stop_or_404(route_id=route.id, stop_id=stop_id, db=db)

    run_id = stop.run_id
    db.delete(stop)
    db.flush()
    stop_router.normalize_run_sequences(db, run_id)
    db.commit()
    return None


def _create_route_student_internal(
    *,
    route_id: int,
    payload: schemas.StudentCompatibilityCreate,
    db: Session,
    operator: Operator,
):
    from backend.routers import student as student_router

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
        options=[selectinload(Route.schools)],
    )
    school = db.get(School, payload.school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    _, stop = student_router._validate_compatibility_student_create_target(
        school=school,
        student_district_id=route.district_id,
        route_id=route.id,
        stop_id=payload.stop_id,
        operator_id=operator.id,
        db=db,
    )

    new_student = student_model.Student(
        name=payload.name,
        grade=payload.grade,
        school_id=school.id,
        route_id=route.id,
        stop_id=stop.id if stop is not None else None,
        district_id=route.district_id,
    )
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


def _delete_route_student_internal(
    *,
    route_id: int,
    student_id: int,
    db: Session,
    operator: Operator,
):
    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    student = get_route_student_or_404(route_id=route.id, student_id=student_id, db=db)

    student.route_id = None
    if student.stop_id is not None:
        stop = db.get(stop_model.Stop, student.stop_id)
        stop_route_id = stop.route_id if stop and stop.route_id is not None else stop.run.route_id if stop and stop.run else None
        if stop_route_id == route.id:
            student.stop_id = None

    db.commit()
    return None


@router.post(
    "/{route_id}/runs",
    response_model=schemas.RunOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Create run inside route",
    description=(
        "Primary workflow-first run creation path. "
        "Create a planned run inside the selected route context without sending route_id in the body. "
        "When exactly one active route-driver assignment exists, the planned run inherits that active driver. "
        "Primary/default assignment does not control operational run resolution by itself."
    ),
    response_description="Created run",
)
def create_route_run(
    route_id: int,
    payload: RouteRunCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _create_route_run_internal(route_id=route_id, payload=payload, db=db, operator=operator)


@router.put(
    "/{route_id}/runs/{run_id}",
    response_model=schemas.RunOut,
    include_in_schema=False,
    summary="Update run inside route",
    description="Update one planned run under the selected route context. The path route_id is authoritative.",
    response_description="Updated run",
)
def update_route_run(
    route_id: int,
    run_id: int,
    payload: RunUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _update_route_run_internal(route_id=route_id, run_id=run_id, payload=payload, db=db, operator=operator)


@router.delete(
    "/{route_id}/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
    summary="Delete run inside route",
    description="Delete one planned run under the selected route context. The path route_id is authoritative.",
    response_description="Run deleted",
)
def delete_route_run(
    route_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _delete_route_run_internal(route_id=route_id, run_id=run_id, db=db, operator=operator)


@router.post(
    "/{route_id}/runs/{run_id}/stops",
    response_model=StopOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Create stop inside route run",
    description="Primary path-driven stop creation workflow. Create a planned stop under the selected route and run context without sending internal run_id in the body.",
    response_description="Created stop",
)
def create_route_run_stop(
    route_id: int,
    run_id: int,
    payload: RunStopCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _create_route_run_stop_internal(route_id=route_id, run_id=run_id, payload=payload, db=db, operator=operator)


@router.put(
    "/{route_id}/stops/{stop_id}",
    response_model=StopOut,
    include_in_schema=False,
    summary="Update stop inside route",
    description="Update one planned stop under the selected route context. The stop may not be moved across runs through this route-level endpoint.",
    response_description="Updated stop",
)
def update_route_stop(
    route_id: int,
    stop_id: int,
    payload: StopUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _update_route_stop_internal(route_id=route_id, stop_id=stop_id, payload=payload, db=db, operator=operator)


@router.delete(
    "/{route_id}/stops/{stop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
    summary="Delete stop inside route",
    description="Delete one planned stop under the selected route context and normalize the remaining run sequence order.",
    response_description="Stop deleted",
)
def delete_route_stop(
    route_id: int,
    stop_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _delete_route_stop_internal(route_id=route_id, stop_id=stop_id, db=db, operator=operator)


@router.post(
    "/{route_id}/students",
    response_model=schemas.StudentOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Create student inside route",
    description="Route-scoped planning helper. This is not the preferred initial student setup workflow. Preferred workflow is POST /runs/{run_id}/stops/{stop_id}/students so run and stop context stay authoritative.",
    response_description="Created student",
)
def create_route_student(
    route_id: int,
    payload: schemas.StudentCompatibilityCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _create_route_student_internal(route_id=route_id, payload=payload, db=db, operator=operator)


@router.delete(
    "/{route_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
    summary="Remove student from route",
    description="Remove one student from the selected route planning context without deleting the student record entirely.",
    response_description="Student removed from route",
)
def delete_route_student(
    route_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _raise_district_planning_path_retired()
    return _delete_route_student_internal(route_id=route_id, student_id=student_id, db=db, operator=operator)
