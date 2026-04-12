# -----------------------------------------------------------
# Deprecated Attendance Generator Compatibility
# - Keep legacy imports working while reports_generator is canonical
# -----------------------------------------------------------
from .reports_generator import (
    driver_summary,
    route_summary,
    dispatch_summary,
    generate_reports,
    generate_attendance,
    run_reports_summary,
    run_attendance_summary,
    school_reports_summary,
)

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
