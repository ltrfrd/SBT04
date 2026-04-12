# =============================================================================
# backend/models/route.py - Route Model
# -----------------------------------------------------------------------------
# Represents a school bus route in the system.
#
# Relationships:
#   Route -> RouteDriverAssignment (one-to-many)
#   Route -> Schools (many-to-many)
#   Route -> Runs (one-to-many)
#   Route -> Students (view-only legacy reference)
#
# Data flow in the system:
#   Route -> RouteDriverAssignment -> Runs -> Stops
#
# Notes:
#   - Runs represent actual operational trips (AM / PM).
#   - Stops belong to runs, not directly to routes.
#   - Students are assigned to runs dynamically using StudentRunAssignment.
# =============================================================================

from sqlalchemy import Column, ForeignKey, Integer, String, Text  # Table column types
from sqlalchemy.orm import relationship                    # ORM relationship mapping

from database import Base                                  # Declarative base for models
from .associations import route_schools                    # Many-to-many association table


# =============================================================================
# Route Model
# =============================================================================
class Route(Base):

    __tablename__ = "routes"                               # Database table name

    id = Column(Integer, primary_key=True, index=True)     # Unique route identifier
    district_id = Column(Integer, ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True)
    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    route_number = Column(String(50), nullable=False)      # Public route number (ex: "102A")
    bus_id = Column(Integer, ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)  # Current assigned bus
    primary_bus_id = Column(Integer, ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)  # Default/base route bus
    active_bus_id = Column(Integer, ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)  # Current operational route bus
    clearance_note = Column(Text, nullable=True)            # Optional dispatch note when restoring the primary bus
    num_runs = Column(Integer, nullable=True)              # Number of runs assigned to route

    district = relationship(
        "District",
        back_populates="routes",
    )

    operator = relationship(
        "Operator",
        back_populates="routes",
    )

    driver_assignments = relationship(
        "RouteDriverAssignment",
        back_populates="route",                            # Linked from RouteDriverAssignment.route
        cascade="all, delete-orphan",                      # Delete assignments if route removed
        passive_deletes=True,                              # Use DB-level ON DELETE
    )

    schools = relationship(
        "School",
        secondary=route_schools,                           # Many-to-many via association table
        back_populates="routes",
    )

    runs = relationship(
        "Run",
        back_populates="route",                            # Linked from Run.route
        cascade="all, delete-orphan",                      # Delete runs if route removed
        passive_deletes=True,                              # Use DB-level ON DELETE
    )

    bus = relationship(
        "Bus",
        back_populates="routes",                           # Linked from Bus.routes
        foreign_keys=[bus_id],                             # Compatibility-facing active bus pointer
    )

    primary_bus = relationship(
        "Bus",
        foreign_keys=[primary_bus_id],                     # Default/base bus pointer
    )

    active_bus = relationship(
        "Bus",
        foreign_keys=[active_bus_id],                      # Current operational bus pointer
    )

    students = relationship(
        "Student",
        viewonly=True,                                     # Not used for runtime assignment
    )
    operator_access = relationship(
        "OperatorRouteAccess",
        back_populates="route",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

