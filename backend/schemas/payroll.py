# ===========================================================
# backend/schemas/payroll.py — BST Payroll Schemas
# -----------------------------------------------------------
# Handles workdays + charter time input and verification.
# ===========================================================
from pydantic import BaseModel, ConfigDict
from datetime import date, time
from decimal import Decimal
from typing import Optional


# -----------------------------------------------------------
# Schema for creating or updating payroll entry
# -----------------------------------------------------------
class PayrollCreate(BaseModel):
    driver_id: int  # FK: driver submitting
    work_date: date  # Workday date
    charter_start: Optional[time] = None  # Charter start time
    charter_end: Optional[time] = None  # Charter end time
    approved: Optional[bool] = False  # Default not verified


# -----------------------------------------------------------
# Schema for returning payroll summary
# -----------------------------------------------------------
class PayrollOut(BaseModel):
    id: int
    driver_id: int
    work_date: date
    charter_start: Optional[time] = None
    charter_end: Optional[time] = None
    charter_hours: Decimal
    approved: bool

    model_config = ConfigDict(from_attributes=True)
