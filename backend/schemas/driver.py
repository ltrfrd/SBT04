# ===========================================================
# backend/schemas/driver.py — SBT Driver Schemas
# -----------------------------------------------------------
# Defines the Pydantic models for driver requests and responses.
# ===========================================================

from pydantic import BaseModel, ConfigDict, EmailStr  # Pydantic types for validation
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

    pass  # No extra fields needed beyond base fields


class DriverUpdate(BaseModel):
    """Fields allowed to be updated (all optional)."""

    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# Schema for reading driver data (GET response)
# -----------------------------------------------------------
class DriverOut(DriverBase):
    """Schema returned in responses."""

    id: int  # Auto-generated unique ID

    # Pydantic v2 configuration: allows ORM model conversion
    model_config = ConfigDict(from_attributes=True)
