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
from .route import RouteCreate, RouteOut  # Route creation and response schemas


# -------------------------------------------------------------------------
# Stop schemas
# -------------------------------------------------------------------------
from .stop import StopCreate, StopOut  # Stop creation and response schemas


# -------------------------------------------------------------------------
# Student schemas
# -------------------------------------------------------------------------
from .student import StudentCreate, StudentOut  # Student creation and response schemas


# -------------------------------------------------------------------------
# Run schemas
# -------------------------------------------------------------------------
from .run import (
    RunOut,          # Standard run response schema
    RunSummaryOut,   # Operational run summary schema
)


# -------------------------------------------------------------------------
# Payroll schemas
# -------------------------------------------------------------------------
from .payroll import PayrollCreate, PayrollOut  # Payroll creation and response schemas


# -------------------------------------------------------------------------
# Student-Run assignment schemas
# -------------------------------------------------------------------------
from .student_run_assignment import (
    StudentRunAssignmentCreate,
    StudentRunAssignmentOut,
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

    "RouteCreate",
    "RouteOut",

    "StopCreate",
    "StopOut",

    "RunOut",
    "RunSummaryOut",

    "PayrollCreate",
    "PayrollOut",

    "StudentRunAssignmentCreate",
    "StudentRunAssignmentOut",
    
    "RunOut",
    "RunSummaryOut",
]
