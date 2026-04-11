# ============================================================
# Stop model for FleetOS run stops
# ============================================================

# -----------------------------
# Imports
# -----------------------------
import enum  # Python enum support

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String, Time, UniqueConstraint  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship helpers

from database import Base  # Shared declarative base


# -----------------------------
# Router / Model / Schema
# -----------------------------
class StopType(str, enum.Enum):
    PICKUP = "PICKUP"  # Pickup stop type
    DROPOFF = "DROPOFF"  # Dropoff stop type
    SCHOOL_ARRIVE = "SCHOOL_ARRIVE"  # School arrival stop type
    SCHOOL_DEPART = "SCHOOL_DEPART"  # School departure stop type


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
    type = Column(String(32), nullable=False)  # Store canonical stop type without breaking legacy rows
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)  # Link the stop to its run
    school_id = Column(Integer, ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)  # Link school stops to a real school
    name = Column(String(100), nullable=True)  # Store stop display name
    address = Column(String(255), nullable=True)  # Store stop address
    planned_time = Column(Time, nullable=True)  # Store planned arrival time
    latitude = Column(Float, nullable=True)  # Store stop latitude
    longitude = Column(Float, nullable=True)  # Store stop longitude

    run = relationship("Run", back_populates="stops", foreign_keys=[run_id])  # Load owning run through Stop.run_id
    school = relationship("School", back_populates="stops")  # Load linked school for school stop rows
    students = relationship("Student", viewonly=True)  # Expose linked students without managing writes here
    student_assignments = relationship("StudentRunAssignment", back_populates="stop", cascade="all, delete-orphan", passive_deletes=True, foreign_keys="StudentRunAssignment.stop_id")  # Load planned student assignments for this stop
