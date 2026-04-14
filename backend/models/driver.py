# ===========================================================
# backend/models/driver.py - FleetOS Driver Model
# -----------------------------------------------------------
# Defines the Driver table and relationships with other entities.
# ===========================================================

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


# -----------------------------------------------------------
# Driver model
# -----------------------------------------------------------
class Driver(Base):
    __tablename__ = "drivers"  # Database table name

    id = Column(Integer, primary_key=True, index=True)  # Unique driver ID
    yard_id = Column(Integer, ForeignKey("yards.id"), nullable=True)
    name = Column(String(100), nullable=False)  # Full name of the driver
    email = Column(String(120), unique=True, index=True, nullable=False)  # Contact email
    phone = Column(String(20))  # Driver phone number
    pin_hash = Column(String(255), nullable=True)  # Store the hashed driver PIN used for login

    # -------------------------------------------------------
    # Relationships
    # -------------------------------------------------------
    yard = relationship("Yard", back_populates="drivers")
    route_assignments = relationship(
        "RouteDriverAssignment",
        back_populates="driver",  # One driver -> many route assignments
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs = relationship("Run", back_populates="driver")  # One driver -> many runs
    dispatch_records = relationship("DispatchRecord", back_populates="driver")  # Dispatch entries

