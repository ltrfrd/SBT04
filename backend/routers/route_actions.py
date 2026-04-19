from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from database import get_db

from backend.models.associations import RouteDriverAssignment
from backend.models.bus import Bus
from backend.models.operator import Operator, OperatorRouteAccess
from backend.models.route import Route
from backend.models.yard import Yard
from backend.routers.route_helpers import _assign_driver_to_route
from backend.routers.route_helpers import _assert_route_driver_assignment_integrity
from backend.routers.route_helpers import _get_primary_route_assignment
from backend.routers.route_helpers import _get_route_assignment_for_driver
from backend.routers.route_helpers import _serialize_route
from backend.schemas.route import RouteDriverAssignmentOut, RouteOut, RouteRestorePrimaryBus
from backend.utils.operator_scope import create_operator_route_access
from backend.utils.operator_scope import ensure_route_owner
from backend.utils.operator_scope import get_bus_operator_id
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_route_access_level
from backend.utils.operator_scope import get_operator_scoped_route_or_404
router = APIRouter(tags=["Routes"])


@router.post(
    "/{route_id}/assign_bus/{bus_id}",
    response_model=RouteOut,
    summary="Assign bus to route",
    description="Assign one current bus to the route without changing route setup or runtime workflow behavior.",
    response_description="Updated route with assigned bus",
)
def assign_bus_to_route(
    route_id: int,
    bus_id: int,
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

    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus_operator_id = get_bus_operator_id(bus)
    if bus_operator_id != operator.id:
        raise HTTPException(status_code=400, detail="Bus is not allowed for this route")

    route.active_bus_id = bus.id
    route.bus_id = bus.id
    if route.primary_bus_id is None:
        route.primary_bus_id = bus.id
    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.post(
    "/{route_id}/set_primary_bus/{bus_id}",
    response_model=RouteOut,
    summary="Set primary bus for route",
    description="Set the default/base bus for a route. If no active bus exists yet, active bus and compatibility bus_id are aligned to the same bus.",
    response_description="Updated route with primary bus",
)
def set_primary_bus_for_route(
    route_id: int,
    bus_id: int,
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

    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus_operator_id = get_bus_operator_id(bus)
    if bus_operator_id != operator.id:
        raise HTTPException(status_code=400, detail="Bus is not allowed for this route")

    route.primary_bus_id = bus.id
    if route.active_bus_id is None:
        route.active_bus_id = bus.id
        route.bus_id = bus.id

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.post(
    "/{route_id}/set_active_bus/{bus_id}",
    response_model=RouteOut,
    summary="Set active bus for route",
    description="Set the current operational bus for a route and keep the legacy compatibility bus_id aligned.",
    response_description="Updated route with active bus",
)
def set_active_bus_for_route(
    route_id: int,
    bus_id: int,
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

    bus = db.get(Bus, bus_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus_operator_id = get_bus_operator_id(bus)
    if bus_operator_id != operator.id:
        raise HTTPException(status_code=400, detail="Bus is not allowed for this route")

    route.active_bus_id = bus.id
    route.bus_id = bus.id

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.post(
    "/{route_id}/restore_primary_bus",
    response_model=RouteOut,
    summary="Restore primary bus for route",
    description="Restore the active operational bus back to the route's primary/default bus and optionally record a clearance note.",
    response_description="Updated route with restored primary bus",
)
def restore_primary_bus_for_route(
    route_id: int,
    payload: RouteRestorePrimaryBus | None = None,
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

    if route.primary_bus_id is None:
        raise HTTPException(status_code=400, detail="Route has no primary bus to restore")

    route.active_bus_id = route.primary_bus_id
    route.bus_id = route.primary_bus_id
    route.clearance_note = payload.clearance_note if payload else None

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.delete(
    "/{route_id}/unassign_bus",
    response_model=RouteOut,
    summary="Unassign bus from route",
    description="Clear the current bus assignment from the route without changing route setup or runtime workflow behavior.",
    response_description="Updated route without assigned bus",
)
def unassign_bus_from_route(
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

    route.active_bus_id = None
    route.bus_id = None
    db.commit()
    db.refresh(route)
    return _serialize_route(route)


@router.post(
    "/{route_id}/assign_driver/{driver_id}",
    response_model=RouteDriverAssignmentOut,
    summary="Assign driver to route",
    description=(
        "Assign a driver to a route using separate primary/default and active/current semantics. "
        "The first route-driver assignment becomes both primary and active. "
        "Later assignments may activate a temporary replacement driver without removing the existing primary assignment. "
        "Operational run logic continues to follow the single active/current assignment only. No request body is required."
    ),
    response_description="The activated route-driver assignment",
)
def assign_driver_to_route(
    route_id: int,
    driver_id: int,
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
    ensure_route_owner(route, operator.id)

    assignment = _assign_driver_to_route(route, driver_id, db, operator.id)

    db.commit()
    db.refresh(assignment)

    return RouteDriverAssignmentOut(
        id=assignment.id,
        route_id=assignment.route_id,
        driver_id=assignment.driver_id,
        driver_name=assignment.driver.name if assignment.driver else None,
        active=assignment.active,
        is_primary=assignment.is_primary,
    )


@router.delete(
    "/{route_id}/unassign_driver/{driver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unassign driver from route",
    description=(
        "Deactivate the selected route-driver assignment safely. "
        "If the active assignment being removed is a temporary replacement and the route still has an inactive primary/default assignment, "
        "the primary assignment is reactivated automatically. "
        "Operational run logic continues to follow the single active/current assignment only."
    ),
    response_description="Route-driver assignment deactivated",
)
def unassign_driver_from_route(
    route_id: int,
    driver_id: int,
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
    ensure_route_owner(route, operator.id)

    _assert_route_driver_assignment_integrity(route)

    assignment = _get_route_assignment_for_driver(route, driver_id)
    if assignment is None or assignment.active is not True:
        raise HTTPException(status_code=404, detail="Active route-driver assignment not found")

    assignment.active = False

    primary_assignment = _get_primary_route_assignment(route)
    if (
        primary_assignment is not None
        and primary_assignment.id != assignment.id
        and primary_assignment.active is not True
    ):
        primary_assignment.active = True

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{route_id}/assign-yard/{yard_id}",
    summary="Assign route to yard",
    description="Link a route to one yard owned by the acting operator without changing route grant logic.",
)
def assign_route_to_yard(
    route_id: int,
    yard_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    raise HTTPException(
        status_code=403,
        detail="Yard assignment must be managed through district route planning endpoints",
    )


@router.delete(
    "/{route_id}/assign-yard/{yard_id}",
    summary="Unassign route from yard",
    description="Remove one yard link from a route without changing route grant logic.",
)
def unassign_route_from_yard(
    route_id: int,
    yard_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    raise HTTPException(
        status_code=403,
        detail="Yard assignment must be managed through district route planning endpoints",
    )


@router.post(
    "/{route_id}/share/{target_operator_id}",
    summary="Grant shared route access",
    description="Owner-only endpoint that grants explicit read or operate access for a route to another operator.",
)
def share_route_with_operator(
    route_id: int,
    target_operator_id: int,
    payload: dict = Body(...),
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

    if get_route_access_level(route, target_operator_id) == "owner":
        raise HTTPException(status_code=400, detail="Owner operator already has access")

    target_operator = db.get(Operator, target_operator_id)
    if not target_operator:
        raise HTTPException(status_code=404, detail="Operator not found")

    access_level = str(payload.get("access_level", "read")).strip().lower()
    if access_level not in {"read", "operate"}:
        raise HTTPException(status_code=400, detail="Invalid access level")

    grant = (
        db.query(OperatorRouteAccess)
        .filter(OperatorRouteAccess.route_id == route_id)
        .filter(OperatorRouteAccess.operator_id == target_operator_id)
        .first()
    )
    if grant is None:
        grant = create_operator_route_access(
            route_id=route_id,
            operator_id=target_operator_id,
            access_level=access_level,
        )
        db.add(grant)
    else:
        grant.access_level = access_level

    db.commit()
    db.refresh(grant)
    return {
        "route_id": route_id,
        "operator_id": target_operator_id,
        "access_level": grant.access_level,
    }


@router.delete(
    "/{route_id}/share/{target_operator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove shared route access",
    description="Owner-only endpoint that removes explicit shared access for a route.",
)
def unshare_route_with_operator(
    route_id: int,
    target_operator_id: int,
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

    grant = (
        db.query(OperatorRouteAccess)
        .filter(OperatorRouteAccess.route_id == route_id)
        .filter(OperatorRouteAccess.operator_id == target_operator_id)
        .first()
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Shared access not found")
    if grant.access_level == "owner":
        raise HTTPException(
            status_code=400,
            detail="Cannot remove owner access from a route",
        )

    db.delete(grant)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
