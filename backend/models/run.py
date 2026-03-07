from sqlalchemy import Column, Integer, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from database import Base
import enum


class RunType(str, enum.Enum):
    AM = "AM"
    MIDDAY = "MIDDAY"
    PM = "PM"
    EXTRA = "EXTRA"


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="RESTRICT"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)
    run_type = Column(Enum(RunType), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)

    driver = relationship("Driver", back_populates="runs")
    route = relationship("Route", back_populates="runs")
    stops = relationship(
        "Stop",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    student_assignments = relationship(
        "StudentRunAssignment",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
