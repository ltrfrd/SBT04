from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class Operator(Base):
    __tablename__ = "operators"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True, index=True)

    yards = relationship("Yard", back_populates="operator")
    route_access = relationship(
        "OperatorRouteAccess",
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OperatorRouteAccess(Base):
    __tablename__ = "operator_route_access"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    access_level = Column(String(20), nullable=False, default="read")

    __table_args__ = (
        UniqueConstraint("route_id", "operator_id", name="uq_operator_route_access_route_operator"),
    )

    route = relationship("Route", back_populates="operator_access")
    operator = relationship("Operator", back_populates="route_access")


