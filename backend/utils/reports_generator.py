# -----------------------------------------------------------
# - Reports generator
# - Build reports-layer summaries behind canonical /reports endpoints
# -----------------------------------------------------------
from sqlalchemy.orm import Session  # Database session type
from datetime import date, datetime, time # Date filter type
from backend.models import (  # Existing summary data sources
    driver as driver_model,
    route as route_model,
    run as run_model,
    dispatch as dispatch_model,
    associations as assoc_model,
    student as student_model,
)
from backend.models.yard import Yard

from backend.models.run import Run  # Import locally to avoid circular dependency
from backend.models.run_event import RunEvent  # Run event history
from backend.models.associations import StudentRunAssignment  # Runtime assignments
from backend.utils.student_bus_absence import has_student_bus_absence  # Absence check
from backend.models import school as school_model  # School model
from backend.models import SchoolAttendanceVerification  # School confirmation state
from backend.utils.operator_scope import get_route_access_level
from backend.utils.planning_scope import accessible_route_filter, accessible_school_filter
from backend.utils.route_driver_assignment import get_route_driver_name, resolve_route_driver_assignment

def driver_summary(db: Session, driver_id: int, operator_id: int | None = None) -> dict:
    driver_query = db.query(driver_model.Driver).filter(driver_model.Driver.id == driver_id)
    if operator_id is not None:
        driver_query = (
            driver_query
            .join(driver_model.Driver.yard)
            .filter(Yard.operator_id == operator_id)
        )
    drv = driver_query.first()  # Load driver with optional operator scope
    if not drv:
        return {"error": "Driver not found"}  # Return stable missing-driver payload

    total_charter_hours = (
        db.query(dispatch_model.DispatchRecord)
        .filter(dispatch_model.DispatchRecord.driver_id == driver_id)
        .with_entities(dispatch_model.DispatchRecord.charter_hours)
        .all()
    )  # Load dispatch hour fragments for this driver

    total_hours = sum(float(h[0]) for h in total_charter_hours if h[0])  # Sum non-null charter hours

    approved = (
        db.query(dispatch_model.DispatchRecord)
        .filter(
            dispatch_model.DispatchRecord.driver_id == driver_id,
            dispatch_model.DispatchRecord.approved.is_(True),
        )
        .count()
    )  # Count approved dispatch days

    pending = (
        db.query(dispatch_model.DispatchRecord)
        .filter(
            dispatch_model.DispatchRecord.driver_id == driver_id,
            dispatch_model.DispatchRecord.approved.is_(False),
        )
        .count()
    )  # Count pending dispatch days

    return {
        "driver_id": driver_id,
        "driver_name": drv.name,
        "charter_hours": round(total_hours, 2),
        "approved_days": approved,
        "pending_days": pending,
    }  # Preserve existing payload shape


def route_summary(db: Session, route_id: int, operator_id: int | None = None) -> dict:
    r = db.get(route_model.Route, route_id)  # Load route
    if not r or (operator_id is not None and get_route_access_level(r, operator_id) is None):
        return {"error": "Route not found"}  # Return stable missing-route payload
    assigned_bus = r.bus  # Current assigned bus when present

    active_driver_id = None  # Default unresolved route driver
    try:
        active_assignment = resolve_route_driver_assignment(r)  # Resolve active route driver
        active_driver_id = active_assignment.driver_id
    except ValueError:
        active_assignment = None  # Leave unresolved when route has no active driver

    schools_list = [{"id": s.id, "name": s.name} for s in r.schools]  # Serialize assigned schools

    stops_list = []
    for run in r.runs:
        run_stops = sorted(run.stops, key=lambda st: st.sequence)  # Keep stable stop order
        for st in run_stops:
            stops_list.append(
                {
                    "id": st.id,
                    "run_id": run.id,
                    "sequence": st.sequence,
                    "type": st.type.value if hasattr(st.type, "value") else str(st.type),
                }
            )  # Preserve existing stop payload shape

    route_run_ids = [run.id for run in r.runs]  # Collect child run IDs once
    assignments = []
    if route_run_ids:
        assignments = (
            db.query(assoc_model.StudentRunAssignment)
            .filter(assoc_model.StudentRunAssignment.run_id.in_(route_run_ids))
            .all()
        )  # Load runtime student assignments for the route

    students_by_id = {}
    for assignment in assignments:
        student = db.get(student_model.Student, assignment.student_id)  # Resolve assigned student
        if not student or student.id in students_by_id:
            continue  # Keep unique serialized students only
        students_by_id[student.id] = {
            "id": student.id,
            "name": student.name,
            "grade": student.grade,
        }

    students_list = list(students_by_id.values())  # Convert unique student map back to list
    total_runs = db.query(run_model.Run).filter(run_model.Run.route_id == route_id).count()  # Count route runs

    return {
        "route_id": route_id,
        "route_number": r.route_number,
        "bus_id": assigned_bus.id if assigned_bus else None,
        "bus_unit_number": assigned_bus.unit_number if assigned_bus else None,
        "bus_license_plate": assigned_bus.license_plate if assigned_bus else None,
        "bus_capacity": assigned_bus.capacity if assigned_bus else None,
        "bus_size": assigned_bus.size if assigned_bus else None,
        "num_runs": r.num_runs,
        "driver_id": active_driver_id,  # Compatibility shim for existing report payloads
        "active_driver_id": active_driver_id,
        "active_driver_name": get_route_driver_name(r),
        "schools": schools_list,
        "stops": stops_list,
        "students": students_list,
        "total_runs": total_runs,
    }  # Preserve existing payload shape


def dispatch_summary(
    db: Session,
    yard_id: int,
    start: date,
    end: date,
    operator_id: int | None = None,
) -> list:
    query = (
        db.query(dispatch_model.DispatchRecord)
        .join(driver_model.Driver, driver_model.Driver.id == dispatch_model.DispatchRecord.driver_id)
        .join(driver_model.Driver.yard)
        .filter(
            dispatch_model.DispatchRecord.work_date >= start,
            dispatch_model.DispatchRecord.work_date <= end,
            Yard.id == yard_id,
        )
    )
    if operator_id is not None:
        query = (
            query
            .filter(Yard.operator_id == operator_id)
        )
    records = (
        query
        .order_by(
            driver_model.Driver.name.asc(),
            dispatch_model.DispatchRecord.work_date.asc(),
            dispatch_model.DispatchRecord.id.asc(),
        )
        .all()
    )  # Load dispatch rows inside the requested range

    driver_records = {}
    for r in records:
        driver_name = r.driver.name if r.driver else None
        if r.driver_id not in driver_records:
            driver_records[r.driver_id] = {
                "driver_id": r.driver_id,
                "driver_name": driver_name,
                "records": [],
            }
        driver_records[r.driver_id]["records"].append(
            {
                "work_date": r.work_date,
                "charter_hours": float(r.charter_hours or 0),
                "approved": r.approved,
            }
        )  # Preserve existing dispatch row data while grouping by driver
    return list(driver_records.values())


def generate_reports(
    db: Session,
    reports_type: str,
    ref_id: int = None,
    start: date = None,
    end: date = None,
    operator_id: int | None = None,
):
    if reports_type == "driver" and ref_id:
        return driver_summary(db, ref_id, operator_id=operator_id)  # Return driver reports summary
    if reports_type == "route" and ref_id:
        return route_summary(db, ref_id, operator_id=operator_id)  # Return route reports summary
    if reports_type == "dispatch" and ref_id and start and end:
        return dispatch_summary(db, ref_id, start, end, operator_id=operator_id)  # Return dispatch summary
    if reports_type == "run" and ref_id:
        run = db.get(Run, ref_id)  # Load run for run-level reports
        if not run:
            return {"error": "Run not found"}  # Preserve error-style contract

        assignments = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.run_id == run.id)
            .all()
        )  # Load run assignments

        events = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run.id)
            .all()
        )  # Load run events

        absence_lookup = {}  # Cache planned absences by student
        for assignment in assignments:
            absence_lookup[assignment.student_id] = has_student_bus_absence(
                assignment.student_id,  # Student identifier
                run,  # Run object
                db,  # Database session
            )

        return run_reports_summary(
            db,
            run,
            assignments,
            events,
            absence_lookup,
        )  # Return run reports summary
    if reports_type == "date" and start and end:
        return date_summary(db, start, end, operator_id=operator_id)
    if reports_type == "school" and ref_id:
        return school_reports_summary(db, ref_id, operator_id=operator_id)
    return {"error": "Invalid reports type or parameters"}  # Preserve error-style contract

# -----------------------------------------------------------
# Student Reports Status
# - Derive unified reports state from run events and absence
# -----------------------------------------------------------

def classify_student_status(assignment, events, absence_lookup):
    """Return reports status for a student assignment."""  # Unified reports state

    student_id = assignment.student_id  # Student identifier

    if absence_lookup.get(student_id):
        return "planned_absent"  # Student planned not to ride

    if assignment.picked_up and assignment.dropped_off:
        return "dropped_off"  # Student completed ride

    if assignment.picked_up:
        return "picked_up"  # Student boarded but dropoff not yet recorded

    for event in events:
        if event.student_id == student_id and event.event_type == "STUDENT_NO_SHOW":
            return "no_show"  # Automatically generated no-show

    return "expected"  # Student expected but no event yet



# -----------------------------------------------------------
# Run Reports Summary
# - Build student and stop reports view for a run
# -----------------------------------------------------------
def run_reports_summary(db, run, assignments, events, absence_lookup):
    """Return reports status for each student in a run."""  # Reports-layer computation

    results = []  # Output list

    for assignment in assignments:
        status = classify_student_status(assignment, events, absence_lookup)  # Determine status

        results.append(
            {
                "student_id": assignment.student_id,  # Student identifier
                "student_name": assignment.student.name if assignment.student else None,  # Student display name
                "stop_id": assignment.stop_id,  # Assigned stop identifier
                "stop_name": assignment.stop.name if assignment.stop else None,  # Stop display name
                "status": status,  # Reports status
            }
        )

    # -----------------------------------------------------------
    # Stop Reports Totals
    # - Aggregate reports by stop
    # -----------------------------------------------------------
    stop_totals = {}  # Stop-level counters

    for r in results:
        stop_id = r["stop_id"]  # Current stop identifier

        if stop_id not in stop_totals:
            stop_totals[stop_id] = {
                "stop_name": r["stop_name"],  # Stop display name
                "planned_absent": 0,
                "picked_up": 0,
                "dropped_off": 0,
                "no_show": 0,
                "expected": 0,
            }

        stop_totals[stop_id][r["status"]] += 1  # Increment stop counter

    totals = {
        "planned_absent": 0,
        "picked_up": 0,
        "dropped_off": 0,
        "no_show": 0,
        "expected": 0,
    }  # Reports counters

    for r in results:
        totals[r["status"]] += 1  # Increment status count

    return {
        "route_number": run.route.route_number if run.route else None,  # Operational route identifier
        "run_type": run.run_type,                                       # Flexible run label
        "students": results,                                            # Student-level reports
        "totals": totals,                                               # Run totals
        "stop_totals": stop_totals,                                     # Stop-level totals
    }

# -----------------------------------------------------------
# - Date reports summary
# - Build reports output for one requested date window
# -----------------------------------------------------------
def date_summary(db: Session, start: date, end: date, operator_id: int | None = None):        # Build reports for a specific date
    day_start = datetime.combine(start, time.min)             # Start of requested day
    day_end = datetime.combine(end, time.max)                 # End of requested day

    runs = (                                                  # Query runs within full-day range
        db.query(Run)                                         # Select runs
        .filter(Run.start_time >= day_start)                  # Lower datetime boundary
        .filter(Run.start_time <= day_end)                    # Upper datetime boundary
        .all()                                                # Execute query
    )
    if operator_id is not None:
        runs = [
            run for run in runs
            if run.route and get_route_access_level(run.route, operator_id) is not None
        ]

    results = []                                              # Collect run reports summaries

    for run in runs:                                          # Iterate through runs
        assignments = (                                               # Load run assignments
            db.query(StudentRunAssignment)                            # Query runtime assignments
            .filter(StudentRunAssignment.run_id == run.id)            # Match current run
            .all()                                                    # Execute query
        )

        events = (                                                    # Load run events
            db.query(RunEvent)                                        # Query run events
            .filter(RunEvent.run_id == run.id)                        # Match current run
            .all()                                                    # Execute query
        )

        absence_lookup = {}                                           # Cache planned absences by student
        for assignment in assignments:
            absence_lookup[assignment.student_id] = has_student_bus_absence(
                assignment.student_id,                                # Student identifier
                run,                                                  # Current run object
                db,                                                   # Database session
            )

        summary = run_reports_summary(
            db,                                                       # Database session
            run,                                                      # Current run object
            assignments,                                              # Run assignments
            events,                                                   # Run events
            absence_lookup,                                           # Planned absence lookup
        )
        
        if summary and "error" not in summary:                # Skip invalid summaries
            results.append(summary)                           # Add valid run summary
    return {
        "date_range": {"start": str(start), "end": str(end)},  # Requested date window
        "total_runs": len(results),                            # Number of runs returned
        "runs": results,                                       # Run reports payloads
    }
# -----------------------------------------------------------
# - School status normalizer
# - Convert operational reports states into school-facing status
# -----------------------------------------------------------
def normalize_school_status(status: str) -> str:
    """Convert detailed reports state to present/absent for schools."""  # School-safe status view

    if status in {"picked_up", "dropped_off"}:
        return "present"                                                     # Student rode the bus

    return "absent"                                                          # Hide operational absence reason

# -----------------------------------------------------------
# - School reports summary
# - Build school-facing reports grouped by route and run
# -----------------------------------------------------------
def school_reports_summary(db: Session, school_id: int, operator_id: int | None = None):
    school_query = db.query(school_model.School).filter(school_model.School.id == school_id)
    if operator_id is not None:
        school_query = school_query.filter(accessible_school_filter(operator_id))
    school = school_query.first()  # Load school once for final payload
    if not school:
        return {"error": "School not found"}

    routes_query = (  # Load routes serving the school
        db.query(route_model.Route)  # Query routes
        .join(route_model.route_schools)  # Join route-school association
        .filter(route_model.route_schools.c.school_id == school_id)  # Keep only this school's routes
    )
    if operator_id is not None:
        routes_query = routes_query.filter(accessible_route_filter(operator_id))
    routes = routes_query.all()  # Execute query

    results = []  # Collect run reports summaries

    for route in routes:  # Iterate through routes serving this school
        runs = (  # Load runs for this route
            db.query(Run)  # Query runs
            .filter(Run.route_id == route.id)  # Match current route
            .all()  # Execute query
        )

        for run in runs:  # Iterate through route runs
            school_students = (  # Load full school roster for this route
                db.query(student_model.Student)  # Query students
                .filter(student_model.Student.school_id == school_id)  # Keep only this school
                .filter(student_model.Student.route_id == route.id)  # Keep only this route
                .all()  # Execute query
            )

            assignments = (  # Load runtime assignments for this run
                db.query(StudentRunAssignment)  # Query runtime assignments
                .filter(StudentRunAssignment.run_id == run.id)  # Match current run
                .all()  # Execute query
            )

            events = (  # Load runtime events for this run
                db.query(RunEvent)  # Query run events
                .filter(RunEvent.run_id == run.id)  # Match current run
                .all()  # Execute query
            )

            # -----------------------------------------------------------
            # - Map runtime assignments by student id
            # - Used for filtering and status lookup
            # -----------------------------------------------------------
            assignment_by_student_id = {
                assignment.student_id: assignment
                for assignment in assignments
            }

            # -----------------------------------------------------------
            # - Visible students for this run
            # - Show only students assigned to the current run
            # -----------------------------------------------------------
            visible_students = [
                student for student in school_students                     # Route + school roster
                if student.id in assignment_by_student_id                  # Keep only current run assignments
            ]

            absence_lookup = {}  # Planned absence cache for current run

            if run.start_time:  # Only resolve absences when run date exists
                run_date = run.start_time.date()  # Authoritative run date

                for student in visible_students:  # Preload planned absence for assigned students only
                    absence_lookup[student.id] = has_student_bus_absence(
                        student.id,  # Student identifier
                        run,  # Current run object
                        db,  # Database session
                    )

            # -----------------------------------------------------------
            # - Build student rows (school-facing)
            # - Apply persisted school status if exists
            # -----------------------------------------------------------
            school_students_rows = []  # Final school-facing rows
            for student in visible_students:                                      # Always build from full school roster
                assignment = assignment_by_student_id.get(student.id)            # Runtime assignment if present

                if assignment:                                                   # Use runtime state when assigned
                    operational_status = classify_student_status(
                        assignment,                                              # Runtime assignment
                        events,                                                  # Run event history
                        absence_lookup,                                          # Planned absence lookup
                    )
                    final_status = (
                        assignment.school_status                                 # Persisted school-side override
                        if assignment.school_status
                        else normalize_school_status(operational_status)         # Fallback to operational state
                    )
                else:
                    operational_status = (
                        "planned_absent"
                        if absence_lookup.get(student.id)
                        else "expected"
                    )
                    final_status = normalize_school_status(operational_status)   # No assignment → derive normally

                school_students_rows.append(
                    {
                        "student_id": student.id,                                # Required for frontend/backend
                        "student_name": student.name,                            # Display name
                        "status": final_status,                                  # Final school-facing status
                        "is_assigned": assignment is not None,                   # Controls button enable/disable
                    }
                )
            school_students_rows.sort(
                key=lambda s: (s.get("student_name") or "").lower()
            )  # Stable safe alphabetical order

            verification = (
                db.query(SchoolAttendanceVerification)
                .filter(
                    SchoolAttendanceVerification.school_id == school_id,
                    SchoolAttendanceVerification.run_id == run.id,
                )
                .first()
            )  # Load confirmation for this specific school/run pair

            confirmation = {
                "is_confirmed": verification is not None,  # True when school confirmed this run
                "confirmed_at": verification.confirmed_at if verification else None,  # Confirmation timestamp
                "confirmed_by": verification.confirmed_by if verification else None,  # Optional confirmer name
            }
            # -----------------------------------------------------------
            # - Build run payload
            # - Add current run to school results
            # -----------------------------------------------------------
            results.append(
                {
                    "id": run.id,                                           # Template uses run.id
                    "run_id": run.id,                                       # Explicit run identifier
                    "route_id": route.id,                                   # Route identifier for navigation
                    "route_number": route.route_number,                     # Grouping key
                    "driver_name": run.driver.name if run.driver else "Unassigned",  # Display driver
                    "run_type": run.run_type,                                   # Flexible run label
                    "date": run.start_time.date().isoformat() if run.start_time else None,    # Run date
                    "students": school_students_rows,                       # Current school-facing rows
                    "total_students": len(school_students_rows),            # Total visible students
                    "total_present": sum(
                        1 for row in school_students_rows if row.get("status") == "present"
                    ),                                                      # Present count
                    "total_absent": sum(
                        1 for row in school_students_rows if row.get("status") == "absent"
                    ),                                                      # Absent count
                    "confirmation": confirmation,                           # Per-school confirmation state
                }
            )   

    routes_map = {}  # Group runs by route identifier

    for run_data in results:  # Iterate through run reports results
        route_id = run_data.get("route_id")  # Extract route identifier
        route_number = run_data.get("route_number")  # Extract route number for display

        if route_id not in routes_map:  # Initialize route bucket if first time seen
            routes_map[route_id] = {
                "route_id": route_id,  # Route identifier
                "route_number": route_number,  # Route identifier
                "total_runs": 0,  # Counter for runs under this route
                "runs": [],  # Runs belonging to this route
            }

        run_entry = dict(run_data)  # Copy run payload
        run_entry.pop("route_number", None)  # Remove duplicate route number
        run_entry.pop("route_id", None)  # Remove duplicate route id inside run row
        routes_map[route_id]["runs"].append(run_entry)  # Attach run to its route group
        routes_map[route_id]["total_runs"] += 1  # Increment route run count

    for route_data in routes_map.values():  # Sort runs inside each route group
        route_data["runs"].sort(
            key=lambda run: (run.get("date") or "", run.get("run_type") or "")
        )  # Stable order

    
    return {
        "school_id": school_id,  # School identifier
        "school_name": school.name if school else None,  # School name
        "total_routes": len(routes_map),  # Number of routes serving this school
        "routes": sorted(
            routes_map.values(),
            key=lambda route: route.get("route_number") or "",
        ),  # Stable route order
    }


# -----------------------------------------------------------
# - School route navigation summary
# - Returns routes assigned to one school
# -----------------------------------------------------------
def school_routes_summary(db: Session, school_id: int, operator_id: int | None = None):
    school_data = school_reports_summary(db, school_id, operator_id=operator_id)

    if school_data.get("school_name") is None:  # Guard unknown school requests
        return {"error": "School not found"}

    return {
        "school_id": school_data["school_id"],  # School identifier
        "school_name": school_data["school_name"],  # School display name
        "total_routes": school_data["total_routes"],  # Route count
        "routes": school_data["routes"],  # Route navigation list
    }


# -----------------------------------------------------------
# - School route run summary
# - Returns runs for one selected school route
# -----------------------------------------------------------
def school_route_runs_summary(db: Session, school_id: int, route_id: int, operator_id: int | None = None):
    school_data = school_reports_summary(db, school_id, operator_id=operator_id)

    if school_data.get("school_name") is None:  # Guard unknown school requests
        return {"error": "School not found"}

    selected_route = next(
        (route for route in school_data.get("routes", []) if route.get("route_id") == route_id),
        None,
    )  # Find requested route inside school payload

    if not selected_route:  # Reject routes not assigned to this school
        return {"error": "Route not found for school"}

    return {
        "school_id": school_data["school_id"],  # School identifier
        "school_name": school_data["school_name"],  # School display name
        "route": selected_route,  # Selected route payload
        "total_runs": selected_route.get("total_runs", 0),  # Route run count
    }


# -----------------------------------------------------------
# - School single run summary
# - Returns one selected run for one school
# -----------------------------------------------------------
def school_single_run_summary(db: Session, school_id: int, run_id: int, operator_id: int | None = None):
    school_data = school_reports_summary(db, school_id, operator_id=operator_id)

    if school_data.get("school_name") is None:  # Guard unknown school requests
        return {"error": "School not found"}

    for route in school_data.get("routes", []):  # Search all school routes
        selected_run = next(
            (run for run in route.get("runs", []) if run.get("run_id") == run_id),
            None,
        )  # Find requested run inside current route

        if selected_run:
            return {
                "school_id": school_data["school_id"],  # School identifier
                "school_name": school_data["school_name"],  # School display name
                "route": route,  # Selected route payload
                "run": selected_run,  # Single selected run payload
            }

    return {"error": "Run not found for school"}  # Reject unrelated runs


