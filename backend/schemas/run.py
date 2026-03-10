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

    # =============================================================================
# Student Pickup Schemas
# -----------------------------------------------------------------------------
# These schemas support runtime student boarding operations during a run.
#
# Purpose:
#   - Allow driver to mark a student as picked up at a stop
#   - Used by endpoint:
#       POST /runs/{run_id}/pickup_student
#
# Workflow:
#   Driver arrives at stop → boards student → API marks pickup
# =============================================================================


# =============================================================================
# PickupStudentRequest
# -----------------------------------------------------------------------------
# Request body sent by the driver to mark a student as boarded.
#
# Only the student_id is required because:
#   - run_id is already provided in the endpoint path
#   - the stop is determined automatically using run.current_stop_sequence
# =============================================================================

class PickupStudentRequest(BaseModel):
    student_id: int  # ID of the student being picked up


# =============================================================================
# PickupStudentResponse
# -----------------------------------------------------------------------------
# Response returned after a successful pickup operation.
#
# Provides confirmation and key runtime tracking fields so that:
#   - driver apps
#   - live dashboards
#   - parent notifications (future feature)
#
# can immediately know the student is onboard.
# =============================================================================

class PickupStudentResponse(BaseModel):
    message: str  # Human-readable confirmation message

    run_id: int  # Run where pickup occurred
    student_id: int  # Student that was picked up

    picked_up: bool  # Confirms pickup flag was set
    is_onboard: bool  # Indicates the student is now on the bus

    picked_up_at: datetime  # Timestamp when pickup occurred

# =============================================================================
# Student Dropoff Schemas
# -----------------------------------------------------------------------------
# These schemas support runtime student drop-off operations during a run.
#
# Purpose:
#   - Allow driver to mark a student as dropped off
#   - Used by endpoint:
#       POST /runs/{run_id}/dropoff_student
#
# Workflow:
#   Student onboard → driver confirms drop-off → system records timestamp
# =============================================================================


# =============================================================================
# DropoffStudentRequest
# -----------------------------------------------------------------------------
# Request body sent by the driver to mark a student as dropped off.
#
# Only the student_id is required because:
#   - run_id is already provided in the endpoint path
#   - stop validation uses run.current_stop_sequence
# =============================================================================
class DropoffStudentRequest(BaseModel):
    student_id: int  # ID of the student being dropped off


# =============================================================================
# DropoffStudentResponse
# -----------------------------------------------------------------------------
# Response returned after a successful drop-off operation.
#
# Confirms:
#   - student is no longer onboard
#   - drop-off timestamp stored
#
# This information supports:
#   - attendance verification
#   - parent notifications
#   - route completion analytics
# =============================================================================
class DropoffStudentResponse(BaseModel):
    message: str  # Human-readable confirmation

    run_id: int  # Run where drop-off occurred
    student_id: int  # Student that was dropped off

    dropped_off: bool  # Confirms drop-off flag was set
    is_onboard: bool  # Should now be False

    dropped_off_at: datetime  # Timestamp when drop-off occurred

    # =============================================================================
# Onboard Students Schemas
# -----------------------------------------------------------------------------
# These schemas support returning the list of students currently onboard
# during an active run.
#
# Used by endpoint:
#   - GET /runs/{run_id}/onboard_students
# =============================================================================


# =============================================================================
# OnboardStudentItem
# -----------------------------------------------------------------------------
# One student currently onboard the bus.
#
# Includes:
#   - student identity
#   - assigned stop info
#   - pickup timestamp
# =============================================================================
class OnboardStudentItem(BaseModel):
    student_id: int  # Student ID
    student_name: str  # Student name

    stop_id: int  # Assigned stop ID
    stop_name: str  # Assigned stop name
    stop_sequence: int  # Assigned stop order in the run

    picked_up_at: datetime | None = None  # Time student was picked up


# =============================================================================
# OnboardStudentsResponse
# -----------------------------------------------------------------------------
# Response returned for the onboard-students endpoint.
#
# Includes:
#   - run ID
#   - total students currently onboard
#   - ordered list of onboard students
# =============================================================================
class OnboardStudentsResponse(BaseModel):
    run_id: int  # Run being checked
    total_onboard_students: int  # Count of onboard students

    students: list[OnboardStudentItem]  # Students currently onboard


# =============================================================================
# Run Occupancy Summary Schema
# -----------------------------------------------------------------------------
# Purpose:
#   Response model for GET /runs/{run_id}/occupancy_summary
#
#   Provides a quick overview of student occupancy for a run.
#   This summary is used for:
#       - driver dashboard
#       - dispatch monitoring
#       - future safety alerts
#
#   Counts are derived from StudentRunAssignment runtime fields:
#       picked_up
#       dropped_off
#       is_onboard
# =============================================================================

class RunOccupancySummaryResponse(BaseModel):
    """
    Response model representing the occupancy state of a run.
    """

    run_id: int                     # ID of the run
    route_id: int                   # Route associated with the run
    run_type: str                   # AM / PM / Charter etc.

    total_assigned_students: int    # All runtime student assignments for this run
    total_picked_up: int            # Students picked up at least once
    total_dropped_off: int          # Students dropped off
    total_currently_onboard: int    # Students currently on the bus
    total_not_yet_boarded: int      # Assigned students who have not been picked up yet