# -----------------------------------------------------------
# Report Generator Compatibility
# - Re-export attendance-layer helpers for the app layer
# -----------------------------------------------------------
from .attendance_generator import (  # Re-export attendance-layer helpers during the rename phase
    driver_summary,
    route_summary,
    dispatch_summary,
    generate_attendance,
    generate_report,
)


__all__ = [
    "driver_summary",
    "route_summary",
    "dispatch_summary",
    "generate_attendance",
    "generate_report",
]  # Preserve legacy helper exports
