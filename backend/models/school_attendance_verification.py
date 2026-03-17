# ============================================================
# School attendance verification model
# ============================================================

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint  # DB columns
from sqlalchemy.orm import relationship  # ORM relationships
from database import Base  # Shared declarative base


class SchoolAttendanceVerification(Base):
    __tablename__ = "school_attendance_verifications"  # New table name

    id = Column(Integer, primary_key=True, index=True)  # Row ID
    school_id = Column(Integer, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)  # School
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)  # Run
    confirmed_at = Column(DateTime(timezone=True), nullable=False)  # Confirmation time
    confirmed_by = Column(String(150), nullable=True)  # Optional staff/user name

    __table_args__ = (
        UniqueConstraint("school_id", "run_id", name="uq_school_run_verification"),  # One record per school/run
    )

    school = relationship("School")  # Linked school
    run = relationship("Run")  # Linked run