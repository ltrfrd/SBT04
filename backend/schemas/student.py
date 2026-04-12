# ===========================================================
# backend/schemas/student.py - FleetOS Student Schemas
# -----------------------------------------------------------
# Pydantic models for student compatibility and workflow APIs.
# ===========================================================
from pydantic import BaseModel, ConfigDict
from typing import Optional


# -----------------------------------------------------------
# - Shared student identity fields
# - Keep student-specific fields reusable across API layers
# -----------------------------------------------------------
class StudentIdentityFields(BaseModel):
    name: str  # Student full name
    grade: Optional[str] = None  # Optional grade (e.g., "5th")
    school_id: int  # FK: school ID this student belongs to

    model_config = ConfigDict(extra="forbid")


# -----------------------------------------------------------
# - Generic student create compatibility schema
# - Preserve legacy route/stop linkage fields only for /students/
# -----------------------------------------------------------
class StudentCompatibilityCreate(StudentIdentityFields):
    district_id: Optional[int] = None
    route_id: Optional[int] = None  # Optional legacy planning route pointer
    stop_id: Optional[int] = None  # Optional legacy planning stop pointer


# -----------------------------------------------------------
# - Backward-compatible student create alias
# - Keep existing imports stable while Swagger uses the clearer name
# -----------------------------------------------------------
class StudentCreate(StudentCompatibilityCreate):
    pass

# -----------------------------------------------------------
# - Student assignment update schema
# - Require explicit route, run, and stop targets
# -----------------------------------------------------------
class StudentAssignmentUpdate(BaseModel):
    route_id: int
    run_id: int
    stop_id: int

    model_config = ConfigDict(extra="forbid")

# -----------------------------------------------------------
# - Student response schema
# - Return the stored student with optional legacy planning pointers
# -----------------------------------------------------------
class StudentOut(StudentIdentityFields):
    id: int  # Auto-generated unique ID
    school_name: Optional[str] = None
    route_id: Optional[int] = None  # Optional legacy planning route pointer
    stop_id: Optional[int] = None  # Optional legacy planning stop pointer

    model_config = ConfigDict(from_attributes=True)  # ORM to schema conversion


# -----------------------------------------------------------
# - Stop-context student create schemas
# - Keep route/run assignment details internal to workflow helpers
# -----------------------------------------------------------
class StopStudentCreate(StudentIdentityFields):
    pass


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
