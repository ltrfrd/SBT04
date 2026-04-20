# ============================================================
# Run verification summary model
# ============================================================

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class RunVerification(Base):
    __tablename__ = "run_verifications"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    mismatch_count = Column(Integer, nullable=False, default=0)
    confirmed_by_role = Column(String(20), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "direction", name="uq_run_verification_run_direction"),
    )

    run = relationship("Run", back_populates="verifications")
