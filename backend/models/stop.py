# ===========================================================  # File header
# backend/models/stop.py — BST Stop Model                      # File path + purpose
# -----------------------------------------------------------  # Separator
# Defines the Stop table using numeric order instead of names.  # Model summary
# Each stop belongs to a route and can be pickup or dropoff.    # Ownership + type
# ===========================================================  # Separator

from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    Enum,
    String,
    Float,
    Index,
)  # Add Index for DB performance
from sqlalchemy.orm import relationship  # SQLAlchemy relationships
from database import Base  # Root-level import
import enum  # Python enum


# -----------------------------------------------------------  # Separator
# Stop type enum: pickup or dropoff                            # Enum purpose
# -----------------------------------------------------------  # Separator
class StopType(str, enum.Enum):  # Enum class
    PICKUP = "pickup"  # Pickup stop
    DROPOFF = "dropoff"  # Dropoff stop


# -----------------------------------------------------------  # Separator
# Stop model                                                   # Model purpose
# -----------------------------------------------------------  # Separator
class Stop(Base):  # ORM model
    __tablename__ = "stops"  # DB table name

    __table_args__ = (  # Table-level DB options
        Index(
            "ix_stops_route_id_sequence", "route_id", "sequence"
        ),  # Speeds up route filter + ordering
    )  # End table args

    id = Column(Integer, primary_key=True, index=True)  # Unique stop ID
    sequence = Column(Integer, nullable=False)  # Numeric order (1, 2, 3...)
    type = Column(Enum(StopType), nullable=False)  # Stop type (pickup/dropoff)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)  # Linked route
    name = Column(String(100), nullable=True)  # Optional stop label
    address = Column(String(255), nullable=True)  # Optional stop address
    latitude = Column(Float, nullable=True)  # Optional latitude
    longitude = Column(Float, nullable=True)  # Optional longitude

    # -------------------------------------------------------  # Separator
    # Relationships                                            # Relationship group
    # -------------------------------------------------------  # Separator
    route = relationship(
        "Route", back_populates="stops"
    )  # Each stop belongs to one route
    students = relationship(
        "Student", back_populates="stop"
    )  # Students linked to this stop
