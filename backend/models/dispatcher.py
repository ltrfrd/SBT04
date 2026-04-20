from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class Dispatcher(Base):
    __tablename__ = "dispatchers"

    id = Column(Integer, primary_key=True, index=True)
    yard_id = Column(Integer, ForeignKey("yards.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)

    yard = relationship("Yard", back_populates="dispatchers")
    approved_dispatch_records = relationship(
        "DispatchRecord",
        back_populates="approved_by_dispatcher",
    )
