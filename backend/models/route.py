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

from sqlalchemy import Column, ForeignKey, Integer, String  # Table column types
from sqlalchemy.orm import relationship                    # ORM relationship mapping

from database import Base                                  # Declarative base for models
from .associations import route_schools                    # Many-to-many association table


# =============================================================================
# Route Model
# =============================================================================
class Route(Base):

    __tablename__ = "routes"                               # Database table name

    id = Column(Integer, primary_key=True, index=True)     # Unique route identifier
    route_number = Column(String(50), nullable=False)      # Public route number (ex: "102A")
    bus_id = Column(Integer, ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)  # Current assigned bus
    num_runs = Column(Integer, nullable=True)              # Number of runs assigned to route

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
    )

    students = relationship(
        "Student",
        viewonly=True,                                     # Not used for runtime assignment
    )
