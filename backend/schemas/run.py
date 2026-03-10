# ============================================================
# Run request and response schemas for BusTrack
# ============================================================

# -----------------------------
# Imports
# -----------------------------
from datetime import datetime, time  # Datetime types used in API schemas
from enum import Enum  # Shared enum support
from typing import List, Optional  # Optional and collection typing

from pydantic import BaseModel, ConfigDict  # Pydantic schema helpers


# -----------------------------
# Router / Model / Schema
# -----------------------------
class RunType(str, Enum):
    AM = "AM"  # Morning run type
    MIDDAY = "MIDDAY"  # Midday run type
    PM = "PM"  # Afternoon run type
    EXTRA = "EXTRA"  # Extra run type


# -----------------------------
# Logic
# -----------------------------
class RunStart(BaseModel):
    driver_id: int  # Driver starting the run
    route_id: int  # Route being run
    run_type: RunType  # AM / MIDDAY / PM / EXTRA


class RunOut(BaseModel):
    id: int  # Run identifier
    driver_id: int  # Assigned driver ID
    route_id: int  # Assigned route ID
    run_type: RunType  # Operational run type
    start_time: datetime  # Run start timestamp
    end_time: Optional[datetime] = None  # Run end timestamp if completed
    current_stop_id: Optional[int] = None  # Current actual stop ID for the bus
    current_stop_sequence: Optional[int] = None  # Current actual stop sequence for the bus
    driver_name: Optional[str] = None  # Driver display name
    route_number: Optional[str] = None  # Route number for display
    model_config = ConfigDict(from_attributes=True)  # Enable ORM serialization


class RunningBoardStudent(BaseModel):
    student_id: int  # Unique student identifier
    student_name: str  # Student display name


class RunningBoardStop(BaseModel):
    stop_id: int  # Stop database ID
    sequence: int  # Stop order within the run
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
    driver_id: int  # Driver ID
    driver_name: str | None  # Driver display name
    route_id: int  # Route ID
    route_number: str | None  # Route number
    run_type: RunType  # Run type
    start_time: datetime  # Run start timestamp
    end_time: datetime | None  # Run end timestamp
    status: str  # active / ended
    total_stops: int  # Number of stops in the run
    total_assigned_students: int  # Number of assigned riders
    current_load: int  # Current cumulative load based on assignments
    model_config = ConfigDict(from_attributes=True)  # Enable ORM serialization


class RunProgressOut(BaseModel):
    run_id: int  # Current run ID
    route_id: int  # Parent route ID
    route_number: Optional[str] = None  # Route number for display
    run_type: RunType  # AM / PM / etc.
    total_stops: int  # Total number of stops in run
    current_stop_index: int  # 1-based current stop position
    remaining_stops: int  # Stops remaining including current
    current_stop_id: Optional[int] = None  # Current stop database ID
    current_stop_name: Optional[str] = None  # Current stop display name
    current_stop_sequence: Optional[int] = None  # Current stop sequence number
    current_stop_planned_time: Optional[time] = None  # Planned time for current stop
    next_stop_id: Optional[int] = None  # Next stop database ID
    next_stop_name: Optional[str] = None  # Next stop display name
    next_stop_sequence: Optional[int] = None  # Next stop sequence number
    next_stop_planned_time: Optional[time] = None  # Planned time for next stop
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
