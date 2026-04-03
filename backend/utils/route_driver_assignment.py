# -----------------------------------------------------------
# - Route driver assignment helpers
# - Shared active/primary route-driver assignment rules
# -----------------------------------------------------------
from backend.models.associations import RouteDriverAssignment

# -----------------------------------------------------------
# - Active assignment filter
# - Keep only operationally active route-driver assignments
# -----------------------------------------------------------
def get_active_route_driver_assignments(route) -> list[RouteDriverAssignment]:
    return [
        assignment
        for assignment in getattr(route, "driver_assignments", [])
        if assignment.active is True
    ]


# -----------------------------------------------------------
# - Primary assignment filter
# - Keep only default/base route-owner assignments
# -----------------------------------------------------------
def get_primary_route_driver_assignments(route) -> list[RouteDriverAssignment]:
    return [
        assignment
        for assignment in getattr(route, "driver_assignments", [])
        if assignment.is_primary is True
    ]


# -----------------------------------------------------------
# - Route driver resolver
# - Enforce exactly one active driver assignment for operations
# -----------------------------------------------------------
def resolve_route_driver_assignment(route) -> RouteDriverAssignment:
    active_assignments = get_active_route_driver_assignments(route)  # Active route-driver assignments

    if not active_assignments:
        raise ValueError("Route has no active driver assignment")

    if len(active_assignments) > 1:
        raise ValueError("Route has multiple active driver assignments")

    return active_assignments[0]


# -----------------------------------------------------------
# - Primary route driver resolver
# - Enforce at most one default/base driver assignment
# -----------------------------------------------------------
def resolve_primary_route_driver_assignment(route) -> RouteDriverAssignment:
    primary_assignments = get_primary_route_driver_assignments(route)  # Default/base route-owner assignments

    if not primary_assignments:
        raise ValueError("Route has no primary driver assignment")

    if len(primary_assignments) > 1:
        raise ValueError("Route has multiple primary driver assignments")

    return primary_assignments[0]


# -----------------------------------------------------------
# - Route driver display helper
# - Return the resolved active driver name for operations
# -----------------------------------------------------------
def get_route_driver_name(route) -> str | None:
    try:
        assignment = resolve_route_driver_assignment(route)  # Resolve active route-driver assignment
    except ValueError:
        return None

    return assignment.driver.name if assignment.driver else None
