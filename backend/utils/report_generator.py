# -----------------------------------------------------------
# Reports Generator Compatibility
# - Re-export reports-layer helpers for legacy imports
# -----------------------------------------------------------
from .reports_generator import (  # Re-export reports-layer helpers during the rename phase
    driver_summary,
    route_summary,
    dispatch_summary,
    generate_reports,
)


def generate_attendance(
    db,
    attendance_type: str,
    ref_id: int = None,
    start=None,
    end=None,
    operator_id=None,
):
    """Deprecated compatibility wrapper. Use generate_reports instead."""
    reports_type = "dispatch" if attendance_type == "payroll" else attendance_type
    return generate_reports(
        db=db,
        reports_type=reports_type,
        ref_id=ref_id,
        start=start,
        end=end,
        operator_id=operator_id,
    )


__all__ = [
    "driver_summary",
    "route_summary",
    "dispatch_summary",
    "generate_reports",
    "generate_attendance",
]  # Preserve legacy helper exports
