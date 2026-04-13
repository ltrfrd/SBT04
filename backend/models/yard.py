from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


# -----------------------------------------------------------
# - Yard Model
# - Represents operational grouping under an operator
# -----------------------------------------------------------
class Yard(Base):
    __tablename__ = "yards"

    id = Column(Integer, primary_key=True, index=True)  # internal ID
    name = Column(String, nullable=False)  # yard name
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=False)

    operator = relationship("Operator", back_populates="yards")
