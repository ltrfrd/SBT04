# -----------------------------------------------------------
# Deprecated Attendance Router Compatibility
# - Keep legacy module imports working while reports is canonical
# -----------------------------------------------------------
from .reports import attendance_router as router
from .reports import student_bus_absence_router


__all__ = ["router", "student_bus_absence_router"]
