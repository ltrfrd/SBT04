# ===========================================================
# backend/models/bus.py - Bus Model
# -----------------------------------------------------------
# Represents a standalone bus entity in the system.
# ===========================================================

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from database import Base


# -----------------------------------------------------------
# Bus model
# -----------------------------------------------------------
class Bus(Base):
    __tablename__ = "buses"  # Database table name

    id = Column(Integer, primary_key=True, index=True)  # Unique bus identifier
    unit_number = Column(String(50), unique=True, index=True, nullable=False)  # Visible bus unit number
    license_plate = Column(String(50), unique=True, index=True, nullable=False)  # Registration plate
    capacity = Column(Integer, nullable=False)  # Total seating capacity
    size = Column(String(50), nullable=False)  # Bus size label for first-layer compatibility

    routes = relationship(
        "Route",
        back_populates="bus",  # Current routes pointing at this bus
        foreign_keys="Route.bus_id",  # Keep compatibility route-bus relationship explicit
    )

    @property
    def bus_number(self) -> str:
        return self.unit_number  # User-facing bus label remains mapped to stored unit_number
