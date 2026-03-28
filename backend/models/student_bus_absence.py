# -----------------------------------------------------------
# Student Bus Absence Model
# - Store planned no-ride records separately from incidents
# -----------------------------------------------------------
import enum  # Enum support for source values
from datetime import datetime, timezone  # Timestamp helpers

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship mapping

from database import Base  # Shared declarative base


class StudentBusAbsenceSource(str, enum.Enum):
    PARENT = "parent"  # Parent-reported planned absence
    SCHOOL = "school"  # School-reported planned absence
    DISPATCH = "dispatch"  # Dispatch-reported planned absence


class StudentBusAbsence(Base):
    __tablename__ = "student_bus_absences"  # Persist planned bus absences here

    id = Column(Integer, primary_key=True, index=True)  # Unique absence identifier
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)  # Linked student
    date = Column(Date, nullable=False, index=True)  # Planned no-ride date
    run_type = Column(String, nullable=False)  # Flexible run label matched against the run record
    source = Column(Enum(StudentBusAbsenceSource), nullable=False, default=StudentBusAbsenceSource.PARENT)  # Who reported the absence
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC creation timestamp

    __table_args__ = (
        UniqueConstraint("student_id", "date", "run_type", name="uq_student_bus_absence_student_date_run_type"),  # Prevent duplicate planned absences
    )

    student = relationship("Student", back_populates="bus_absences")  # Load linked student
