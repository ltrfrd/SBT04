from uuid import uuid4

from sqlalchemy import Boolean, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    grade = Column(String(10))
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    # Transitional legacy pointers for default roster/home stop metadata.
    # Runtime rider-to-run/stop assignment is authoritative in StudentRunAssignment.
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="SET NULL"), nullable=True)
    stop_id = Column(Integer, ForeignKey("stops.id", ondelete="SET NULL"), nullable=True)
    notification_distance_meters = Column(Integer, default=500)
    qr_token = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid4()))
    qr_active = Column(Boolean, default=True, nullable=False)

    district = relationship("District", back_populates="students")
    school = relationship("School", back_populates="students")
    route = relationship("Route", foreign_keys=[route_id])
    stop = relationship("Stop", foreign_keys=[stop_id])
    run_assignments = relationship(
        "StudentRunAssignment",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    bus_absences = relationship(
        "StudentBusAbsence",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def school_name(self) -> str | None:
        return self.school.name if self.school else None

