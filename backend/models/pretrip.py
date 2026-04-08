# -----------------------------------------------------------
# Pre-Trip Inspection Models
# - Store one bus-level pre-trip inspection per bus per day
# -----------------------------------------------------------
from datetime import datetime, timezone  # Timestamp helpers

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text, Time, UniqueConstraint  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship mapping

from database import Base  # Shared declarative base


# -----------------------------------------------------------
# - Pre-trip inspection
# - Store bus/day inspection header fields and audit metadata
# -----------------------------------------------------------
class PreTripInspection(Base):
    __tablename__ = "pretrip_inspections"  # Persist bus/day inspections here

    id = Column(Integer, primary_key=True, index=True)  # Unique inspection identifier
    bus_id = Column(Integer, ForeignKey("buses.id", ondelete="CASCADE"), nullable=False, index=True)  # Inspected bus
    license_plate = Column(String, nullable=False)  # Reported bus plate captured on the form
    driver_name = Column(String(255), nullable=False)  # Manual driver name captured on the form
    inspection_date = Column(Date, nullable=False, index=True)  # Bus-level inspection date
    inspection_time = Column(Time, nullable=False)  # Reported inspection time
    odometer = Column(Integer, nullable=False)  # Reported odometer reading
    inspection_place = Column(String(255), nullable=False)  # Where the inspection happened
    use_type = Column(String(50), nullable=False)  # school_bus or charter
    fit_for_duty = Column(String(10), nullable=False)  # yes or no
    no_defects = Column(Boolean, nullable=False, default=False)  # Defect-free flag for XOR validation
    signature = Column(Text, nullable=False)  # Captured signature payload/text
    is_corrected = Column(Boolean, nullable=False, default=False)  # Future correction workflow flag
    corrected_by = Column(String(255), nullable=True)  # Future correction actor
    corrected_at = Column(DateTime, nullable=True)  # Future correction timestamp
    original_payload = Column(JSON, nullable=True)  # Future audit snapshot of the submitted payload
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC creation time
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC update time

    __table_args__ = (
        UniqueConstraint("bus_id", "inspection_date", name="uq_pretrip_inspection_bus_date"),  # One inspection per bus per day
    )

    bus = relationship("Bus")  # Load inspected bus when needed
    defects = relationship("PreTripDefect", back_populates="inspection", cascade="all, delete-orphan", passive_deletes=True)  # Load attached defect rows

    @property
    def bus_number(self) -> str | None:
        return self.bus.unit_number if self.bus is not None else None  # Expose the user-facing bus number from the related bus


# -----------------------------------------------------------
# - Pre-trip defect
# - Store one reported defect row under a pre-trip inspection
# -----------------------------------------------------------
class PreTripDefect(Base):
    __tablename__ = "pretrip_defects"  # Persist defect rows here

    id = Column(Integer, primary_key=True, index=True)  # Unique defect identifier
    pretrip_id = Column(Integer, ForeignKey("pretrip_inspections.id", ondelete="CASCADE"), nullable=False, index=True)  # Parent inspection
    description = Column(Text, nullable=False)  # Reported defect description
    severity = Column(String(20), nullable=False)  # minor or major

    inspection = relationship("PreTripInspection", back_populates="defects")  # Load parent inspection
