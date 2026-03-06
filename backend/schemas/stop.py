# ===========================================================
# backend/schemas/stop.py — SBT Stop Schemas
# -----------------------------------------------------------
# Pydantic models for Stop creation and output responses.
# Stops are identified primarily by sequence number.
# ===========================================================

from pydantic import BaseModel, ConfigDict
from enum import Enum

from typing import Optional  # Allow optional sequence


# -----------------------------------------------------------
# Stop type enum: pickup or dropoff
# -----------------------------------------------------------
class StopType(str, Enum):
    PICKUP = "pickup"
    DROPOFF = "dropoff"


# -----------------------------------------------------------
# Schema for creating a stop (POST request)
# -----------------------------------------------------------
class StopCreate(BaseModel):                                   # Create schema
    route_id: int                                              # Required route id
    type: str                                                  # Required ("pickup" or "dropoff")
    sequence: Optional[int] = None                             # Optional; backend can auto-set

    name: Optional[str] = None                                 # Optional stop name
    address: Optional[str] = None                              # Optional address

    latitude: Optional[float] = None                           # Optional latitude
    longitude: Optional[float] = None                          # Optional longitude


class StopUpdate(BaseModel):  # Partial update schema for Stop
    sequence: int | None = None  # Optional stop order update
    type: StopType | None = None  # Optional stop type update
    route_id: int | None = None  # Optional route reassignment (usually not used)

    name: str | None = None  # Optional label update
    address: str | None = None  # Optional address update
    latitude: float | None = None  # Optional latitude update (dragging pin)
    longitude: float | None = None  # Optional longitude update (dragging pin)


# -----------------------------------------------------------
# Schema for returning stop data (GET response)
# -----------------------------------------------------------
class StopOut(BaseModel):
    id: int  # Auto-generated unique ID
    sequence: int  # Stop number on the route
    type: StopType  # pickup/dropoff
    route_id: int  # Linked route ID
    name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# Schema for reordering a stop
# -----------------------------------------------------------
class StopReorder(BaseModel):  # Input model
    new_sequence: int  # Target sequence position
