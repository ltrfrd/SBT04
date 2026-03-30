# ===========================================================
# backend/schemas/student.py — SBT Student Schemas
# -----------------------------------------------------------
# Pydantic models for Student creation and output responses.
# ===========================================================
from pydantic import BaseModel, ConfigDict
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
# - Student update schemas
# - Keep generic and stop-context update payloads explicit
# -----------------------------------------------------------
class StudentUpdate(BaseModel):
    name: Optional[str] = None
    grade: Optional[str] = None
    school_id: Optional[int] = None
    route_id: Optional[int] = None
    stop_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


# -----------------------------------------------------------
# Schema for returning student data (GET response)
# -----------------------------------------------------------
class StudentOut(StudentBase):
    """Returned in API responses."""

    id: int  # Auto-generated unique ID
    school_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)  # ORM to schema conversion


# -----------------------------------------------------------
# Stop-context student create schemas
# - Keep route/run assignment details internal to workflow helpers
# -----------------------------------------------------------
class StopStudentCreate(BaseModel):
    name: str
    grade: Optional[str] = None
    school_id: int

    model_config = ConfigDict(extra="forbid")


class StopStudentUpdate(BaseModel):
    name: Optional[str] = None
    grade: Optional[str] = None
    school_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


class StopStudentBulkCreate(BaseModel):
    students: list[StopStudentCreate]

    model_config = ConfigDict(extra="forbid")


class StopStudentBulkError(BaseModel):
    index: int
    name: Optional[str] = None
    detail: str


class StopStudentBulkResult(BaseModel):
    created_count: int
    skipped_count: int
    created_students: list[StudentOut] = []
    errors: list[StopStudentBulkError] = []
