# ===========================================================
# backend/models/dispatch.py — BST Dispatch Model
# -----------------------------------------------------------
# Dispatch module model wrapper for dispatch work records.
# ===========================================================
from sqlalchemy import Column, Integer, Date, Time, Boolean, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from database import Base  # Root-level
from datetime import datetime, timedelta


class DispatchRecord(Base):
    __tablename__ = "dispatch_records"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=False)
    work_date = Column(Date, nullable=False)  # Workday date
    charter_start = Column(Time, nullable=True)  # Start time for charter
    charter_end = Column(Time, nullable=True)  # End time for charter
    charter_hours = Column(Numeric(5, 2), default=0.00)  # Auto-calculated
    approved = Column(Boolean, default=False)  # Dispatch verification flag

    # -------------------------------------------------------
    # Relationships
    # -------------------------------------------------------
    driver = relationship("Driver", back_populates="dispatch_records")

    # -------------------------------------------------------
    # Auto-calculate charter hours from start → end
    # -------------------------------------------------------
    @property
    def calculate_charter_hours(self):
        if self.charter_start and self.charter_end:
            start = datetime.combine(datetime.min, self.charter_start)
            end = datetime.combine(datetime.min, self.charter_end)
            if end < start:
                end += timedelta(days=1)  # Handle overnight
            hours = (end - start).total_seconds() / 3600
            return round(hours, 2)
        return 0.0
