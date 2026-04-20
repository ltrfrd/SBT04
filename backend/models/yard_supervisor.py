from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class YardSupervisor(Base):
    __tablename__ = "yard_supervisors"

    id = Column(Integer, primary_key=True, index=True)
    yard_id = Column(Integer, ForeignKey("yards.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("yard_id", name="uq_yard_supervisors_yard_id"),
    )

    yard = relationship("Yard", back_populates="yard_supervisor")
