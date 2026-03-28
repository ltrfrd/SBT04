# ===========================================================
# backend/schemas/student.py — SBT Student Schemas
# -----------------------------------------------------------
# Pydantic models for Student creation and output responses.
# ===========================================================

from pydantic import AliasPath, BaseModel, ConfigDict, Field
from typing import Optional


# -----------------------------------------------------------
# Base schema (shared by create and response models)
# -----------------------------------------------------------
class StudentBase(BaseModel):
    """Common fields shared by StudentCreate and StudentOut."""

    name: str  # Student full name
    grade: Optional[str] = None  # Optional grade (e.g., "5th")
    school_id: int  # FK: school ID this student belongs to
    route_id: Optional[int] = None  # Optional assigned route
    stop_id: Optional[int] = None  # Optional assigned stop


# -----------------------------------------------------------
# Schema for creating a student (POST request)
# -----------------------------------------------------------
class StudentCreate(StudentBase):
    """Used when adding a new student."""

    pass


# -----------------------------------------------------------
# Schema for returning student data (GET response)
# -----------------------------------------------------------
class StudentOut(StudentBase):
    """Returned in API responses."""

    id: int  # Auto-generated unique ID
    school_code: Optional[str] = Field(default=None, validation_alias=AliasPath("school", "school_code"))

    model_config = ConfigDict(from_attributes=True)  # ORM to schema conversion
