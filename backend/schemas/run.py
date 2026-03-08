# =============================================================================
# backend/schemas/run.py — Run Schemas
# -----------------------------------------------------------------------------
# Defines request and response schemas for:
#   - run creation / start
#   - run output
#   - running board output
#   - run summary output
# =============================================================================

from datetime import datetime, time  
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# =============================================================================
# Run Type Enum
# Must stay aligned with backend/models/run.py
# =============================================================================
class RunType(str, Enum):
    AM = "AM"
    MIDDAY = "MIDDAY"
    PM = "PM"
    EXTRA = "EXTRA"


# =============================================================================
# Run start / create input schema
# =============================================================================
class RunStart(BaseModel):
    driver_id: int                          # Driver starting the run
    route_id: int                           # Route being run
    run_type: RunType                       # AM / MIDDAY / PM / EXTRA


# =============================================================================
# Run output schema
# Returned by run endpoints
# =============================================================================
class RunOut(BaseModel):
    id: int
    driver_id: int
    route_id: int
    run_type: RunType
    start_time: datetime
    end_time: Optional[datetime] = None
    current_stop_sequence: Optional[int] = None  # Driver's current stop sequence in the run

    # -------------------------------------------------------------------------
    # Enriched display fields
    # -------------------------------------------------------------------------
    driver_name: Optional[str] = None       # Driver display name
    route_number: Optional[str] = None      # Route number (not route name)

    model_config = ConfigDict(from_attributes=True)
    

# =============================================================================
# Running Board Schemas
# These schemas define the structure returned by the Run Running Board API
# =============================================================================
class RunningBoardStudent(BaseModel):       # Represents a student assigned to a stop
    student_id: int                         # Unique student identifier
    student_name: str                       # Student display name


class RunningBoardStop(BaseModel):          # Represents a single stop row on the running board
    stop_id: int                            # Stop database ID
    sequence: int                           # Stop order within the run
    planned_time: str | None                # Planned arrival time (optional)
    lat: float | None                       # Stop latitude
    lng: float | None                       # Stop longitude

    student_count_at_stop: int              # Number of students assigned to this stop
    load_change: int                        # Boarding change at this stop
    cumulative_load: int                    # Total students on bus after this stop

    students: List[RunningBoardStudent]     # Students assigned to this stop


class RunningBoardResponse(BaseModel):      # Full response returned by the running board endpoint
    run_id: int                             # Run identifier
    route_id: int | None                    # Parent route ID
    run_name: str | None                    # Run name or label

    total_stops: int                        # Number of stops in the run
    total_assigned_students: int            # Total riders for the run

    stops: List[RunningBoardStop]           # Ordered stop list


# =============================================================================
# Run Summary Schema
# Compact operational summary for one run
# =============================================================================
class RunSummaryOut(BaseModel):
    run_id: int                             # Run identifier
    driver_id: int                          # Driver ID
    driver_name: str | None                 # Driver display name
    route_id: int                           # Route ID
    route_number: str | None                # Route number
    run_type: RunType                       # Run type
    start_time: datetime                    # Run start timestamp
    end_time: datetime | None               # Run end timestamp
    status: str                             # active / ended
    total_stops: int                        # Number of stops in the run
    total_assigned_students: int            # Number of assigned riders
    current_load: int                       # Current cumulative load based on assignments

    model_config = ConfigDict(from_attributes=True)

    # =============================================================================
# Live Run Progress Output
# -----------------------------------------------------------------------------
# Used by the driver workflow endpoint that shows:
# - current stop
# - next stop
# - progress through the run
# =============================================================================
class RunProgressOut(BaseModel):
    run_id: int                                  # Current run ID
    route_id: int                                # Parent route ID
    route_number: Optional[str] = None           # Route number for display
    run_type: RunType                            # AM / PM / etc.

    total_stops: int                             # Total number of stops in run
    current_stop_index: int                      # 1-based current stop position
    remaining_stops: int                         # Stops remaining including current

    current_stop_id: Optional[int] = None        # Current stop database ID
    current_stop_name: Optional[str] = None      # Current stop display name
    current_stop_sequence: Optional[int] = None  # Current stop sequence number
    current_stop_planned_time: Optional[time] = None  # Planned time for current stop

    next_stop_id: Optional[int] = None           # Next stop database ID
    next_stop_name: Optional[str] = None         # Next stop display name
    next_stop_sequence: Optional[int] = None     # Next stop sequence number
    next_stop_planned_time: Optional[time] = None  # Planned time for next stop

    model_config = ConfigDict(from_attributes=True)  # Enable ORM -> schema conversion