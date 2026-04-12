# ===========================================================
# backend/models/school.py — BST School Model
# -----------------------------------------------------------
# Defines the School table and its relationships with routes and students.
# ===========================================================
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from database import Base  # Root-level database.py
from .associations import route_schools  # associations.py is in the same folder


class School(Base):
    __tablename__ = "schools"
    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True)
    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    address = Column(String(255), nullable=True)
    phone = Column(String(20))

    district = relationship("District", back_populates="schools")
    operator = relationship("Operator", back_populates="schools")
    routes = relationship("Route", secondary=route_schools, back_populates="schools")
    students = relationship("Student", back_populates="school")
    stops = relationship("Stop", back_populates="school")

