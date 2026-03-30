# =============================================================================
# backend/schemas/__init__.py — Schema Export Hub
# -----------------------------------------------------------------------------
# This file centralizes schema imports so the rest of the application can use:
#
#     from backend import schemas
#
# instead of importing each schema file individually.
#
# Only schemas listed in __all__ will be exposed when importing the package.
# =============================================================================


# -------------------------------------------------------------------------
# Driver schemas
# -------------------------------------------------------------------------
from .driver import DriverCreate, DriverOut  # Driver creation and response schemas


# -------------------------------------------------------------------------
# School schemas
# -------------------------------------------------------------------------
from .school import SchoolCreate, SchoolOut  # School creation and response schemas


# -------------------------------------------------------------------------
# Route schemas
# -------------------------------------------------------------------------
from .route import (
    RouteCreate,
    RouteDetailOut,
    RouteDetailRunOut,
    RouteDetailStopOut,
    RouteDetailStudentOut,
    RouteSchoolOut,
    RouteOut,
    RouteDriverAssignmentCreate,
    RouteDriverAssignmentOut,
)  # Route creation and response schemas


# -------------------------------------------------------------------------
# Stop schemas
# -------------------------------------------------------------------------
from .stop import RunStopCreate, StopCreate, StopOut  # Stop creation and response schemas


# -------------------------------------------------------------------------
# Student schemas
# -------------------------------------------------------------------------
from .student import (
    StudentCreate,
    StudentOut,
    StopStudentBulkCreate,
    StopStudentBulkError,
    StopStudentBulkResult,
    StopStudentCreate,
)  # Student creation and stop-context workflow schemas


# -------------------------------------------------------------------------
# Run schemas
# -------------------------------------------------------------------------
from .run import (
    RunListOut,
    RunDetailDriverOut,
    RunDetailOut,
    RunDetailRouteOut,
    RunDetailStopOut,
    RunDetailStudentOut,
    RouteRunCreate,
    RunOut,          # Standard run response schema
    RunSummaryOut,   # Operational run summary schema
)


# -----------------------------------------------------------
# - Dispatch schema exports
# - Outward-facing Dispatch names with Payroll aliases
# -----------------------------------------------------------
from .dispatch import (
    DispatchCreate,
    DispatchOut,
    PayrollCreate,
    PayrollOut,
)  # Dispatch creation and response schemas


# -------------------------------------------------------------------------
# Student-Run assignment schemas
# -------------------------------------------------------------------------
from .student_run_assignment import (
    StudentRunAssignmentCreate,
    StudentRunAssignmentOut,
)
from .student_bus_absence import (
    StudentBusAbsenceCreate,
    StudentBusAbsenceOut,
)

# =============================================================================
# Public schema exports
# Only schemas listed here are accessible through "backend.schemas"
# =============================================================================
__all__ = [
    "DriverCreate",
    "DriverOut",

    "SchoolCreate",
    "SchoolOut",

    "StudentCreate",
    "StudentOut",
    "StopStudentCreate",
    "StopStudentBulkCreate",
    "StopStudentBulkError",
    "StopStudentBulkResult",

    "RouteCreate",
    "RouteOut",
    "RouteDetailOut",
    "RouteDetailRunOut",
    "RouteDetailStopOut",
    "RouteDetailStudentOut",
    "RouteSchoolOut",
    "RouteDriverAssignmentCreate",
    "RouteDriverAssignmentOut",

    "StopCreate",
    "RunStopCreate",
    "StopOut",

    "RunOut",
    "RunListOut",
    "RunDetailOut",
    "RunDetailRouteOut",
    "RunDetailDriverOut",
    "RunDetailStopOut",
    "RunDetailStudentOut",
    "RouteRunCreate",
    "RunSummaryOut",

    "DispatchCreate",
    "DispatchOut",
    "PayrollCreate",
    "PayrollOut",

    "StudentRunAssignmentCreate",
    "StudentRunAssignmentOut",
    "StudentBusAbsenceCreate",
    "StudentBusAbsenceOut",
    
    "RunOut",
    "RunSummaryOut",
]
