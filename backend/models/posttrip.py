# -----------------------------------------------------------
# - Post-Trip Inspection Model
# -----------------------------------------------------------
from datetime import datetime, timezone  # Timestamp helpers

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint  # SQLAlchemy column types
from sqlalchemy.orm import relationship  # ORM relationship mapping

from database import Base  # Shared declarative base


# -----------------------------------------------------------
# - Post-trip inspection
# -----------------------------------------------------------
class PostTripInspection(Base):
    __tablename__ = "posttrip_inspections"  # Persist one post-trip per run

    id = Column(Integer, primary_key=True, index=True)  # Unique post-trip identifier
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)  # Linked run
    bus_id = Column(Integer, ForeignKey("buses.id", ondelete="RESTRICT"), nullable=False, index=True)  # Bus used for the run
    route_id = Column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)  # Route linked to the run
    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True, index=True)  # Driver recorded for later workflow/reporting

    phase1_completed = Column(Boolean, nullable=False, default=False)  # Phase 1 checklist completion flag
    phase1_completed_at = Column(DateTime, nullable=True)  # When Phase 1 was completed
    phase1_no_students_remaining = Column(Boolean, nullable=False, default=False)  # Confirms no students remain onboard
    phase1_belongings_checked = Column(Boolean, nullable=False, default=False)  # Confirms belongings scan was done
    phase1_checked_sign_hung = Column(Boolean, nullable=False, default=False)  # Confirms checked sign is hung

    phase2_completed = Column(Boolean, nullable=False, default=False)  # Phase 2 checklist completion flag
    phase2_completed_at = Column(DateTime, nullable=True)  # When Phase 2 was completed
    phase2_pending_since = Column(DateTime, nullable=True)  # When Phase 2 became the pending next step
    phase2_status = Column(String(50), nullable=False, default="not_started")  # not_started / pending / completed / overdue / suspected_neglect
    phase2_full_internal_recheck = Column(Boolean, nullable=False, default=False)  # Confirms full internal recheck
    phase2_checked_to_cleared_switched = Column(Boolean, nullable=False, default=False)  # Confirms status sign switch
    phase2_rear_button_triggered = Column(Boolean, nullable=False, default=False)  # Confirms rear safety button trigger

    exterior_status = Column(String(20), nullable=True)  # clear / minor / major for later workflow use
    exterior_description = Column(Text, nullable=True)  # Optional exterior issue details
    last_driver_activity_at = Column(DateTime, nullable=True)  # Latest meaningful post-trip driver interaction time
    last_known_lat = Column(Float, nullable=True)  # Last known GPS latitude from the live websocket stream
    last_known_lng = Column(Float, nullable=True)  # Last known GPS longitude from the live websocket stream
    last_location_update_at = Column(DateTime, nullable=True)  # When the last GPS point was persisted
    neglect_flagged_at = Column(DateTime, nullable=True)  # When a later process flags suspected neglect
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC creation time
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC update time

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_posttrip_inspection_run"),  # One post-trip per run
    )

    run = relationship("Run")  # Load linked run when needed
    bus = relationship("Bus")  # Load linked bus when needed
    route = relationship("Route")  # Load linked route when needed
    driver = relationship("Driver")  # Load linked driver when needed
    photos = relationship(
        "PostTripPhoto",
        back_populates="inspection",
        cascade="all, delete-orphan",
        order_by="PostTripPhoto.id.asc()",
    )  # Driver-captured photo rows for both post-trip phases


# -----------------------------------------------------------
# - Post-trip photos
# -----------------------------------------------------------
class PostTripPhoto(Base):
    __tablename__ = "posttrip_photos"  # Persist auditable phase photos separate from checklist state

    id = Column(Integer, primary_key=True, index=True)  # Unique photo identifier
    posttrip_inspection_id = Column(Integer, ForeignKey("posttrip_inspections.id", ondelete="CASCADE"), nullable=False, index=True)  # Parent post-trip inspection
    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)  # Linked run for audit and uniqueness
    phase = Column(String(20), nullable=False, index=True)  # phase1 / phase2
    photo_type = Column(String(50), nullable=False, index=True)  # Required photo category inside the phase
    file_path = Column(String(255), nullable=False)  # Relative media path only
    mime_type = Column(String(100), nullable=False)  # Accepted stored image MIME type
    file_size_bytes = Column(Integer, nullable=False)  # Stored file size in bytes
    source = Column(String(20), nullable=False, default="camera")  # camera / compatibility_camera
    captured_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Driver capture time
    captured_lat = Column(Float, nullable=True)  # Optional capture latitude when available
    captured_lng = Column(Float, nullable=True)  # Optional capture longitude when available
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC creation time
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # Naive UTC update time

    __table_args__ = (
        UniqueConstraint("run_id", "photo_type", name="uq_posttrip_photos_run_type"),  # One active photo row per run and photo type
    )

    inspection = relationship("PostTripInspection", back_populates="photos")  # Parent post-trip inspection
    run = relationship("Run")  # Linked run when photos are reviewed later
