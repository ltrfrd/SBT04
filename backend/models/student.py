from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    grade = Column(String(10))
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    # Transitional legacy pointers for default roster/home stop metadata.
    # Runtime rider-to-run/stop assignment is authoritative in StudentRunAssignment.
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="SET NULL"), nullable=True)
    stop_id = Column(Integer, ForeignKey("stops.id", ondelete="SET NULL"), nullable=True)
    notification_distance_meters = Column(Integer, default=500)

    school = relationship("School", back_populates="students")
    route = relationship("Route", foreign_keys=[route_id])
    stop = relationship("Stop", foreign_keys=[stop_id])
    run_assignments = relationship(
        "StudentRunAssignment",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
