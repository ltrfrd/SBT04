# ===========================================================
# backend/schemas/bus.py - SBT Bus Schemas
# -----------------------------------------------------------
# Defines the Pydantic models for bus requests and responses.
# ===========================================================

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from backend.schemas.route import RouteDetailOut


# -----------------------------------------------------------
# Shared base schema
# -----------------------------------------------------------
class BusBase(BaseModel):
    unit_number: str
    license_plate: str
    capacity: int
    size: str

    # -----------------------------------------------------------
    # Shared string normalization
    # Keep visible bus identifiers trimmed and predictable
    # -----------------------------------------------------------
    @field_validator("unit_number", "license_plate", "size")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field is required")
        return normalized

    # -----------------------------------------------------------
    # Capacity validation
    # Keep bus capacity practical and positive
    # -----------------------------------------------------------
    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("capacity must be greater than 0")
        return value


# -----------------------------------------------------------
# Schema for bus creation (POST request)
# -----------------------------------------------------------
class BusCreate(BusBase):
    model_config = ConfigDict(extra="forbid")


# -----------------------------------------------------------
# Schema for bus updates (PUT request)
# -----------------------------------------------------------
class BusUpdate(BaseModel):
    unit_number: Optional[str] = None
    license_plate: Optional[str] = None
    capacity: Optional[int] = None
    size: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("unit_number", "license_plate", "size")
    @classmethod
    def normalize_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        normalized = value.strip()
        if not normalized:
            raise ValueError("field is required")
        return normalized

    @field_validator("capacity")
    @classmethod
    def validate_optional_capacity(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("capacity must be greater than 0")
        return value


# -----------------------------------------------------------
# Schema for reading bus data (GET response)
# -----------------------------------------------------------
class BusOut(BusBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# Schema for rich bus detail (GET response)
# -----------------------------------------------------------
class BusDetailOut(BusOut):
    assigned_routes: List[RouteDetailOut] = []
