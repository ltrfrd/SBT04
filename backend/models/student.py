# ===========================================================
# backend/models/student.py — BST Student Model
# -----------------------------------------------------------
# Defines the Student table with relationships to School, Route, and Stop
# ===========================================================
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base  # Root-level


# -----------------------------------------------------------
# Student model
# -----------------------------------------------------------
class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    grade = Column(String(10))  # e.g., "5th", "K", "12"
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"))  # Optional: assigned route
    stop_id = Column(Integer, ForeignKey("stops.id"))  # Optional: pickup/dropoff stop
    notification_distance_meters = Column(
        Integer, default=500
    )  # User sets in app (e.g., 200-1000m)
    # -------------------------------------------------------
    # Relationships
    # -------------------------------------------------------
    school = relationship("School", back_populates="students")
    route = relationship("Route", back_populates="students")
    stop = relationship("Stop", back_populates="students")
