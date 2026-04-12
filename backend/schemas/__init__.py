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
# Bus schemas
# -------------------------------------------------------------------------
from .bus import BusCreate, BusDetailOut, BusOut, BusUpdate  # Bus creation and response schemas


# -------------------------------------------------------------------------
# Driver schemas
# -------------------------------------------------------------------------
from .driver import DriverCreate, DriverOut  # Driver creation and response schemas


# -------------------------------------------------------------------------
# District schemas
# -------------------------------------------------------------------------
from .district import DistrictCreate, DistrictOut  # District creation and response schemas


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
    RouteRestorePrimaryBus,
)  # Route creation and response schemas


# -------------------------------------------------------------------------
# Stop schemas
# -------------------------------------------------------------------------
from .stop import RunStopCreate, RunStopUpdate, StopCreate, StopOut  # Stop creation and response schemas


# -------------------------------------------------------------------------
# Student schemas
# -------------------------------------------------------------------------
from .student import (
    StudentAssignmentUpdate,
    StudentCompatibilityCreate,
    StudentCreate,
    StudentOut,
    StopStudentBulkCreate,
    StopStudentBulkError,
    StopStudentBulkResult,
    StopStudentCreate,
    StopStudentUpdate,
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
from .pretrip import (
    PreTripCreate,
    PreTripCorrect,
    PreTripDefectBase,
    PreTripDefectCreate,
    PreTripDefectOut,
    PreTripOut,
)
from .posttrip import (
    PostTripOut,
    PostTripPhase1Submit,
    PostTripPhase2Submit,
)


# -----------------------------------------------------------
# - Dispatch schema exports
# -----------------------------------------------------------
from .dispatch import (
    DispatchCreate,
    DispatchOut,
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
    "BusCreate",
    "BusDetailOut",
    "BusUpdate",
    "BusOut",

    "DriverCreate",
    "DriverOut",

    "DistrictCreate",
    "DistrictOut",

    "SchoolCreate",
    "SchoolOut",

    "StudentCreate",
    "StudentCompatibilityCreate",
    "StudentAssignmentUpdate",
    "StudentOut",
    "StopStudentCreate",
    "StopStudentUpdate",
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
    "RouteRestorePrimaryBus",

    "StopCreate",
    "RunStopCreate",
    "RunStopUpdate",
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
    "PreTripDefectBase",
    "PreTripDefectCreate",
    "PreTripCreate",
    "PreTripCorrect",
    "PreTripDefectOut",
    "PreTripOut",
    "PostTripPhase1Submit",
    "PostTripPhase2Submit",
    "PostTripOut",

    "DispatchCreate",
    "DispatchOut",

    "StudentRunAssignmentCreate",
    "StudentRunAssignmentOut",
    "StudentBusAbsenceCreate",
    "StudentBusAbsenceOut",
    
    "RunOut",
    "RunSummaryOut",
]
