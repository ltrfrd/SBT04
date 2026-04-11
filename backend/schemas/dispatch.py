# ===========================================================
# backend/schemas/dispatch.py — BST Dispatch Schemas
# -----------------------------------------------------------
# Handles dispatch workdays and charter time input.
# ===========================================================
from datetime import date, time
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------
# DispatchCreate
# - Create or update a dispatch-backed work entry
# -----------------------------------------------------------
class DispatchCreate(BaseModel):
    driver_id: int  # FK: driver submitting
    work_date: date = Field(
        ...,
        description="Date in YYYY-MM-DD format (e.g. 2026-03-23)",
        json_schema_extra={"example": "2026-03-23"},
    )  # Workday date
    charter_start: Optional[time] = None  # Charter start time
    charter_end: Optional[time] = None  # Charter end time
    approved: Optional[bool] = False  # Default not verified


# -----------------------------------------------------------
# DispatchOut
# - Return dispatch work entry data
# -----------------------------------------------------------
class DispatchOut(BaseModel):
    id: int
    driver_id: int
    work_date: date
    charter_start: Optional[time] = None
    charter_end: Optional[time] = None
    charter_hours: Decimal
    approved: bool

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
