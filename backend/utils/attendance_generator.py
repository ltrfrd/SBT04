# -----------------------------------------------------------
# Deprecated Attendance Generator Compatibility
# - Keep legacy imports working while reports_generator is canonical
# -----------------------------------------------------------
from .reports_generator import (
    driver_summary,
    route_summary_execution,
    dispatch_summary,
    generate_reports,
    run_reports_summary,
    school_reports_summary_execution,
)


__all__ = [
    "driver_summary",
    "route_summary_execution",
    "dispatch_summary",
    "generate_reports",
    "run_reports_summary",
    "school_reports_summary_execution",
]
