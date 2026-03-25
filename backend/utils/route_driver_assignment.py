# -----------------------------------------------------------
# - Route driver assignment helpers
# - Shared one-active-driver-per-route rules
# -----------------------------------------------------------
from backend.models.associations import RouteDriverAssignment
from datetime import datetime, timezone

# -----------------------------------------------------------
# - Active assignment filter
# - Keep only active route-driver assignments
# -----------------------------------------------------------
def get_active_route_driver_assignments(route) -> list[RouteDriverAssignment]:
    return [
        assignment
        for assignment in getattr(route, "driver_assignments", [])
        if assignment.active is True
    ]


# -----------------------------------------------------------
# - Route driver resolver
# - Enforce exactly one active driver assignment
# -----------------------------------------------------------
def resolve_route_driver_assignment(route) -> RouteDriverAssignment:
    active_assignments = get_active_route_driver_assignments(route)  # Active route-driver assignments

    if not active_assignments:
        raise ValueError("Route has no active driver assignment")

    if len(active_assignments) > 1:
        raise ValueError("Route has multiple active driver assignments")

    return active_assignments[0]


# -----------------------------------------------------------
# - Route driver display helper
# - Return the resolved active driver name
# -----------------------------------------------------------
def get_route_driver_name(route) -> str | None:
    try:
        assignment = resolve_route_driver_assignment(route)  # Resolve active route-driver assignment
    except ValueError:
        return None

    return assignment.driver.name if assignment.driver else None
