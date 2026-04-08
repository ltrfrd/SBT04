# -----------------------------------------------------------
# Dispatch Alert Model
# - Store focused persistent alerts for pre-trip enforcement
# -----------------------------------------------------------
from datetime import datetime, timezone  # Timestamp helpers

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text  # SQLAlchemy column types

from database import Base  # Shared declarative base


# -----------------------------------------------------------
# - Dispatch alert
# - Persist unresolved and resolved enforcement alerts
# -----------------------------------------------------------
class DispatchAlert(Base):
    __tablename__ = "dispatch_alerts"  # Persist alerts here

    id = Column(Integer, primary_key=True, index=True)  # Unique alert identifier
    alert_type = Column(String(100), nullable=False, index=True)  # Alert category key
    severity = Column(String(50), nullable=False)  # urgent / warning style severity label
    message = Column(Text, nullable=False)  # Human-readable alert message
    bus_id = Column(Integer, ForeignKey("buses.id", ondelete="SET NULL"), nullable=True, index=True)  # Related bus when known
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="SET NULL"), nullable=True, index=True)  # Related route when known
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)  # Related run when known
    pretrip_id = Column(Integer, ForeignKey("pretrip_inspections.id", ondelete="SET NULL"), nullable=True, index=True)  # Related pre-trip when known
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC creation time
    resolved = Column(Boolean, nullable=False, default=False)  # Current alert resolution flag
    resolved_at = Column(DateTime, nullable=True)  # When the alert was resolved
