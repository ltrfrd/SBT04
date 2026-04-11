# -----------------------------------------------------------
# Reports Generator Compatibility
# - Re-export reports-layer helpers for legacy imports
# -----------------------------------------------------------
from .reports_generator import (  # Re-export reports-layer helpers during the rename phase
    driver_summary,
    route_summary,
    dispatch_summary,
    generate_reports,
    generate_attendance,
)


__all__ = [
    "driver_summary",
    "route_summary",
    "dispatch_summary",
    "generate_reports",
    "generate_attendance",
]  # Preserve legacy helper exports
