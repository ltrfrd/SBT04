# ============================================================
# Run model for BusTrack operational runs
# ============================================================

# -----------------------------
# Imports
# -----------------------------
import enum  # Python enum support

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship mapping

from database import Base  # Declarative base class


# -----------------------------
# Router / Model / Schema
# -----------------------------
class RunType(str, enum.Enum):
    AM = "AM"  # Morning run type
    MIDDAY = "MIDDAY"  # Midday run type
    PM = "PM"  # Afternoon run type
    EXTRA = "EXTRA"  # Extra run type


# -----------------------------
# Logic
# -----------------------------
class Run(Base):
    __tablename__ = "runs"  # Persist runs in the runs table

    id = Column(Integer, primary_key=True, index=True)  # Store unique run ID
    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False)  # Store assigned driver ID
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)  # Store assigned route ID
    run_type = Column(Enum(RunType), nullable=False)  # Store operational run type
    start_time = Column(DateTime, nullable=False)  # Store when the run started
    end_time = Column(DateTime)  # Store when the run ended
    current_stop_id = Column(Integer, nullable=True)  # Store current actual stop ID without enforcing a cyclic FK
    current_stop_sequence = Column(Integer, nullable=True)  # Store current actual stop sequence

    driver = relationship("Driver", back_populates="runs")  # Load assigned driver
    route = relationship("Route", back_populates="runs")  # Load assigned route
    stops = relationship("Stop", back_populates="run", cascade="all, delete-orphan", passive_deletes=True, foreign_keys="Stop.run_id")  # Load stops that belong to this run
    student_assignments = relationship("StudentRunAssignment", back_populates="run", cascade="all, delete-orphan", passive_deletes=True)  # Load runtime student assignments
