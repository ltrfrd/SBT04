# ============================================================
# Stop model for BusTrack run stops
# ============================================================

# -----------------------------
# Imports
# -----------------------------
import enum  # Python enum support

from sqlalchemy import Column, Enum, Float, ForeignKey, Index, Integer, String, Time, UniqueConstraint  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship helpers

from database import Base  # Shared declarative base


# -----------------------------
# Router / Model / Schema
# -----------------------------
class StopType(str, enum.Enum):
    PICKUP = "pickup"  # Pickup stop type
    DROPOFF = "dropoff"  # Dropoff stop type


# -----------------------------
# Logic
# -----------------------------
class Stop(Base):
    __tablename__ = "stops"  # Persist run stops in the stops table
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_stops_run_sequence"),  # Enforce one sequence per run
        Index("ix_stops_run_id_sequence", "run_id", "sequence"),  # Speed up route stop ordering queries
    )  # Apply run stop constraints and indexes

    id = Column(Integer, primary_key=True, index=True)  # Store unique stop ID
    sequence = Column(Integer, nullable=False)  # Store planned stop order within a run
    type = Column(Enum(StopType), nullable=False)  # Store pickup or dropoff type
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)  # Link the stop to its run
    name = Column(String(100), nullable=True)  # Store stop display name
    address = Column(String(255), nullable=True)  # Store stop address
    planned_time = Column(Time, nullable=True)  # Store planned arrival time
    latitude = Column(Float, nullable=True)  # Store stop latitude
    longitude = Column(Float, nullable=True)  # Store stop longitude

    run = relationship("Run", back_populates="stops", foreign_keys=[run_id])  # Load owning run through Stop.run_id
    students = relationship("Student", viewonly=True)  # Expose linked students without managing writes here
    student_assignments = relationship("StudentRunAssignment", back_populates="stop", cascade="all, delete-orphan", passive_deletes=True, foreign_keys="StudentRunAssignment.stop_id")  # Load planned student assignments for this stop
