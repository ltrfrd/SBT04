# ===========================================================
# backend/schemas/school.py — BST School Schemas
# -----------------------------------------------------------
# Pydantic models for School API requests and responses
# ===========================================================
from pydantic import BaseModel, ConfigDict
from typing import Optional


# -----------------------------------------------------------
# Shared base schema
# -----------------------------------------------------------
class SchoolBase(BaseModel):
    """Common fields shared by create and response models."""

    name: str
    address: Optional[str] = None
    phone: Optional[str] = None


# -----------------------------------------------------------
# Schema for school creation (POST request)
# -----------------------------------------------------------
class SchoolCreate(SchoolBase):
    """Schema used when creating a new school."""

    district_id: Optional[int] = None


# -----------------------------------------------------------
# Schema for reading school data (GET response)
# -----------------------------------------------------------
class SchoolOut(SchoolBase):
    """Schema returned in responses."""

    id: int

    model_config = ConfigDict(from_attributes=True)
