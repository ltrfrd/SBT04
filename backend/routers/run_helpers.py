# ===========================================================
# backend/routers/run_helpers.py - FleetOS Run Router Helpers
# -----------------------------------------------------------
# Compatibility re-export shim for split setup/execution helpers.
# ===========================================================

from backend.routers.run_execution_helpers import (
    EXECUTION_RUN_BLOCKED_DETAIL,
    _assert_dropoff_transition_allowed,
    _assert_pickup_transition_allowed,
    _build_run_occupancy_counts,
    _build_running_board_stops,
    _get_execution_scoped_run_or_404,
    _get_ordered_run_stops,
    _get_run_assignments,
    _get_runtime_assignment_or_404,
    _get_runtime_run_or_404,
    _group_running_board_students,
    _require_active_runtime_run,
    _require_current_runtime_stop,
    _require_posttrip_phase1_and_phase2_completed,
    _resolve_run_driver,
    _resolve_runtime_stop_target_or_404,
    _serialize_run,
    _serialize_run_detail,
    _serialize_run_list_item,
    _set_run_current_stop,
)
from backend.routers.run_setup_helpers import (
    _assert_unique_route_run_type,
    _create_planned_run,
    _create_stop_context_student,
    _get_operator_scoped_run_or_404,
    _get_run_stop_or_404,
    _get_run_stop_student_context_or_404,
)
