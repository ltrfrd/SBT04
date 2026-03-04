# ===========================================================
# backend/models/run.py — BST Run Model
# -----------------------------------------------------------
# Defines a single bus run (AM or PM) with driver, route, and timing
# ===========================================================
from sqlalchemy import Column, Integer, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from database import Base  # Root-level
import enum


# -----------------------------------------------------------
# Run type enum: AM or PM
# -----------------------------------------------------------
class RunType(str, enum.Enum):
    AM = "AM"
    MIDDAY = "MIDDAY"
    PM = "PM"
    EXTRA = "EXTRA"


# -----------------------------------------------------------
# Run model
# -----------------------------------------------------------
class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    run_type = Column(Enum(RunType), nullable=False)  # AM or PM
    start_time = Column(DateTime, nullable=False)  # Actual start time
    end_time = Column(DateTime)  # Actual end time (nullable until completed)

    # -------------------------------------------------------
    # Relationships
    # -------------------------------------------------------
    driver = relationship("Driver", back_populates="runs")
    route = relationship("Route", back_populates="runs")
