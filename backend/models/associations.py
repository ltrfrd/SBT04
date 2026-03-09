# =============================================================================
# Imports
# =============================================================================
from sqlalchemy import Boolean, DateTime, Table, Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base


# =============================================================================
# Route ↔ School association
# Many-to-many relationship between routes and schools
# =============================================================================
route_schools = Table(
    "route_schools",
    Base.metadata,
    Column("route_id", Integer, ForeignKey("routes.id"), primary_key=True),
    Column("school_id", Integer, ForeignKey("schools.id"), primary_key=True),
)


# =============================================================================
# StudentRunAssignment
# Runtime mapping between Student, Run, and Stop
# Used to track pickups, dropoffs, and onboard state during a run
# =============================================================================
class StudentRunAssignment(Base):
    __tablename__ = "student_run_assignments"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(Integer, ForeignKey("stops.id", ondelete="CASCADE"), nullable=False)

    # -------------------------------------------------------------------------
    # Ensure a student appears only once per run
    # -------------------------------------------------------------------------
    __table_args__ = (
        UniqueConstraint("student_id", "run_id", name="uq_student_run_assignment"),
    )

    # -------------------------------------------------------------------------
    # ORM relationships
    # -------------------------------------------------------------------------
    student = relationship("Student", back_populates="run_assignments")
    run = relationship("Run", back_populates="student_assignments")
    stop = relationship("Stop", back_populates="student_assignments")

    # -------------------------------------------------------------------------
    # Run operation state
    # -------------------------------------------------------------------------
    picked_up = Column(Boolean, default=False, nullable=False)     # Student boarded the bus
    picked_up_at = Column(DateTime, nullable=True)                 # Boarding timestamp
    dropped_off = Column(Boolean, default=False, nullable=False)   # Student exited the bus
    dropped_off_at = Column(DateTime, nullable=True)               # Exit timestamp
    is_onboard = Column(Boolean, default=False, nullable=False)    # True while student is on the bus