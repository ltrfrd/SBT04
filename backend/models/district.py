from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    contact_info = Column(String(255), nullable=True)

    schools = relationship("School", back_populates="district")
    routes = relationship("Route", back_populates="district")
    students = relationship("Student", back_populates="district")
