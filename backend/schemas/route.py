# ===========================================================
# backend/schemas/route.py - BST Route Schemas
# -----------------------------------------------------------
# Pydantic models for route summary and detail responses.
# ===========================================================

from datetime import datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# -----------------------------------------------------------
# Driver assignment payload
# - active means current operational assignment
# -----------------------------------------------------------
class RouteDriverAssignmentBase(BaseModel):
    active: bool = True


# -----------------------------------------------------------
# Driver assignment create schema
# -----------------------------------------------------------
class RouteDriverAssignmentCreate(RouteDriverAssignmentBase):
    pass


# -----------------------------------------------------------
# Driver assignment output schema
# - is_primary means default/base route owner
# -----------------------------------------------------------
class RouteDriverAssignmentOut(RouteDriverAssignmentBase):
    id: int
    route_id: int
    driver_id: int
    driver_name: Optional[str] = None
    is_primary: bool = False

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# Schema for creating a new route (POST request)
# - Route creation is vehicle-agnostic in the user-facing workflow
# - Bus assignment happens later through the separate route-bus flow
# -----------------------------------------------------------
class RouteCreate(BaseModel):
    route_number: str = Field(
        ...,
        description="Required public route identifier used during normal route creation.",
    )
    school_ids: Optional[List[int]] = []

    model_config = ConfigDict(extra="forbid")

    # -----------------------------------------------------------
    # Route number normalization
    # Keep visible route identity trimmed and predictable
    # -----------------------------------------------------------
    @field_validator("route_number")
    @classmethod
    def normalize_route_number(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("route_number is required")
        return normalized


# -----------------------------------------------------------
# Route summary response
# - Lightweight route list item for navigation and selection
# -----------------------------------------------------------
class RouteOut(BaseModel):
    id: int
    route_number: str
    bus_id: Optional[int] = None
    school_ids: Optional[List[int]] = None
    school_names: List[str] = []
    schools_count: int = 0
    active_driver_id: Optional[int] = None  # Current operational driver id
    active_driver_name: Optional[str] = None  # Current operational driver name
    primary_driver_id: Optional[int] = None  # Default/base route-owner driver id
    primary_driver_name: Optional[str] = None  # Default/base route-owner driver name
    runs_count: int = 0
    active_runs_count: int = 0
    total_stops_count: int = 0
    total_students_count: int = 0

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------
# Route detail school response
# - School rows nested under one route detail response
# -----------------------------------------------------------
class RouteSchoolOut(BaseModel):
    school_id: int
    school_name: str


# -----------------------------------------------------------
# Route detail stop response
# - Stop rows nested under one run in route detail output
# -----------------------------------------------------------
class RouteDetailStopOut(BaseModel):
    stop_id: int
    sequence: int
    type: str
    name: str | None = None
    school_id: int | None = None
    address: str | None = None
    planned_time: time | None = None
    student_count: int = 0


# -----------------------------------------------------------
# Route detail student response
# - Runtime student assignment rows nested under one run
# -----------------------------------------------------------
class RouteDetailStudentOut(BaseModel):
    student_id: int
    student_name: str
    school_id: int | None = None
    school_name: str | None = None
    stop_id: int | None = None
    stop_sequence: int | None = None
    stop_name: str | None = None


# -----------------------------------------------------------
# Route detail run response
# - Full nested run details for one selected route
# -----------------------------------------------------------
class RouteDetailRunOut(BaseModel):
    run_id: int
    run_type: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    driver_id: int | None = None
    driver_name: str | None = None
    is_planned: bool
    is_active: bool
    is_completed: bool
    stops: List[RouteDetailStopOut] = []
    students: List[RouteDetailStudentOut] = []


# -----------------------------------------------------------
# Route detail response
# - Full nested route payload for one selected route
# -----------------------------------------------------------
class RouteDetailOut(BaseModel):
    id: int
    route_number: str
    bus_id: Optional[int] = None
    schools: List[RouteSchoolOut] = []
    active_driver_id: int | None = None  # Current operational driver id
    active_driver_name: str | None = None  # Current operational driver name
    primary_driver_id: int | None = None  # Default/base route-owner driver id
    primary_driver_name: str | None = None  # Default/base route-owner driver name
    driver_assignments: List[RouteDriverAssignmentOut] = []
    runs: List[RouteDetailRunOut] = []

    model_config = ConfigDict(from_attributes=True)
