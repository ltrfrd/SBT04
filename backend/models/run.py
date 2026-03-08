# =============================================================================
# backend/models/run.py — SBT02 Run Model
# -----------------------------------------------------------------------------
# Represents one operational run for a route.
#
# Examples:
#   - AM run
#   - MIDDAY run
#   - PM run
#   - EXTRA run
#
# Core hierarchy:
#   Route -> Runs -> Stops
#
# Notes:
#   - A run belongs to exactly one driver and one route.
#   - Stops belong to runs, not directly to routes.
#   - Runtime rider mapping is handled through StudentRunAssignment.
#   - start_time is required.
#   - end_time is null while the run is active.
# =============================================================================

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
from sqlalchemy import Column, Integer, ForeignKey, DateTime, Enum  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship mapping
from database import Base  # Declarative base class
import enum  # Python enum support


# =============================================================================
# Run Type Enum
# Defines the allowed operational run types
# =============================================================================
class RunType(str, enum.Enum):
    AM = "AM"               # Morning run
    MIDDAY = "MIDDAY"       # Midday run
    PM = "PM"               # Afternoon / dismissal run
    EXTRA = "EXTRA"         # Extra / special run


# =============================================================================
# Run Model
# =============================================================================
class Run(Base):
    __tablename__ = "runs"  # Database table name

    # -------------------------------------------------------------------------
    # Primary Key
    # -------------------------------------------------------------------------
    id = Column(Integer, primary_key=True, index=True)  # Unique run ID

    # -------------------------------------------------------------------------
    # Foreign Keys
    # -------------------------------------------------------------------------
    driver_id = Column(
        Integer,
        ForeignKey("drivers.id", ondelete="RESTRICT"),  # Driver cannot be deleted if run exists
        nullable=False                                  # Every run must have a driver
    )

    route_id = Column(
        Integer,
        ForeignKey("routes.id", ondelete="CASCADE"),    # Delete runs if parent route is deleted
        nullable=False                                  # Every run must belong to a route
    )

    # -------------------------------------------------------------------------
# Operational Fields
# -------------------------------------------------------------------------
    run_type = Column(
        Enum(RunType),
        nullable=False                                  # Run type is required
    )

    start_time = Column(
        DateTime,
        nullable=False                                  # Run start time is required
    )

    end_time = Column(
        DateTime                                        # Null while run is still active
    )

# -------------------------------------------------------------------------
# Live progress tracking
# -------------------------------------------------------------------------
    current_stop_sequence = Column(
        Integer,
        nullable=True                                   # Driver's current stop sequence in the run
    )

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------
    driver = relationship(
        "Driver",
        back_populates="runs"                           # Linked from Driver.runs
    )

    route = relationship(
        "Route",
        back_populates="runs"                           # Linked from Route.runs
    )

    stops = relationship(
        "Stop",
        back_populates="run",                           # Linked from Stop.run
        cascade="all, delete-orphan",                   # Delete stops if run is deleted
        passive_deletes=True,                           # Use DB delete behavior
    )

    student_assignments = relationship(
        "StudentRunAssignment",
        back_populates="run",                           # Linked from StudentRunAssignment.run
        cascade="all, delete-orphan",                   # Delete assignments if run is deleted
        passive_deletes=True,                           # Use DB delete behavior
    )