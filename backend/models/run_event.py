# ===========================================================
# backend/models/run_event.py — Run Event Log
# -----------------------------------------------------------
# Records operational events during a run.
# Used to reconstruct full run timeline.
# ===========================================================

from sqlalchemy import Column, Integer, ForeignKey, DateTime, String      # SQLAlchemy column types
from sqlalchemy.orm import relationship                                    # ORM relationships
from datetime import datetime, timezone                                    # UTC timestamp support
from database import Base                                                  # SQLAlchemy Base

# -----------------------------------------------------------
# RunEvent model
# - Stores bus activity timeline
# -----------------------------------------------------------
class RunEvent(Base):
    __tablename__ = "run_events"                                           # Table name

    id = Column(Integer, primary_key=True, index=True)                     # Event ID
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)        # Related run
    stop_id = Column(Integer, ForeignKey("stops.id"), nullable=True)       # Stop where event occurred
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True) # Student involved (if any)
    event_type = Column(String, nullable=False)                            # ARRIVE | PICKUP | DROPOFF
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)  # Event timestamp

    run = relationship("Run", back_populates="events")                     # Parent run
    stop = relationship("Stop")                                            # Related stop
    student = relationship("Student")                                      # Related student
# -----------------------------------------------------------
# Relationships
# - Event timeline for this run
# -----------------------------------------------------------
events = relationship("RunEvent", back_populates="run", cascade="all, delete-orphan")  # Run timeline events