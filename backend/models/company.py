from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True, index=True)

    drivers = relationship("Driver", back_populates="company")
    buses = relationship("Bus", back_populates="company")
    schools = relationship("School", back_populates="company")
    students = relationship("Student", back_populates="company")
    routes = relationship("Route", back_populates="company")
    route_access = relationship(
        "CompanyRouteAccess",
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CompanyRouteAccess(Base):
    __tablename__ = "company_route_access"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    access_level = Column(String(20), nullable=False, default="read")

    __table_args__ = (
        UniqueConstraint("route_id", "company_id", name="uq_company_route_access_route_company"),
    )

    route = relationship("Route", back_populates="company_access")
    company = relationship("Company", back_populates="route_access")
