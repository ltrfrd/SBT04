from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from .associations import route_schools


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    route_number = Column(String(50), nullable=False)
    unit_number = Column(String(50), nullable=True)
    num_runs = Column(Integer, nullable=True)
    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)

    driver = relationship("Driver", back_populates="routes")
    schools = relationship("School", secondary=route_schools, back_populates="routes")
    runs = relationship(
        "Run",
        back_populates="route",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    students = relationship("Student", viewonly=True)
