# ===========================================================
# backend/schemas/driver.py - FleetOS Driver Schemas
# -----------------------------------------------------------
# Defines the Pydantic models for driver requests and responses.
# ===========================================================

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator  # Pydantic types for validation
from typing import Optional


# -----------------------------------------------------------
# Shared base schema
# -----------------------------------------------------------
class DriverBase(BaseModel):
    """Common fields shared by create and response models."""

    name: str  # Driver's full name
    email: EmailStr  # Valid email address
    phone: Optional[str] = None  # Optional phone number


# -----------------------------------------------------------
# Schema for driver creation (POST request)
# -----------------------------------------------------------
class DriverCreate(DriverBase):
    """Schema used when creating a new driver."""

    yard_id: int
    pin: str

    @field_validator("pin")
    @classmethod
    def normalize_pin(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("pin is required")
        return normalized


class DriverUpdate(BaseModel):
    """Fields allowed to be updated (all optional)."""

    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    pin: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("pin")
    @classmethod
    def normalize_optional_pin(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        normalized = value.strip()
        if not normalized:
            raise ValueError("pin is required")
        return normalized


# -----------------------------------------------------------
# Schema for reading driver data (GET response)
# -----------------------------------------------------------
class DriverOut(DriverBase):
    """Schema returned in responses."""

    id: int  # Auto-generated unique ID

    # Pydantic v2 configuration: allows ORM model conversion
    model_config = ConfigDict(from_attributes=True)
