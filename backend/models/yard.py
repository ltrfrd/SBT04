from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base
from backend.models.associations import YardRouteAssignment


# -----------------------------------------------------------
# - Yard Model
# - Represents operational grouping under an operator
# -----------------------------------------------------------
class Yard(Base):
    __tablename__ = "yards"

    id = Column(Integer, primary_key=True, index=True)  # internal ID
    name = Column(String, nullable=False)  # yard name
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=False)

    operator = relationship("Operator", back_populates="yards")
    yard_supervisor = relationship(
        "YardSupervisor",
        back_populates="yard",
        uselist=False,
        cascade="all, delete-orphan",
    )
    dispatchers = relationship(
        "Dispatcher",
        back_populates="yard",
        cascade="all, delete-orphan",
    )
    drivers = relationship("Driver", back_populates="yard")
    buses = relationship("Bus", back_populates="yard")
    routes = relationship(
        "Route",
        secondary="yard_route_assignments",
        back_populates="yards",
    )
