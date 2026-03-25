# -----------------------------------------------------------
# Route driver assignment helpers
# - Shared route-level driver resolution rules
# -----------------------------------------------------------
from datetime import date, datetime, timezone

from backend.models.associations import RouteDriverAssignment


# -----------------------------------------------------------
# Active assignment filter
# - Keep only assignments effective for the requested date
# -----------------------------------------------------------
def get_active_route_driver_assignments(route, target_date: date | None = None) -> list[RouteDriverAssignment]:
    target_date = target_date or datetime.now(timezone.utc).date()  # Resolve effective date once

    return [
        assignment
        for assignment in getattr(route, "driver_assignments", [])
        if assignment.active is True
        and (assignment.start_date is None or assignment.start_date <= target_date)
        and (assignment.end_date is None or assignment.end_date >= target_date)
    ]


# -----------------------------------------------------------
# Route driver resolver
# - Apply the deterministic active assignment rule
# -----------------------------------------------------------
def resolve_route_driver_assignment(route, target_date: date | None = None) -> RouteDriverAssignment:
    active_assignments = get_active_route_driver_assignments(route, target_date)  # Effective active assignments

    if not active_assignments:
        raise ValueError("Route has no active driver assignment")

    primary_assignments = [
        assignment
        for assignment in active_assignments
        if assignment.is_primary is True
    ]  # Effective primary assignments

    if len(primary_assignments) == 1:
        return primary_assignments[0]

    if len(primary_assignments) > 1:
        raise ValueError("Route has multiple active primary driver assignments")

    if len(active_assignments) == 1:
        return active_assignments[0]

    raise ValueError("Route has multiple active driver assignments without a single primary")


# -----------------------------------------------------------
# Route driver display helper
# - Return the currently resolved driver name when available
# -----------------------------------------------------------
def get_route_driver_name(route, target_date: date | None = None) -> str | None:
    try:
        assignment = resolve_route_driver_assignment(route, target_date)  # Resolve display assignment
    except ValueError:
        return None

    return assignment.driver.name if assignment.driver else None
