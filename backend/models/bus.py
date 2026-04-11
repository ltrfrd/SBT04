# ===========================================================
# backend/models/bus.py - Bus Model
# -----------------------------------------------------------
# Represents a standalone bus entity in the system.
# ===========================================================

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


# -----------------------------------------------------------
# Bus model
# -----------------------------------------------------------
class Bus(Base):
    __tablename__ = "buses"  # Database table name

    id = Column(Integer, primary_key=True, index=True)  # Unique bus identifier
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_number = Column(String(50), index=True, nullable=False)  # Visible bus unit number — unique per company
    license_plate = Column(String(50), index=True, nullable=False)  # Registration plate — unique per company
    capacity = Column(Integer, nullable=False)  # Total seating capacity
    size = Column(String(50), nullable=False)  # Bus size label for first-layer compatibility

    __table_args__ = (
        UniqueConstraint("company_id", "unit_number", name="uq_bus_company_unit_number"),
        UniqueConstraint("company_id", "license_plate", name="uq_bus_company_license_plate"),
    )

    company = relationship("Company", back_populates="buses")
    routes = relationship(
        "Route",
        back_populates="bus",  # Current routes pointing at this bus
        foreign_keys="Route.bus_id",  # Keep compatibility route-bus relationship explicit
    )

    @property
    def bus_number(self) -> str:
        return self.unit_number  # User-facing bus label remains mapped to stored unit_number
