# -----------------------------------------------------------
# Deprecated Attendance Generator Compatibility
# - Keep legacy imports working while reports_generator is canonical
# -----------------------------------------------------------
from .reports_generator import (
    driver_summary,
    route_summary,
    dispatch_summary,
    generate_reports,
    run_reports_summary,
    school_reports_summary,
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


run_attendance_summary = run_reports_summary  # Deprecated: use run_reports_summary.
school_summary = school_reports_summary  # Deprecated: use school_reports_summary.


__all__ = [
    "driver_summary",
    "route_summary",
    "dispatch_summary",
    "generate_reports",
    "generate_attendance",
    "run_reports_summary",
    "run_attendance_summary",
    "school_reports_summary",
    "school_summary",
]
