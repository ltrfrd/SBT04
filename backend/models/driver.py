# ===========================================================
# backend/models/driver.py - SBT Driver Model
# -----------------------------------------------------------
# Defines the Driver table and relationships with other entities.
# ===========================================================

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from database import Base


# -----------------------------------------------------------
# Driver model
# -----------------------------------------------------------
class Driver(Base):
    __tablename__ = "drivers"  # Database table name

    id = Column(Integer, primary_key=True, index=True)  # Unique driver ID
    name = Column(String(100), nullable=False)  # Full name of the driver
    email = Column(String(120), unique=True, index=True, nullable=False)  # Contact email
    phone = Column(String(20))  # Driver phone number

    # -------------------------------------------------------
    # Relationships
    # -------------------------------------------------------
    route_assignments = relationship(
        "RouteDriverAssignment",
        back_populates="driver",  # One driver -> many route assignments
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs = relationship("Run", back_populates="driver")  # One driver -> many runs
    payroll_records = relationship("Payroll", back_populates="driver")  # Payroll entries
