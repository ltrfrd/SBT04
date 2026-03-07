from sqlalchemy import Column, Integer, ForeignKey, Enum, String, Float, Index, Time, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
import enum


class StopType(str, enum.Enum):
    PICKUP = "pickup"
    DROPOFF = "dropoff"


class Stop(Base):
    __tablename__ = "stops"

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_stops_run_sequence"),
        Index("ix_stops_run_id_sequence", "run_id", "sequence"),
    )

    id = Column(Integer, primary_key=True, index=True)
    sequence = Column(Integer, nullable=False)
    type = Column(Enum(StopType), nullable=False)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    planned_time = Column(Time, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    run = relationship("Run", back_populates="stops")
    students = relationship("Student", viewonly=True)
    student_assignments = relationship(
        "StudentRunAssignment",
        back_populates="stop",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
