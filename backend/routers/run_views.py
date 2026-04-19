# ===========================================================
# backend/routers/run_views.py - FleetOS Run View Router
# -----------------------------------------------------------
# Read-only run endpoints split from the main run router.
# ===========================================================

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db

from backend import schemas
from backend.models import run as run_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.models.associations import StudentRunAssignment
from backend.models.operator import Operator
from backend.models.run_event import RunEvent
from backend.schemas.run import (
    OnboardStudentItem,
    OnboardStudentsResponse,
    RunDetailOut,
    RunListOut,
    RunOccupancySummaryResponse,
    RunReplayEventOut,
    RunReplayOut,
    RunReplaySummaryOut,
    RunningBoardResponse,
    RunStateOut,
    RunTimelineOut,
)
from backend.schemas.stop import StopOut
from backend.utils.operator_scope import (
    get_operator_context,
    get_operator_scoped_driver_or_404,
)
from backend.utils.student_bus_absence import apply_run_absence_filter
from backend.utils.planning_scope import execution_route_filter, get_route_for_execution_or_404
from backend.routers.run_helpers import (
    _build_run_occupancy_counts,
    _build_running_board_stops,
    _get_execution_scoped_run_or_404,
    _get_operator_scoped_run_or_404,
    _get_run_assignments,
    _group_running_board_students,
    _serialize_run_detail,
    _serialize_run_list_item,
)


router = APIRouter(tags=["Runs"])


# -----------------------------------------------------------
# - List runs by route
# - Return only runs that belong to the selected route
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[RunListOut],
    summary="List runs",
    description="Return summary-level run data for one route only. route_id is required so operators stay inside a selected route context.",
    response_description="Run summary list",
)
def get_all_runs(
    route_id: int | None = Query(None),    # Required route filter
    db: Session = Depends(get_db),          # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate route filter exists
    # -------------------------------------------------------------------------
    if route_id is None:
        raise HTTPException(status_code=400, detail="route_id is required")  # Require route-scoped listing

    get_route_for_execution_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
    )

    # -------------------------------------------------------------------------
    # Load route runs in stable planning order
    # -------------------------------------------------------------------------
    runs = (
        db.query(run_model.Run)
        .options(
            joinedload(run_model.Run.driver),                   # Include driver label
            joinedload(run_model.Run.route),                    # Include route label
            selectinload(run_model.Run.stops),                  # Include stop counts
            selectinload(run_model.Run.student_assignments),    # Include student counts
        )
        .filter(run_model.Run.route_id == route_id)            # Keep only this route's runs
        .order_by(
            run_model.Run.start_time.desc(),                    # Show newest started runs first
            run_model.Run.id.desc(),                            # Keep planned/history ordering stable
        )
        .all()
    )                                                          # Load route runs

    return [_serialize_run_list_item(run) for run in runs]     # Return run summary list


# =============================================================================
# GET /runs/active
# Return the current active run for one driver
#
# Rules:
#   - driver_id is required
#   - active run = start_time IS NOT NULL and end_time IS NULL
#   - if no active run exists for that driver, return 404
#   - if multiple active runs exist, return the newest one
# =============================================================================
@router.get(
    "/active",
    response_model=schemas.RunOut,
    summary="Get active run",
    description="Operational runtime endpoint that returns the newest active run for the requested driver.",
    response_description="Active run",
)
def get_active_run(
    driver_id: int,                         # Driver to check for active run
    db: Session = Depends(get_db),          # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate driver exists
    # -------------------------------------------------------------------------
    get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    # -------------------------------------------------------------------------
    # Find newest active run for this driver
    # -------------------------------------------------------------------------
    active_run = (
        db.query(run_model.Run)                      # Query Run table
        .join(run_model.Run.route)
        .filter(run_model.Run.driver_id == driver_id)  # Only this driver
        .filter(execution_route_filter(db=db, operator_id=operator.id))  # Keep active run inside the active execution scope
        .filter(run_model.Run.start_time.is_not(None))  # Only started runs
        .filter(run_model.Run.end_time.is_(None))   # Only active runs
        .order_by(run_model.Run.start_time.desc())  # Newest active run first
        .first()
    )

    # -------------------------------------------------------------------------
    # Return result or 404
    # -------------------------------------------------------------------------
    if not active_run:                              # If no active run found
        raise HTTPException(status_code=404, detail="No active run found for this driver")

    return active_run                               # Return active run


# =============================================================================
# GET /runs/{run_id}/stops
# Return ordered stops for a specific run
#
# Ordering:
#   - sequence ascending
#   - id ascending
# =============================================================================
@router.get(
    "/{run_id}/stops",
    response_model=List[StopOut],
    summary="Get run stops",
    description="Return the prepared stop structure for a run ordered by sequence and id so drivers and operators can work inside the selected run context.",
    response_description="Ordered run stops",
)
def get_run_stops(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    _get_execution_scoped_run_or_404(run_id, db, operator.id)

    # -------------------------------------------------------------------------
    # Load stops in stable order
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)   # Only stops for this run
        .order_by(
            stop_model.Stop.sequence.asc(),         # Primary stable order
            stop_model.Stop.id.asc(),               # Secondary stable order
        )
        .all()
    )

    return stops  # Return ordered stop list


# -----------------------------------------------------------
# - Get run state
# - Return the current operational snapshot of a run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/state",
    response_model=RunStateOut,
    summary="Get run state",
    description=(
        "Return the current operational snapshot for a run, including the actual current runtime stop, "
        "flexible stop-progress interpretation, and rider counts."
    ),
    response_description="Current run state",
)
def get_run_state(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(run_id, db, operator.id)

    # -------------------------------------------------------------------------
    # Load stops in stable order for current-stop and progress context
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .order_by(
            stop_model.Stop.sequence.asc(),
            stop_model.Stop.id.asc(),
        )
        .all()
    )
    stops_by_id = {stop.id: stop for stop in stops}  # Fast lookup by actual current stop ID

    # -------------------------------------------------------------------------
    # Load runtime assignments and reuse shared occupancy interpretation
    # -------------------------------------------------------------------------
    assignments = _get_run_assignments(run_id, db)
    occupancy_counts = _build_run_occupancy_counts(assignments)

    # -------------------------------------------------------------------------
    # Determine distinct arrived stops for flexible-progress reporting
    # -------------------------------------------------------------------------
    arrive_events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .filter(RunEvent.event_type == "ARRIVE")
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())
        .all()
    )
    arrived_stop_ids = {
        event.stop_id
        for event in arrive_events
        if event.stop_id is not None
    }  # Distinct actual stop visits, even if the bus revisits a stop later

    total_stops = len(stops)
    completed_stops = min(total_stops, len(arrived_stop_ids))  # Cap to configured stops for safety
    remaining_stops = max(0, total_stops - completed_stops)  # Never allow negative remaining stops

    if total_stops == 0:
        progress_percent = 0.0  # Avoid division by zero for runs with no stops
    else:
        progress_percent = round((completed_stops / total_stops) * 100, 1)  # Stable % from distinct arrivals
    progress_percent = max(0.0, min(100.0, progress_percent))  # Keep progress within valid bounds

    current_stop = stops_by_id.get(run.current_stop_id) if run.current_stop_id is not None else None

    # -------------------------------------------------------------------------
    # Return current run snapshot
    # -------------------------------------------------------------------------
    return RunStateOut(
        run_id=run.id,
        route_id=run.route_id,
        driver_id=run.driver_id,
        run_type=run.run_type,
        current_stop_id=run.current_stop_id,
        current_stop_sequence=run.current_stop_sequence,
        current_stop_name=current_stop.name if current_stop else None,
        total_stops=total_stops,
        completed_stops=completed_stops,
        remaining_stops=remaining_stops,
        progress_percent=progress_percent,
        total_assigned_students=occupancy_counts["total_assigned_students"],
        picked_up_students=occupancy_counts["total_picked_up"],
        dropped_off_students=occupancy_counts["total_dropped_off"],
        students_onboard=occupancy_counts["total_currently_onboard"],
        remaining_pickups=occupancy_counts["total_not_yet_boarded"],
        remaining_dropoffs=occupancy_counts["total_remaining_dropoffs"],
    )


# =============================================================================
# GET /runs/{run_id}/onboard_students
# -----------------------------------------------------------------------------
# Return all students currently onboard the bus for an active run.
#
# Purpose:
#   - allow drivers to see who is still on the bus
#   - allow dispatch to monitor live bus occupancy
#
# Data source:
#   StudentRunAssignment where:
#       run_id == run_id
#       is_onboard == True
#
# Students are returned ordered by stop sequence.
# =============================================================================
@router.get(
    "/{run_id}/onboard_students",
    response_model=OnboardStudentsResponse,
    summary="Get onboard students",
    description="Return students currently onboard the bus for an active run, ordered by stop sequence.",
    response_description="Onboard student list",
)
def get_onboard_students(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    _get_execution_scoped_run_or_404(run_id, db, operator.id)
    # -------------------------------------------------------------------------
    # Load run
    # -------------------------------------------------------------------------
    run = (
        db.query(run_model.Run)
        .filter(run_model.Run.id == run_id)
        .first()
    )

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # -------------------------------------------------------------------------
    # Ensure run is active
    # -------------------------------------------------------------------------
    if run.start_time is None or run.end_time is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run is not active",
        )

    # -------------------------------------------------------------------------
    # Load onboard assignments with related student + stop
    # -------------------------------------------------------------------------
    assignments = (
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),
            joinedload(StudentRunAssignment.stop),
        )
        .filter(
            StudentRunAssignment.run_id == run_id,
            StudentRunAssignment.is_onboard == True,
        )
        .all()
    )

    # -------------------------------------------------------------------------
    # Sort students by stop sequence
    # -------------------------------------------------------------------------
    assignments.sort(key=lambda a: a.stop.sequence if a.stop else 0)

    # -------------------------------------------------------------------------
    # Build response items
    # -------------------------------------------------------------------------
    students = []

    for a in assignments:
        students.append(
            OnboardStudentItem(
                student_id=a.student.id,
                student_name=a.student.name,
                stop_id=a.stop.id,
                stop_name=a.stop.name,
                stop_sequence=a.stop.sequence,
                picked_up_at=a.picked_up_at,
            )
        )

    # -------------------------------------------------------------------------
    # Return structured response
    # -------------------------------------------------------------------------
    return OnboardStudentsResponse(
        run_id=run_id,
        total_onboard_students=len(students),
        students=students,
    )


# =============================================================================
# Get Run Occupancy Summary
# -----------------------------------------------------------------------------
# Purpose:
#   Return a quick student occupancy summary for one run.
#
# Summary includes:
#   - total assigned students
#   - total picked up
#   - total dropped off
#   - total currently onboard
#   - total not yet boarded
#
# Notes:
#   Runtime state is derived from StudentRunAssignment.
#   This keeps summary logic aligned with pickup/dropoff/onboard endpoints.
# =============================================================================
@router.get(
    "/{run_id}/occupancy_summary",
    response_model=RunOccupancySummaryResponse,
    summary="Get run occupancy summary",
    description="Return rider occupancy totals for one run based on runtime student assignments.",
    response_description="Run occupancy summary",
)
def get_run_occupancy_summary(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(run_id, db, operator.id)

    # -------------------------------------------------------------------------
    # Load all runtime student assignments for this run
    # -------------------------------------------------------------------------
    assignments = _get_run_assignments(run_id, db)
    occupancy_counts = _build_run_occupancy_counts(assignments)

    # -------------------------------------------------------------------------
    # Return occupancy summary
    # -------------------------------------------------------------------------
    return RunOccupancySummaryResponse(
        run_id=run.id,
        route_id=run.route_id,
        run_type=run.run_type,
        total_assigned_students=occupancy_counts["total_assigned_students"],
        total_picked_up=occupancy_counts["total_picked_up"],
        total_dropped_off=occupancy_counts["total_dropped_off"],
        total_currently_onboard=occupancy_counts["total_currently_onboard"],
        total_not_yet_boarded=occupancy_counts["total_not_yet_boarded"],
    )


# =============================================================================
# GET /runs/{run_id}/timeline
# ---------------------------------------------------------------------------
# Purpose:
#   Return raw ordered ARRIVE / PICKUP / DROPOFF history for the run.
#
# Notes:
#   This stays separate from /state because timeline is a lossless event log,
#   not a current snapshot or interpreted admin view.
# =============================================================================
@router.get(
    "/{run_id}/timeline",
    response_model=RunTimelineOut,
    summary="Get run timeline",
    description=(
        "Return the raw ordered ARRIVE, PICKUP, and DROPOFF event history for a run. "
        "Repeated ARRIVE events are preserved when the driver revisits stops during flexible execution."
    ),
    response_description="Run timeline",
)
def get_run_timeline(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    run = _get_execution_scoped_run_or_404(run_id, db, operator.id)

    events = (
        db.query(RunEvent)                                                # Query run events
        .filter(RunEvent.run_id == run_id)                                # Only this run
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())            # Stable oldest-first ordering
        .all()                                                            # Materialize list
    )

    return RunTimelineOut(                                                # Build timeline response
        run_id=run_id,                                                    # Parent run ID
        total_events=len(events),                                         # Event count
        events=events,                                                    # Ordered event rows
    )


# =============================================================================
# GET /runs/{run_id}/replay
# ---------------------------------------------------------------------------
# Purpose:
#   Return an interpreted human-readable history for admin/debug/report use.
#
# Notes:
#   This stays separate from /timeline because replay adds names, messages,
#   and occupancy interpretation on top of the raw event log.
# =============================================================================
@router.get(
    "/{run_id}/replay",
    response_model=RunReplayOut,
    summary="Get run replay",
    description=(
        "Return an interpreted event history for a run with readable messages and occupancy context. "
        "Flexible stop revisits and jumps are reflected from the underlying runtime event log."
    ),
    response_description="Run replay",
)
def get_run_replay(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(run_id, db, operator.id)

    # -------------------------------------------------------------------------
    # Load all run events in stable chronological order
    # -------------------------------------------------------------------------
    raw_events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)  # Only events for this run
        .order_by(RunEvent.timestamp.asc(), RunEvent.id.asc())  # Stable time order
        .all()
    )

    # -------------------------------------------------------------------------
    # Build replay rows with readable context
    # -------------------------------------------------------------------------
    replay_events: list[RunReplayEventOut] = []  # Final replay rows
    onboard_count = 0  # Live bus occupancy during replay

    total_arrivals = 0  # Summary counter
    total_pickups = 0  # Summary counter
    total_dropoffs = 0  # Summary counter

    for event in raw_events:
        stop_name = None  # Default when stop is missing
        student_name = None  # Default when student is missing

        # ---------------------------------------------------------------------
        # Resolve stop context
        # ---------------------------------------------------------------------
        if event.stop_id is not None:
            stop = db.get(stop_model.Stop, event.stop_id)  # Load stop by ID
            stop_name = stop.name if stop else None  # Safe stop name

        # ---------------------------------------------------------------------
        # Resolve student context
        # ---------------------------------------------------------------------
        if event.student_id is not None:
            student = db.get(student_model.Student, event.student_id)  # Load student
            student_name = student.name if student else None  # Safe student name

        # ---------------------------------------------------------------------
        # Convert raw event into readable replay message
        # ---------------------------------------------------------------------
        if event.event_type == "ARRIVE":
            total_arrivals += 1  # Count arrival events

            if stop_name:
                message = f"Bus arrived at {stop_name}"  # Human-readable arrival
            elif event.stop_id is not None:
                message = f"Bus arrived at Stop {event.stop_id}"  # Fallback arrival
            else:
                message = "Bus arrived at an unknown stop"  # Safety fallback

        elif event.event_type == "PICKUP":
            total_pickups += 1  # Count pickup events
            onboard_count += 1  # Occupancy increases after pickup

            if student_name and stop_name:
                message = f"{student_name} picked up at {stop_name}"  # Full pickup message
            elif event.student_id is not None and stop_name:
                message = f"Student {event.student_id} picked up at {stop_name}"  # Partial fallback
            elif student_name and event.stop_id is not None:
                message = f"{student_name} picked up at Stop {event.stop_id}"  # Partial fallback
            else:
                message = "Student picked up"  # Safety fallback

        elif event.event_type == "DROPOFF":
            total_dropoffs += 1  # Count dropoff events
            onboard_count = max(0, onboard_count - 1)  # Never allow negative occupancy

            if student_name and stop_name:
                message = f"{student_name} dropped off at {stop_name}"  # Full dropoff message
            elif event.student_id is not None and stop_name:
                message = f"Student {event.student_id} dropped off at {stop_name}"  # Partial fallback
            elif student_name and event.stop_id is not None:
                message = f"{student_name} dropped off at Stop {event.stop_id}"  # Partial fallback
            else:
                message = "Student dropped off"  # Safety fallback

        else:
            message = f"Run event: {event.event_type}"  # Unknown/future event fallback

        # ---------------------------------------------------------------------
        # Save replay event row
        # ---------------------------------------------------------------------
        replay_events.append(
            RunReplayEventOut(
                id=event.id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                stop_id=event.stop_id,
                stop_name=stop_name,
                student_id=event.student_id,
                student_name=student_name,
                onboard_count=onboard_count,
                message=message,
            )
        )

    # -------------------------------------------------------------------------
    # Return replay response with summary
    # -------------------------------------------------------------------------
    return RunReplayOut(
        run_id=run.id,
        events=replay_events,
        summary=RunReplaySummaryOut(
            total_events=len(replay_events),
            total_arrivals=total_arrivals,
            total_pickups=total_pickups,
            total_dropoffs=total_dropoffs,
        ),
    )


# -----------------------------------------------------------
# - Get run detail
# - Return one run with nested route, stops, and students
# -----------------------------------------------------------
@router.get(
    "/{run_id}",
    response_model=RunDetailOut,
    summary="Get run detail",
    description="Return one run by id with nested route, driver, stop, and runtime student details.",
    response_description="Run detail",
)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run with linked route, stops, and student assignments
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
            selectinload(run_model.Run.stops),
            selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),
            selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),
        ],
    )

    # -------------------------------------------------------------------------
    # Return nested run detail response
    # -------------------------------------------------------------------------
    return _serialize_run_detail(run)                            # Return run detail


# -----------------------------------------------------------
# - Get running board
# - Return the operational running board for one run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/running_board",
    response_model=RunningBoardResponse,
    summary="Get running board",
    description="Operational runtime endpoint that returns the running board for a prepared run using runtime student assignments as the source of truth.",
    response_description="Running board",
)
def get_running_board(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load the run
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(run_id, db, operator.id)

    # -------------------------------------------------------------------------
    # Load run stops ordered by sequence
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)  # Query Stop table
        .options(joinedload(stop_model.Stop.school))  # Load school names for school-stop display rows
        .filter(stop_model.Stop.run_id == run_id)  # Only stops belonging to this run
        .order_by(stop_model.Stop.sequence.asc())  # Ensure correct stop order
        .all()
    )

    # -------------------------------------------------------------------------
    # Load student assignments for this run
    # -------------------------------------------------------------------------
    assignments = apply_run_absence_filter((
        db.query(StudentRunAssignment)  # Query assignment table
        .options(joinedload(StudentRunAssignment.student))  # Load linked student
        .filter(StudentRunAssignment.run_id == run_id)  # Only this run
    ), run).all()  # Exclude planned absences from running board source data

    # -------------------------------------------------------------------------
    # Group assignments by stop
    # -------------------------------------------------------------------------
    assignments_by_stop = _group_running_board_students(assignments)  # Keep runtime assignments authoritative
    running_stops = _build_running_board_stops(stops, assignments_by_stop)  # Preserve existing board contract

    # -------------------------------------------------------------------------
    # Return full running board
    # -------------------------------------------------------------------------
    return RunningBoardResponse(
        run_id=run.id,  # Run identifier
        route_id=run.route_id,  # Parent route
        run_name=f"{run.route.route_number} {run.run_type}".strip() if run.route and run.route.route_number else run.run_type,  # Route-number display label
        total_stops=len(stops),  # Stop count
        total_assigned_students=len(assignments),  # Rider count
        stops=running_stops,  # Running board rows
    )


# -----------------------------------------------------------
# - Get run assignments
# - Return all effective student assignments for a specific run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/assignments",
    summary="Get run assignments",
    description="Return all effective runtime student assignments for a run with student and stop details. This is a read-only operational view, not the primary setup flow.",
    response_description="Run assignments",
)
def get_run_assignments(
    run_id: int,                         # Run identifier
    db: Session = Depends(get_db),        # Database session dependency
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Validate run exists
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(run_id, db, operator.id)

    # -------------------------------------------------------------------------
    # Load assignments with student and stop
    # -------------------------------------------------------------------------
    assignments = apply_run_absence_filter((
        db.query(StudentRunAssignment)
        .options(
            joinedload(StudentRunAssignment.student),  # Load student
            joinedload(StudentRunAssignment.stop),     # Load stop
        )
        .filter(StudentRunAssignment.run_id == run_id)
    ), run).all()  # Exclude planned absences from run assignment output

    # -------------------------------------------------------------------------
    # Apply stable ordering in Python
    # -------------------------------------------------------------------------
    assignments.sort(
        key=lambda a: (
            a.stop.sequence if a.stop and a.stop.sequence is not None else 999999,  # Stop order
            a.id,                                                                   # Stable tie-breaker
        )
    )

    # -------------------------------------------------------------------------
    # Build response
    # -------------------------------------------------------------------------
    result = []

    for a in assignments:
        result.append({
            "student_id": a.student.id if a.student else None,
            "student_name": a.student.name if a.student else None,
            "stop_id": a.stop_id,
            "stop_name": a.stop.name if a.stop else None,
            "sequence": a.stop.sequence if a.stop else None,
            "run_type": run.run_type,
        })

    return result


# -----------------------------------------------------------
# - Get run summary
# - Return a compact operational summary for one run
# -----------------------------------------------------------
@router.get(
    "/{run_id}/summary",
    response_model=schemas.RunSummaryOut,
    summary="Get run summary",
    description="Operational runtime endpoint that returns a compact summary for one prepared run with driver, route, and rider totals.",
    response_description="Run summary",
)
def get_run_summary(
    run_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):

    # -------------------------------------------------------------------------
    # Load run with driver and route
    # -------------------------------------------------------------------------
    run = _get_execution_scoped_run_or_404(
        run_id,
        db,
        operator.id,
        options=[
            joinedload(run_model.Run.driver),
            joinedload(run_model.Run.route),
        ],
    )

    # -------------------------------------------------------------------------
    # Load run stops
    # -------------------------------------------------------------------------
    stops = (
        db.query(stop_model.Stop)
        .filter(stop_model.Stop.run_id == run_id)
        .all()
    )

    # -------------------------------------------------------------------------
    # Load student assignments
    # -------------------------------------------------------------------------
    assignments = apply_run_absence_filter((
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
    ), run).all()  # Exclude planned absences from summary counts
    occupancy_counts = _build_run_occupancy_counts(assignments)  # Reuse shared onboard/load counts

    # -------------------------------------------------------------------------
    # Determine run status
    # -------------------------------------------------------------------------
    if run.start_time is None:
        status = "planned"
    elif run.end_time is None:
        status = "active"
    else:
        status = "ended"

    # -------------------------------------------------------------------------
    # Compute current load
    # -------------------------------------------------------------------------
    current_load = occupancy_counts["total_currently_onboard"]  # Current load means students onboard now

    # -------------------------------------------------------------------------
    # Return summary
    # -------------------------------------------------------------------------
    return schemas.RunSummaryOut(
        run_id=run.id,
        driver_id=run.driver_id,
        driver_name=run.driver.name if run.driver else None,
        route_id=run.route_id,
        route_number=run.route.route_number if run.route else None,
        run_type=run.run_type,
        scheduled_start_time=run.scheduled_start_time,
        scheduled_end_time=run.scheduled_end_time,
        start_time=run.start_time,
        end_time=run.end_time,
        status=status,
        total_stops=len(stops),
        total_assigned_students=len(assignments),
        current_load=current_load,
    )
