# ===========================================================
# backend/schemas/route.py — BST Route Schemas
# ===========================================================

from pydantic import BaseModel, ConfigDict
from typing import List, Optional


# -----------------------------------------------------------
# Schema for creating a new route (POST request)
# -----------------------------------------------------------
class RouteCreate(BaseModel):
    route_number: str
    unit_number: str
    driver_id: int
    school_ids: Optional[List[int]] = []  # optional list of assigned schools


# -----------------------------------------------------------
# Schema for reading route data (GET / Response)
# -----------------------------------------------------------
class RouteOut(BaseModel):
    id: int
    route_number: str
    unit_number: Optional[str] = None
    driver_id: Optional[int] = None
    school_ids: Optional[List[int]] = None

    model_config = ConfigDict(from_attributes=True)
