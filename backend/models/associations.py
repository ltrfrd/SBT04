# ============================================================
# Association models for BusTrack routing and run operations
# ============================================================

# -----------------------------
# Imports
# -----------------------------
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship helpers

from database import Base  # Shared declarative base


# -----------------------------
# Router / Model / Schema
# -----------------------------
route_schools = Table(
    "route_schools",
    Base.metadata,
    Column("route_id", Integer, ForeignKey("routes.id"), primary_key=True),  # Link one route row
    Column("school_id", Integer, ForeignKey("schools.id"), primary_key=True),  # Link one school row
)  # Store route-to-school associations


# -----------------------------
# Logic
# -----------------------------
class StudentRunAssignment(Base):
    __tablename__ = "student_run_assignments"  # Persist runtime assignments here

    id = Column(Integer, primary_key=True, index=True)  # Store unique assignment ID
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)  # Link assigned student
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)  # Link operational run
    stop_id = Column(Integer, ForeignKey("stops.id", ondelete="CASCADE"), nullable=False)  # Link planned assigned stop
    actual_pickup_stop_id = Column(Integer, ForeignKey("stops.id", ondelete="SET NULL"), nullable=True)  # Store actual pickup stop ID
    actual_dropoff_stop_id = Column(Integer, ForeignKey("stops.id", ondelete="SET NULL"), nullable=True)  # Store actual dropoff stop ID
    __table_args__ = (
        UniqueConstraint("student_id", "run_id", name="uq_student_run_assignment"),  # Allow one assignment per student per run
    )  # Apply runtime uniqueness rule

    student = relationship("Student", back_populates="run_assignments")  # Load linked student
    run = relationship("Run", back_populates="student_assignments")  # Load linked run
    stop = relationship("Stop", back_populates="student_assignments", foreign_keys=[stop_id])  # Load planned stop
    actual_pickup_stop = relationship("Stop", foreign_keys=[actual_pickup_stop_id])  # Load actual pickup stop
    actual_dropoff_stop = relationship("Stop", foreign_keys=[actual_dropoff_stop_id])  # Load actual dropoff stop
    picked_up = Column(Boolean, default=False, nullable=False)  # Track whether boarding happened
    picked_up_at = Column(DateTime, nullable=True)  # Track when boarding happened
    dropped_off = Column(Boolean, default=False, nullable=False)  # Track whether exit happened
    dropped_off_at = Column(DateTime, nullable=True)  # Track when exit happened
    is_onboard = Column(Boolean, default=False, nullable=False)  # Track current onboard state
    # School-side verification status (set by school, not driver)
    school_status = Column(String, nullable=True)  # "present" or "absent"