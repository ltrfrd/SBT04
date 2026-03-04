# ===========================================================
# backend/routers/__init__.py — SBT Routers Index
# -----------------------------------------------------------
# Central import hub for all API routers.
# Each router handles a specific domain (driver, school, etc.).
# ===========================================================

# -----------------------------------------------------------
# Import routers explicitly
# -----------------------------------------------------------
from .driver import router as driver_router  # Driver management
from .school import router as school_router  # School CRUD operations
from .student import router as student_router  # Student management
from .route import router as route_router  # Route creation & linking
from .stop import router as stop_router  # Stop management
from .run import router as run_router  # AM/PM/Extra run endpoints
from .payroll import router as payroll_router  # Payroll summaries (view only)
from .report import router as report_router

# -----------------------------------------------------------
# Export all routers for app inclusion
# -----------------------------------------------------------
__all__ = [
    "driver_router",
    "school_router",
    "student_router",
    "route_router",
    "stop_router",
    "run_router",
    "payroll_router",
    "report_router",
]
