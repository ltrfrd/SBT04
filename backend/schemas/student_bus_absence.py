# -----------------------------------------------------------
# Student Bus Absence Schemas
# - Validate planned no-ride create and response payloads
# -----------------------------------------------------------
from datetime import date as dt_date, datetime # Date and timestamp types

from pydantic import BaseModel, ConfigDict, Field  # Pydantic schema helpers

from backend.models.student_bus_absence import StudentBusAbsenceSource  # Shared absence source enum


class StudentBusAbsenceCreate(BaseModel):
    date: dt_date = Field(
        ...,
        description="Date in YYYY-MM-DD format (e.g. 2026-03-23)",
        json_schema_extra={"example": "2026-03-23"},
    )  # Planned no-ride date
    run_type: str = Field(min_length=1)  # Flexible run label
    source: StudentBusAbsenceSource = StudentBusAbsenceSource.PARENT  # Defaults to parent-reported absence


class StudentBusAbsenceOut(BaseModel):
    id: int  # Absence identifier
    student_id: int  # Student receiving the planned absence
    date: dt_date  # Planned no-ride date
    run_type: str  # Flexible run label
    source: StudentBusAbsenceSource  # Reporting source
    created_at: datetime  # Record creation timestamp

    model_config = ConfigDict(from_attributes=True)  # Enable ORM serialization
