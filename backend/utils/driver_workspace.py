# ===========================================================
# backend/utils/driver_workspace.py - Driver Workspace Helpers
# -----------------------------------------------------------
# Shared helpers for building route-first driver workspace data
# ===========================================================

from datetime import datetime

from backend.models import route as route_model
from backend.models import run as run_model


# -----------------------------------------------------------
# - Driver workspace helpers
# - Build route-first driver template state
# -----------------------------------------------------------
def _get_run_workspace_status(run: run_model.Run) -> str:
    if run.start_time is None:
        return "ready"                                       # Driver-facing label for a run that has not started yet
    if run.end_time is None:
        return "active"                                      # Started but not ended yet
    return "ended"                                           # Historical completed run


# -----------------------------------------------------------
# - Build route workspace
# - Serialize route, run, stop, and rider details for the driver page
# -----------------------------------------------------------
def _build_route_workspace(route: route_model.Route, selected_run_id: int | None = None) -> dict:
    active_assignment = next(                                # Route-level assigned driver for header display
        (assignment for assignment in route.driver_assignments if assignment.active),
        None,
    )

    # -----------------------------------------------------------
    # - Order route runs
    # - Keep run list stable for route-first browsing
    # -----------------------------------------------------------
    ordered_runs = sorted(                                   # Show the newest run context first
        route.runs,
        key=lambda run: (run.start_time or datetime.min, run.id),
        reverse=True,
    )

    run_rows = []                                            # Final nested run workspace rows

    for run in ordered_runs:
        # -----------------------------------------------------------
        # - Order run stops
        # - Keep stop sequence stable for running-board review
        # -----------------------------------------------------------
        ordered_stops = sorted(                              # Stable stop order inside each run
            run.stops,
            key=lambda stop: (
                stop.sequence if stop.sequence is not None else 999999,
                stop.id,
            ),
        )

        assignments_by_stop: dict[int, list[dict]] = {}     # Stop -> student rows for the template

        # -----------------------------------------------------------
        # - Group riders by stop
        # - Build stop-level running-board rows from runtime assignments
        # -----------------------------------------------------------
        for assignment in sorted(
            run.student_assignments,
            key=lambda item: (
                item.stop.sequence if item.stop and item.stop.sequence is not None else 999999,
                item.id,
            ),
        ):
            if assignment.stop_id is None or not assignment.student:
                continue

            assignments_by_stop.setdefault(assignment.stop_id, []).append(
                {
                    "student_id": assignment.student.id,     # Stable student identifier for row keys
                    "student_name": assignment.student.name, # Driver-facing student display
                    "grade": assignment.student.grade,       # Compact rider detail
                    "school_name": assignment.student.school.name if assignment.student.school else None,  # School context
                    "notification_distance_meters": assignment.student.notification_distance_meters,  # Rider alert distance
                }
            )

        stop_rows = []                                       # Ordered stop rows for this run

        # -----------------------------------------------------------
        # - Serialize stop rows
        # - Expose running-board stop details already available in the repo
        # -----------------------------------------------------------
        for stop in ordered_stops:
            stop_students = assignments_by_stop.get(stop.id, [])
            stop_rows.append(
                {
                    "id": stop.id,
                    "sequence": stop.sequence,
                    "type": stop.type.value if hasattr(stop.type, "value") else str(stop.type),  # Pickup or dropoff label
                    "name": stop.name,
                    "address": stop.address,
                    "planned_time": stop.planned_time,       # Planned stop time when available
                    "student_count": len(stop_students),
                    "students": stop_students,
                }
            )

        # -----------------------------------------------------------
        # - Serialize run row
        # - Keep review state and live-action flags separate
        # -----------------------------------------------------------
        status = _get_run_workspace_status(run)              # Ready / active / ended summary label
        run_rows.append(
            {
                "id": run.id,
                "run_type": run.run_type,
                "status": status,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "stop_count": len(stop_rows),
                "student_count": len(run.student_assignments),
                "current_stop_id": run.current_stop_id,
                "current_stop_sequence": run.current_stop_sequence,
                "can_start": run.start_time is None,         # Start only from ready runs
                "can_update": run.start_time is None,        # Non-started runs remain editable in backend flows
                "can_delete": run.start_time is None,        # Non-started runs remain deletable in backend flows
                "can_end": status == "active",               # Preserve active end-run behavior
                "stops": stop_rows,
            }
        )

    # -----------------------------------------------------------
    # - Resolve selected and active runs
    # - Keep review browsing independent from active-run controls
    # -----------------------------------------------------------
    active_run = next((run for run in run_rows if run["status"] == "active"), None)  # At most one active run per driver
    selected_run = next((run for run in run_rows if run["id"] == selected_run_id), None) if selected_run_id is not None else None
    if selected_run is None and run_rows:
        selected_run = run_rows[0]                            # Default to the first route run so stop details remain visible

    return {
        "id": route.id,
        "route_number": route.route_number,
        "unit_number": route.unit_number,
        "operator": route.operator,
        "capacity": route.capacity,
        "schools": [
            {
                "id": school.id,
                "name": school.name,
            }
            for school in route.schools
        ],
        "assigned_driver_id": active_assignment.driver_id if active_assignment else None,
        "assigned_driver_name": active_assignment.driver.name if active_assignment and active_assignment.driver else None,
        "runs": run_rows,
        "active_run": active_run,
        "selected_run": selected_run,
    }
