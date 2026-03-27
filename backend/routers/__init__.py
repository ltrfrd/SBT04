# -----------------------------------------------------------
# - Router package exports
# - Centralize router imports and outward exports
# -----------------------------------------------------------

from .driver import router as driver_router                      # Driver management endpoints
from .school import router as school_router                      # School management endpoints
from .student import router as student_router                    # Student management endpoints
from .route import router as route_router                        # Route management endpoints
from .stop import router as stop_router                          # Stop management endpoints
from .run import router as run_router                            # Run operation endpoints
from .dispatch import router as dispatch_router                  # Dispatch/business endpoints
from .attendance import router as attendance_router              # Attendance reporting endpoints
from .attendance import student_bus_absence_router               # Attendance-owned planned absence compatibility router
from .student_run_assignment import router as student_run_assignment_router  # Run assignment endpoints


__all__ = [
    "driver_router",                     # Export driver router
    "school_router",                     # Export school router
    "student_router",                    # Export student router
    "route_router",                      # Export route router
    "stop_router",                       # Export stop router
    "run_router",                        # Export run router
    "dispatch_router",                   # Export dispatch router
    "attendance_router",                 # Export attendance router
    "student_bus_absence_router",        # Export attendance-owned planned absence router
    "student_run_assignment_router",     # Export run assignment router
]
