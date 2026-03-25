# ===========================================================
# backend/schemas/route.py - BST Route Schemas
# ===========================================================

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# -----------------------------------------------------------
# Driver assignment payload
# -----------------------------------------------------------
class RouteDriverAssignmentBase(BaseModel):
    is_primary: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    active: bool = True


# -----------------------------------------------------------
# Driver assignment create schema
# -----------------------------------------------------------
class RouteDriverAssignmentCreate(RouteDriverAssignmentBase):
    pass


# -----------------------------------------------------------
# Driver assignment output schema
# -----------------------------------------------------------
class RouteDriverAssignmentOut(RouteDriverAssignmentBase):
    id: int
    route_id: int
    driver_id: int
    driver_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# Schema for creating a new route (POST request)
# -----------------------------------------------------------
class RouteCreate(BaseModel):
    route_number: str
    unit_number: str
    school_ids: Optional[List[int]] = []

    model_config = ConfigDict(extra="forbid")


# -----------------------------------------------------------
# Schema for reading route data (GET / Response)
# -----------------------------------------------------------
class RouteOut(BaseModel):
    id: int
    route_number: str
    unit_number: Optional[str] = None
    school_ids: Optional[List[int]] = None
    active_driver_id: Optional[int] = None
    active_driver_name: Optional[str] = None
    driver_assignments: List[RouteDriverAssignmentOut] = []

    model_config = ConfigDict(from_attributes=True)
