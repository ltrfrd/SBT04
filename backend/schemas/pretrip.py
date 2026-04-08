# -----------------------------------------------------------
# Pre-Trip Schemas
# - Validate bus/day pre-trip payloads and nested defect rows
# -----------------------------------------------------------
from datetime import date as dt_date, datetime, time as dt_time  # Date and timestamp types

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator  # Pydantic schema helpers


VALID_USE_TYPES = {"school_bus", "charter"}  # Supported inspection use types
VALID_FIT_FOR_DUTY = {"yes", "no"}  # Supported duty declarations
VALID_DEFECT_SEVERITIES = {"minor", "major"}  # Supported defect severities


# -----------------------------------------------------------
# - Shared pre-trip defect fields
# - Normalize and validate one defect row
# -----------------------------------------------------------
class PreTripDefectBase(BaseModel):
    description: str = Field(min_length=1)  # Reported defect description
    severity: str  # minor or major

    model_config = ConfigDict(extra="forbid")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("description is required")
        return normalized

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

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# - Pre-trip create payload
# - Validate bus/day inspection header and XOR defect rules
# -----------------------------------------------------------
class PreTripCreate(BaseModel):
    bus_number: str = Field(min_length=1)  # User-facing bus number mapped to the stored bus record
    license_plate: str = Field(min_length=1)  # Reported bus plate captured on the form
    driver_name: str = Field(min_length=1)  # Manual driver name entry
    inspection_date: dt_date  # Required inspection date
    inspection_time: dt_time  # Required inspection time
    odometer: int  # Reported odometer reading
    inspection_place: str = Field(min_length=1)  # Where the inspection occurred
    use_type: str  # school_bus or charter
    fit_for_duty: str  # yes or no
    no_defects: bool  # XOR flag against defect rows
    signature: str = Field(min_length=1)  # Captured signature value
    defects: list[PreTripDefectCreate] = []  # Optional nested defect rows

    model_config = ConfigDict(extra="forbid")

    @field_validator("bus_number", "license_plate", "driver_name", "inspection_place", "signature")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field is required")
        return normalized

    @field_validator("odometer")
    @classmethod
    def validate_odometer(cls, value: int) -> int:
        if value < 0:
            raise ValueError("odometer must be greater than or equal to 0")
        return value

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
    def validate_defect_xor_rules(self) -> "PreTripCreate":
        if self.no_defects and self.defects:
            raise ValueError("no_defects=True cannot coexist with defect rows")

        if not self.no_defects and not self.defects:
            raise ValueError("no_defects=False requires at least one defect row")

        return self


# -----------------------------------------------------------
# - Pre-trip correction payload
# - Reuse create validation and capture correction actor
# -----------------------------------------------------------
class PreTripCorrect(PreTripCreate):
    corrected_by: str = Field(min_length=1)  # Dispatch/operator making the correction

    @field_validator("corrected_by")
    @classmethod
    def normalize_corrected_by(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("corrected_by is required")
        return normalized


# -----------------------------------------------------------
# - Pre-trip response payload
# - Return inspection data with nested defects and metadata
# -----------------------------------------------------------
class PreTripOut(BaseModel):
    id: int  # Inspection identifier
    bus_number: str  # User-facing bus number
    license_plate: str  # Reported bus plate captured on the form
    driver_name: str  # Manual driver name entry
    inspection_date: dt_date  # Inspection date
    inspection_time: dt_time  # Inspection time
    odometer: int  # Reported odometer reading
    inspection_place: str  # Inspection location
    use_type: str  # school_bus or charter
    fit_for_duty: str  # yes or no
    no_defects: bool  # Defect-free flag
    signature: str  # Captured signature value
    is_corrected: bool  # Future correction flag
    corrected_by: str | None = None  # Future correction actor
    corrected_at: datetime | None = None  # Future correction timestamp
    original_payload: dict | list | str | int | float | bool | None = None  # Future audit snapshot
    created_at: datetime  # Record creation timestamp
    updated_at: datetime  # Record update timestamp
    defects: list[PreTripDefectOut] = []  # Nested reported defects

    model_config = ConfigDict(from_attributes=True)
