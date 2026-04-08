# ============================================================
# Run request and response schemas for SBT
# ============================================================

# -----------------------------
# Imports
# -----------------------------
from datetime import datetime, time  # Datetime types used in API schemas
from typing import List, Optional  # Optional and collection typing

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator  # Pydantic schema helpers


# -----------------------------------------------------------
# Run label normalization helpers
# Keep run_type flexible but consistently stored
# -----------------------------------------------------------
RUN_TYPE_PATTERN = re.compile(r"^[A-Z0-9]+(?:[ -][A-Z0-9]+)*$")


def normalize_run_type(value: str) -> str:
    normalized = " ".join(value.strip().upper().split())
    if not normalized:
        raise ValueError("run_type is required")
    if not RUN_TYPE_PATTERN.fullmatch(normalized):
        raise ValueError("run_type may contain only letters, numbers, spaces, and hyphens")
    return normalized


# -----------------------------
# Logic
# -----------------------------
class RunCreateLegacy(BaseModel):
    route_id: int  # Route being run
    run_type: str = Field(min_length=1)  # Flexible run label
    scheduled_start_time: time  # Fixed planned start time
    scheduled_end_time: time  # Fixed planned end time

    model_config = ConfigDict(extra="forbid")

    @field_validator("run_type")
    @classmethod
    def validate_run_type(cls, value: str) -> str:
        return normalize_run_type(value)


class RouteRunCreate(BaseModel):
    run_type: str = Field(min_length=1)  # Flexible run label within selected route
    scheduled_start_time: time  # Fixed planned start time
    scheduled_end_time: time  # Fixed planned end time

    model_config = ConfigDict(extra="forbid")

    @field_validator("run_type")
    @classmethod
    def validate_run_type(cls, value: str) -> str:
        return normalize_run_type(value)


class RunUpdate(BaseModel):
    run_type: str = Field(min_length=1)  # Updated flexible run label
    scheduled_start_time: time | None = None  # Updated planned start time while still planned
    scheduled_end_time: time | None = None  # Updated planned end time while still planned

    model_config = ConfigDict(extra="forbid")

    @field_validator("run_type")
    @classmethod
    def validate_run_type(cls, value: str) -> str:
        return normalize_run_type(value)


class RunOut(BaseModel):
    id: int  # Run identifier
    driver_id: Optional[int] = None  # Assigned driver ID when resolved
    route_id: int  # Assigned route ID
    run_type: str  # Operational run label
    scheduled_start_time: time  # Fixed planned start time
    scheduled_end_time: time  # Fixed planned end time
    start_time: Optional[datetime] = None  # Run start timestamp when the run has started
    end_time: Optional[datetime] = None  # Run end timestamp if completed
    current_stop_id: Optional[int] = None  # Current actual stop ID for the bus
    current_stop_sequence: Optional[int] = None  # Current actual stop sequence for the bus
    driver_name: Optional[str] = None  # Driver display name
    route_number: Optional[str] = None  # Route number for display
    model_config = ConfigDict(from_attributes=True)  # Enable ORM serialization


class RunListOut(BaseModel):
    run_id: int
    run_type: str
    scheduled_start_time: time
    scheduled_end_time: time
    start_time: datetime | None = None
    end_time: datetime | None = None
    driver_id: int | None = None
    driver_name: str | None = None
    is_planned: bool
    is_active: bool
    is_completed: bool
    stops_count: int
    students_count: int


class RunDetailRouteOut(BaseModel):
    route_id: int
    route_number: str | None = None


class RunDetailDriverOut(BaseModel):
    driver_id: int | None = None
    driver_name: str | None = None


class RunDetailStopOut(BaseModel):
    stop_id: int
    sequence: int
    type: str
    name: str | None = None
    school_id: int | None = None
    address: str | None = None
    planned_time: str | None = None


class RunDetailStudentOut(BaseModel):
    student_id: int
    student_name: str
    school_id: int | None = None
    school_name: str | None = None
    stop_id: int | None = None
    stop_sequence: int | None = None
    stop_name: str | None = None


class RunDetailOut(BaseModel):
    id: int
    driver_id: int | None = None
    route_id: int
    run_type: str
    scheduled_start_time: time
    scheduled_end_time: time
    start_time: datetime | None = None
    end_time: datetime | None = None
    current_stop_id: int | None = None
    current_stop_sequence: int | None = None
    driver_name: str | None = None
    route_number: str | None = None
    route: RunDetailRouteOut
    driver: RunDetailDriverOut
    stops: list[RunDetailStopOut] = []
    students: list[RunDetailStudentOut] = []


class RunningBoardStudent(BaseModel):
    student_id: int  # Unique student identifier
    student_name: str  # Student display name


class RunningBoardStop(BaseModel):
    stop_id: int  # Stop database ID
    sequence: int  # Stop order within the run
    stop_type: str
    is_school_stop: bool
    display_name: str
    planned_time: str | None  # Planned arrival time if available
    lat: float | None  # Stop latitude
    lng: float | None  # Stop longitude
    student_count_at_stop: int  # Number of students assigned to this stop
    load_change: int  # Boarding change at this stop
    cumulative_load: int  # Total students on bus after this stop
    students: List[RunningBoardStudent]  # Students assigned to this stop


class RunningBoardResponse(BaseModel):
    run_id: int  # Run identifier
    route_id: int | None  # Parent route ID
    run_name: str | None  # Run name or label
    total_stops: int  # Number of stops in the run
    total_assigned_students: int  # Total riders for the run
    stops: List[RunningBoardStop]  # Ordered stop list


class RunSummaryOut(BaseModel):
    run_id: int  # Run identifier
    driver_id: int | None  # Driver ID when assigned
    driver_name: str | None  # Driver display name
    route_id: int  # Route ID
    route_number: str | None  # Route number
    run_type: str  # Run label
    scheduled_start_time: time  # Fixed planned start time
    scheduled_end_time: time  # Fixed planned end time
    start_time: datetime | None  # Run start timestamp when started
    end_time: datetime | None  # Run end timestamp
    status: str  # planned / active / ended
    total_stops: int  # Number of stops in the run
    total_assigned_students: int  # Number of assigned riders
    current_load: int  # Current cumulative load based on assignments
    model_config = ConfigDict(from_attributes=True)  # Enable ORM serialization


class PickupStudentRequest(BaseModel):
    student_id: int  # ID of the student being picked up


class PickupStudentResponse(BaseModel):
    message: str  # Human-readable confirmation message
    run_id: int  # Run where pickup occurred
    student_id: int  # Student that was picked up
    picked_up: bool  # Confirms pickup flag was set
    is_onboard: bool  # Indicates the student is now on the bus
    picked_up_at: datetime  # Timestamp when pickup occurred


class DropoffStudentRequest(BaseModel):
    student_id: int  # ID of the student being dropped off


class DropoffStudentResponse(BaseModel):
    message: str  # Human-readable confirmation
    run_id: int  # Run where drop-off occurred
    student_id: int  # Student that was dropped off
    dropped_off: bool  # Confirms drop-off flag was set
    is_onboard: bool  # Should now be False
    dropped_off_at: datetime  # Timestamp when drop-off occurred


class OnboardStudentItem(BaseModel):
    student_id: int  # Student ID
    student_name: str  # Student name
    stop_id: int  # Assigned stop ID
    stop_name: str  # Assigned stop name
    stop_sequence: int  # Assigned stop order in the run
    picked_up_at: datetime | None = None  # Time student was picked up


class OnboardStudentsResponse(BaseModel):
    run_id: int  # Run being checked
    total_onboard_students: int  # Count of onboard students
    students: list[OnboardStudentItem]  # Students currently onboard


class RunOccupancySummaryResponse(BaseModel):
    run_id: int  # ID of the run
    route_id: int  # Route associated with the run
    run_type: str  # AM / PM / Charter etc.
    total_assigned_students: int  # All runtime student assignments for this run
    total_picked_up: int  # Students picked up at least once
    total_dropped_off: int  # Students dropped off
    total_currently_onboard: int  # Students currently on the bus
    total_not_yet_boarded: int  # Assigned students who have not been picked up yet


# -----------------------------------------------------------
# Run state snapshot output
# - Current operational view without exposing raw event history
# -----------------------------------------------------------
class RunStateOut(BaseModel):
    run_id: int  # Current run ID
    route_id: int  # Parent route ID
    driver_id: int | None  # Assigned driver ID when available
    run_type: str  # Flexible run label
    current_stop_id: int | None = None  # Latest known bus location stop ID
    current_stop_sequence: int | None = None  # Latest known bus location sequence
    current_stop_name: str | None = None  # Latest known bus location name
    total_stops: int  # Stops configured on the run
    completed_stops: int  # Distinct stops with at least one ARRIVE event
    remaining_stops: int  # Stops not yet arrived at, never below zero
    progress_percent: float  # Distinct arrived stops / total stops
    total_assigned_students: int  # Runtime assignments on the run
    picked_up_students: int  # Students picked up at least once
    dropped_off_students: int  # Students dropped off
    students_onboard: int  # Students currently onboard
    remaining_pickups: int  # Assigned students not yet picked up
    remaining_dropoffs: int  # Students picked up but not yet dropped off

# -----------------------------------------------------------
# Run Completion Output
# - Returned when a run is marked complete
# -----------------------------------------------------------

class RunCompleteOut(BaseModel):
    id: int
    is_completed: bool
    completed_at: datetime | None = None
    message: str

# -----------------------------------------------------------
# Run timeline event output
# - One row per logged ARRIVE / PICKUP / DROPOFF event
# -----------------------------------------------------------
class RunEventOut(BaseModel):
    id: int                                        # Event ID
    run_id: int                                    # Parent run
    stop_id: int | None = None                     # Stop involved in the event
    student_id: int | None = None                  # Student involved in the event
    event_type: str                                # ARRIVE | PICKUP | DROPOFF
    timestamp: datetime                            # Event timestamp

    model_config = ConfigDict(from_attributes=True) # Enable ORM -> schema conversion


# -----------------------------------------------------------
# Run timeline response
# - Ordered event list for a single run
# -----------------------------------------------------------
class RunTimelineOut(BaseModel):
    run_id: int                                                          # Parent run
    total_events: int                                                    # Number of timeline events
    events: list[RunEventOut]                                            # Ordered event rows

 # -----------------------------------------------------------
# Run Replay Output Schemas
# - Human-readable replay entries for admin/debug/report use
# -----------------------------------------------------------

class RunReplayEventOut(BaseModel):
    id: int
    event_type: str
    timestamp: datetime

    stop_id: int | None = None
    stop_name: str | None = None

    student_id: int | None = None
    student_name: str | None = None

    onboard_count: int | None = None  # Bus occupancy after this event
    message: str  # Human-readable replay line


class RunReplaySummaryOut(BaseModel):
    total_events: int
    total_arrivals: int
    total_pickups: int
    total_dropoffs: int


class RunReplayOut(BaseModel):
    run_id: int
    events: list[RunReplayEventOut]
    summary: RunReplaySummaryOut   
