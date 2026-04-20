# ============================================================
# Run model for FleetOS operational runs
# ============================================================

# -----------------------------
# Imports
# -----------------------------
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Time  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship mapping

from database import Base  # Declarative base class

# -----------------------------
# Logic
# -----------------------------
class Run(Base):
    __tablename__ = "runs"  # Persist runs in the runs table

    id = Column(Integer, primary_key=True, index=True)  # Store unique run ID
    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=True)  # Store assigned driver ID when the run is started or preassigned
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)  # Store assigned route ID
    district_id = Column(Integer, ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True)  # Store planning district inherited from route when available
    run_type = Column(String, nullable=False)  # Store flexible operational run label
    scheduled_start_time = Column(Time, nullable=False)  # Store fixed planned start time
    scheduled_end_time = Column(Time, nullable=False)  # Store fixed planned end time
    start_time = Column(DateTime, nullable=True)  # Store when the run started
    end_time = Column(DateTime)  # Store when the run ended
    current_stop_id = Column(Integer, nullable=True)  # Store current actual stop ID without enforcing a cyclic FK
    current_stop_sequence = Column(Integer, nullable=True)  # Store current actual stop sequence
    is_completed = Column(Boolean, default=False, nullable=False)  # Run completion flag
    completed_at = Column(DateTime(timezone=True), nullable=True)  # When the run was completed

    driver = relationship("Driver", back_populates="runs")  # Load assigned driver
    route = relationship("Route", back_populates="runs")  # Load assigned route
    district = relationship("District", back_populates="runs")  # Load planning district when present
    stops = relationship("Stop", back_populates="run", cascade="all, delete-orphan", passive_deletes=True, foreign_keys="Stop.run_id")  # Load stops that belong to this run
    student_assignments = relationship("StudentRunAssignment", back_populates="run", cascade="all, delete-orphan", passive_deletes=True)  # Load runtime student assignments
    events = relationship("RunEvent", back_populates="run", cascade="all, delete-orphan")
    verifications = relationship("RunVerification", back_populates="run", cascade="all, delete-orphan", passive_deletes=True)
    
