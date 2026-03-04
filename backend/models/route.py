# ===========================================================
# backend/models/route.py — BST Route Model
# -----------------------------------------------------------
# Defines the Route table with many-to-many to School, driver, and stops
# ===========================================================
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base  # Root-level
from .associations import route_schools  # Many-to-many table


# -----------------------------------------------------------
# Route model
# -----------------------------------------------------------
class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)  # backend/models/route.py
    route_number = Column(String(50), nullable=False)  # ← NEW
    unit_number = Column(String(50), nullable=True)  # ← NULL allowed
    num_runs = Column(Integer, nullable=True)  # No default

    # Foreign key to Driver (optional: one route can have one primary driver)
    driver_id = Column(Integer, ForeignKey("drivers.id"))

    # -------------------------------------------------------
    # Relationships
    # -------------------------------------------------------
    # One-to-Many: Route → Driver
    driver = relationship("Driver", back_populates="routes")

    # Many-to-Many: Route ↔ School
    schools = relationship("School", secondary=route_schools, back_populates="routes")

    # One-to-Many: Route → Stops
    stops = relationship("Stop", back_populates="route", cascade="all, delete-orphan")

    # One-to-Many: Route → Runs
    runs = relationship("Run", back_populates="route", cascade="all, delete-orphan")

    # One-to-Many: Route → Students (assigned to this route)
    students = relationship("Student", back_populates="route")
