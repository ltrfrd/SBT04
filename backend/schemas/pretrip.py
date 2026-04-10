# -----------------------------------------------------------
# - Pre-Trip Schemas
# -----------------------------------------------------------
from __future__ import annotations

from datetime import date as dt_date, datetime, time as dt_time  # Date and timestamp types
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # Pydantic schema helpers


VALID_USE_TYPES = {"school_bus", "charter"}  # Supported inspection use types
VALID_FIT_FOR_DUTY = {"yes", "no"}  # Supported duty declarations
VALID_DEFECT_SEVERITIES = {"minor", "major"}  # Supported defect severities


def _normalize_required_string(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


# -----------------------------------------------------------
# - Pre-trip defect base
# -----------------------------------------------------------
class PreTripDefectBase(BaseModel):
    description: str = Field(min_length=1)  # Reported defect description
    severity: str  # minor or major

    model_config = ConfigDict(extra="forbid")

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _normalize_required_string(value, "description")

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_DEFECT_SEVERITIES:
            raise ValueError("severity must be minor or major")
        return normalized


class PreTripDefectCreate(PreTripDefectBase):
    pass


class PreTripDefectOut(PreTripDefectBase):
    id: int  # Defect identifier

    model_config = ConfigDict(from_attributes=True, extra="forbid")


# -----------------------------------------------------------
# - Pre-trip create payload
# -----------------------------------------------------------
class PreTripCreate(BaseModel):
    bus_id: int | None = None  # Forward-compatible bus identifier
    bus_number: str | None = Field(default=None, min_length=1)  # Legacy user-facing bus number
    license_plate: str = Field(min_length=1)  # Legacy reported bus plate
    driver_name: str = Field(min_length=1)  # Manual driver name entry
    inspection_date: dt_date  # Required inspection date
    inspection_time: dt_time  # Required inspection time
    odometer: int  # Reported odometer reading
    inspection_place: str = Field(min_length=1)  # Where the inspection occurred
    use_type: str  # school_bus or charter
    brakes_checked: bool  # Checklist audit field
    lights_checked: bool  # Checklist audit field
    tires_checked: bool  # Checklist audit field
    emergency_equipment_checked: bool  # Checklist audit field
    fit_for_duty: str  # yes or no
    no_defects: bool  # XOR flag against defect rows
    signature: str = Field(min_length=1)  # Captured signature value
    defects: list[PreTripDefectCreate] = Field(default_factory=list)  # Nested reported defect rows

    model_config = ConfigDict(extra="forbid")

    @field_validator("bus_number", "license_plate", "driver_name", "inspection_place", "signature")
    @classmethod
    def validate_required_strings(cls, value: str | None, info) -> str | None:
        if value is None and info.field_name == "bus_number":
            return value
        return _normalize_required_string(value, info.field_name)

    @field_validator("use_type")
    @classmethod
    def validate_use_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_USE_TYPES:
            raise ValueError("use_type must be school_bus or charter")
        return normalized

    @field_validator("fit_for_duty")
    @classmethod
    def validate_fit_for_duty(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in VALID_FIT_FOR_DUTY:
            raise ValueError("fit_for_duty must be yes or no")
        return normalized

    @model_validator(mode="after")
    def validate_defect_xor_rules(self) -> PreTripCreate:
        if self.bus_id is None and not self.bus_number:
            raise ValueError("bus_id or bus_number is required")
        if self.no_defects and self.defects:
            raise ValueError("defects must be empty when no_defects is true")
        if not self.no_defects and not self.defects:
            raise ValueError("at least one defect is required when no_defects is false")
        return self


# -----------------------------------------------------------
# - Pre-trip correction payload
# -----------------------------------------------------------
class PreTripCorrect(PreTripCreate):
    corrected_by: str = Field(min_length=1)  # Dispatch/operator making the correction

    @field_validator("corrected_by")
    @classmethod
    def validate_corrected_by(cls, value: str) -> str:
        return _normalize_required_string(value, "corrected_by")


# -----------------------------------------------------------
# - Pre-trip response payload
# -----------------------------------------------------------
class PreTripOut(BaseModel):
    id: int  # Inspection identifier
    bus_id: int  # Linked bus identifier
    bus_number: str | None = None  # Legacy user-facing bus number
    license_plate: str  # Legacy reported bus plate
    driver_name: str  # Manual driver name entry
    inspection_date: dt_date  # Inspection date
    inspection_time: dt_time  # Inspection time
    odometer: int  # Reported odometer reading
    inspection_place: str  # Inspection location
    use_type: str  # school_bus or charter
    brakes_checked: bool  # Checklist audit field
    lights_checked: bool  # Checklist audit field
    tires_checked: bool  # Checklist audit field
    emergency_equipment_checked: bool  # Checklist audit field
    fit_for_duty: str  # yes or no
    no_defects: bool  # Defect-free flag
    signature: str  # Captured signature value
    is_corrected: bool  # Future correction flag
    corrected_by: str | None = None  # Future correction actor
    corrected_at: datetime | None = None  # Future correction timestamp
    original_payload: Any = None  # Future audit snapshot
    created_at: datetime  # Record creation timestamp
    updated_at: datetime  # Record update timestamp
    defects: list[PreTripDefectOut] = Field(default_factory=list)  # Nested reported defects

    model_config = ConfigDict(from_attributes=True, extra="forbid")
