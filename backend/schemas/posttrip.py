# -----------------------------------------------------------
# - Post-Trip Schemas
# -----------------------------------------------------------
from __future__ import annotations

from datetime import datetime  # Datetime types used in API schemas

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # Pydantic schema helpers


VALID_EXTERIOR_STATUSES = {"clear", "minor", "major"}  # Supported exterior condition labels


def _normalize_required_description(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


# -----------------------------------------------------------
# - Post-trip phase 1 submit
# -----------------------------------------------------------
class PostTripPhase1Submit(BaseModel):
    phase1_no_students_remaining: bool  # Confirms no students remain onboard
    phase1_belongings_checked: bool  # Confirms belongings check was done
    phase1_checked_sign_hung: bool  # Confirms checked sign is hung

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_phase1_checklist(self) -> PostTripPhase1Submit:
        if not self.phase1_no_students_remaining:
            raise ValueError("phase1_no_students_remaining must be true")
        if not self.phase1_belongings_checked:
            raise ValueError("phase1_belongings_checked must be true")
        if not self.phase1_checked_sign_hung:
            raise ValueError("phase1_checked_sign_hung must be true")
        return self


# -----------------------------------------------------------
# - Post-trip phase 2 submit
# -----------------------------------------------------------
class PostTripPhase2Submit(BaseModel):
    phase2_full_internal_recheck: bool  # Confirms full internal recheck
    phase2_checked_to_cleared_switched: bool  # Confirms sign switched to cleared
    phase2_rear_button_triggered: bool  # Confirms rear safety button trigger
    exterior_status: str  # clear / minor / major
    exterior_description: str | None = None  # Optional exterior issue description

    model_config = ConfigDict(extra="forbid")

    @field_validator("exterior_status")
    @classmethod
    def validate_exterior_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_EXTERIOR_STATUSES:
            raise ValueError("exterior_status must be clear, minor, or major")
        return normalized

    @field_validator("exterior_description")
    @classmethod
    def validate_exterior_description(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_phase2_submit(self) -> PostTripPhase2Submit:
        if not self.phase2_full_internal_recheck:
            raise ValueError("phase2_full_internal_recheck must be true")
        if not self.phase2_checked_to_cleared_switched:
            raise ValueError("phase2_checked_to_cleared_switched must be true")
        if not self.phase2_rear_button_triggered:
            raise ValueError("phase2_rear_button_triggered must be true")
        if self.exterior_status in {"minor", "major"} and self.exterior_description is None:
            raise ValueError("exterior_description is required when exterior_status is minor or major")
        if self.exterior_status == "clear" and self.exterior_description == "":
            self.exterior_description = None
        return self


# -----------------------------------------------------------
# - Post-trip output
# -----------------------------------------------------------
class PostTripOut(BaseModel):
    id: int  # Post-trip identifier
    run_id: int  # Linked run identifier
    bus_id: int  # Linked bus identifier
    route_id: int  # Linked route identifier
    driver_id: int | None = None  # Linked driver identifier when present
    phase1_completed: bool  # Phase 1 completion flag
    phase1_completed_at: datetime | None = None  # Phase 1 completion time
    phase1_no_students_remaining: bool  # Phase 1 checklist item
    phase1_belongings_checked: bool  # Phase 1 checklist item
    phase1_checked_sign_hung: bool  # Phase 1 checklist item
    phase2_completed: bool  # Phase 2 completion flag
    phase2_completed_at: datetime | None = None  # Phase 2 completion time
    phase2_pending_since: datetime | None = None  # When phase 2 became pending
    phase2_status: str | None = None  # Current phase 2 status label
    phase2_full_internal_recheck: bool  # Phase 2 checklist item
    phase2_checked_to_cleared_switched: bool  # Phase 2 checklist item
    phase2_rear_button_triggered: bool  # Phase 2 checklist item
    exterior_status: str | None = None  # Exterior post-run condition
    exterior_description: str | None = None  # Exterior condition detail
    last_driver_activity_at: datetime | None = None  # Latest post-trip driver interaction time
    last_known_lat: float | None = None  # Last known GPS latitude
    last_known_lng: float | None = None  # Last known GPS longitude
    last_location_update_at: datetime | None = None  # When the last GPS point was persisted
    neglect_flagged_at: datetime | None = None  # When suspected neglect was flagged later
    phase2_decision_status: str | None = None  # Read-only decision label for current phase 2 state
    has_recent_driver_activity: bool | None = None  # Read-only recent driver interaction flag
    has_recent_location_activity: bool | None = None  # Read-only recent GPS activity flag
    minutes_since_phase2_pending: float | None = None  # Minutes since phase 2 became pending
    minutes_since_driver_activity: float | None = None  # Minutes since last post-trip driver activity
    minutes_since_location_update: float | None = None  # Minutes since last GPS update
    created_at: datetime  # Record creation timestamp
    updated_at: datetime  # Record update timestamp

    model_config = ConfigDict(from_attributes=True, extra="forbid")
