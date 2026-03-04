# ===========================================================
# backend/models/school.py — BST School Model
# -----------------------------------------------------------
# Defines the School table and its relationships with routes and students.
# ===========================================================
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from database import Base  # Root-level database.py
from .associations import route_schools  # associations.py is in the same folder


class School(Base):
    __tablename__ = "schools"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    address = Column(String(255), nullable=False)
    phone = Column(String(20))

    routes = relationship("Route", secondary=route_schools, back_populates="schools")
    students = relationship("Student", back_populates="school")
