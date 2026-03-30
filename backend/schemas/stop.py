# ===========================================================
# backend/schemas/stop.py - BST Stop Schemas
# -----------------------------------------------------------
# Pydantic models for stop requests and responses.
# ===========================================================
from pydantic import BaseModel, ConfigDict, field_validator
from enum import Enum
from typing import Optional
from datetime import time


# -----------------------------------------------------------
# - Stop type helpers
# - Normalize flexible stop type input into canonical enum values
# -----------------------------------------------------------
class StopType(str, Enum):
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"
    SCHOOL_ARRIVE = "SCHOOL_ARRIVE"
    SCHOOL_DEPART = "SCHOOL_DEPART"


def _normalize_stop_type(value: str | StopType | None) -> str | StopType | None:
    if value is None or isinstance(value, StopType):
        return value

    if not isinstance(value, str):
        return value

    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    normalized = "_".join(part for part in normalized.split("_") if part)
    compact = normalized.replace("_", "")

    if compact == StopType.PICKUP.value:
        return StopType.PICKUP
    if compact == StopType.DROPOFF.value:
        return StopType.DROPOFF
    if compact == StopType.SCHOOL_ARRIVE.value.replace("_", ""):
        return StopType.SCHOOL_ARRIVE
    if compact == StopType.SCHOOL_DEPART.value.replace("_", ""):
        return StopType.SCHOOL_DEPART

    raise ValueError("Stop type must be pickup, dropoff, school_arrive, or school_depart")


class StopCreate(BaseModel):
    run_id: int
    type: StopType
    sequence: Optional[int] = None
    name: Optional[str] = None
    school_id: Optional[int] = None
    address: Optional[str] = None
    planned_time: Optional[time] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return _normalize_stop_type(value)


class StopUpdate(BaseModel):
    sequence: int | None = None
    type: StopType | None = None
    run_id: int | None = None
    name: str | None = None
    school_id: int | None = None
    address: str | None = None
    planned_time: time | None = None
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return _normalize_stop_type(value)


class StopOut(BaseModel):
    id: int
    sequence: int
    type: StopType
    run_id: int
    name: str | None = None
    school_id: int | None = None
    address: str | None = None
    planned_time: time | None = None
    latitude: float | None = None
    longitude: float | None = None

    model_config = ConfigDict(from_attributes=True)


class RunStopCreate(BaseModel):
    type: StopType
    sequence: Optional[int] = None
    name: Optional[str] = None
    school_id: Optional[int] = None
    address: Optional[str] = None
    planned_time: Optional[time] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return _normalize_stop_type(value)


class StopReorder(BaseModel):
    new_sequence: int
