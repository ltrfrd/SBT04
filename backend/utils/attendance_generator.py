# -----------------------------------------------------------
# Attendance Generator
# - Provide attendance-layer summaries using the existing report logic
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

from backend.models.run import Run  # Import locally to avoid circular dependency
from backend.models.run_event import RunEvent  # Run event history
from backend.models.associations import StudentRunAssignment  # Runtime assignments
from backend.utils.student_bus_absence import has_student_bus_absence  # Absence check
from backend.utils import attendance_generator  # Attendance utility functions
from backend.models import school as school_model  # School model
from fastapi import APIRouter, Depends, HTTPException, status  # FastAPI components
from sqlalchemy.orm import Session  # Database session type
from backend.models.school_attendance_verification import SchoolAttendanceVerification  # Read confirmation state
from database import get_db  # Shared DB dependency
from backend.utils import attendance_generator  # Attendance utility functions
from backend.routers import student_bus_absence  # Re-export planned absence router through attendance layer

router = APIRouter(
    prefix="/reports",  # Keep existing path stable during the rename phase
    tags=["Attendance"],  # Rename outward-facing API label
)

def driver_summary(db: Session, driver_id: int) -> dict:
    drv = db.get(driver_model.Driver, driver_id)  # Load driver
    if not drv:
        return {"error": "Driver not found"}  # Return stable missing-driver payload

    total_runs = (
        db.query(run_model.Run).filter(run_model.Run.driver_id == driver_id).count()
    )  # Count runs assigned to this driver

    total_charter_hours = (
        db.query(dispatch_model.Payroll)
        .filter(dispatch_model.Payroll.driver_id == driver_id)
        .with_entities(dispatch_model.Payroll.charter_hours)
        .all()
    )  # Load payroll hour fragments for this driver

    total_hours = sum(float(h[0]) for h in total_charter_hours if h[0])  # Sum non-null charter hours

    approved = (
        db.query(dispatch_model.Payroll)
        .filter(
            dispatch_model.Payroll.driver_id == driver_id,
            dispatch_model.Payroll.approved.is_(True),
        )
        .count()
    )  # Count approved payroll days

    pending = (
        db.query(dispatch_model.Payroll)
        .filter(
            dispatch_model.Payroll.driver_id == driver_id,
            dispatch_model.Payroll.approved.is_(False),
        )
        .count()
    )  # Count pending payroll days

    return {
        "driver_id": driver_id,
        "driver_name": drv.name,
        "total_runs": total_runs,
        "charter_hours": round(total_hours, 2),
        "approved_days": approved,
        "pending_days": pending,
    }  # Preserve existing payload shape


def route_summary(db: Session, route_id: int) -> dict:
    r = db.get(route_model.Route, route_id)  # Load route
    if not r:
        return {"error": "Route not found"}  # Return stable missing-route payload

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
                    "type": st.type.value,
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
        "unit_number": r.unit_number,
        "num_runs": r.num_runs,
        "driver_id": r.driver_id,
        "schools": schools_list,
        "stops": stops_list,
        "students": students_list,
        "total_runs": total_runs,
    }  # Preserve existing payload shape


def payroll_summary(db: Session, start: date, end: date) -> list:
    records = (
        db.query(dispatch_model.Payroll)
        .filter(
            dispatch_model.Payroll.work_date >= start,
            dispatch_model.Payroll.work_date <= end,
        )
        .all()
    )  # Load payroll rows inside the requested range

    summary = []
    for r in records:
        summary.append(
            {
                "driver_id": r.driver_id,
                "work_date": r.work_date,
                "charter_hours": float(r.charter_hours or 0),
                "approved": r.approved,
            }
        )  # Preserve existing payroll summary row shape
    return summary


def generate_attendance(
    db: Session,
    attendance_type: str,
    ref_id: int = None,
    start: date = None,
    end: date = None,
):
    if attendance_type == "driver" and ref_id:
        return driver_summary(db, ref_id)  # Return driver attendance summary
    if attendance_type == "route" and ref_id:
        return route_summary(db, ref_id)  # Return route attendance summary
    if attendance_type == "payroll" and start and end:
        return payroll_summary(db, start, end)  # Return payroll attendance summary
    if attendance_type == "run" and ref_id:
        return run_attendance_summary(db, ref_id)  # Run-level attendance summary
    if attendance_type == "date" and start and end:               # Date-based attendance request
        return date_summary(db, start, end)                       # Generate daily attendance summary
    if attendance_type == "school" and ref_id:                   # School-based attendance request
        return school_summary(db, ref_id)                        # Generate school attendance summary
    return {"error": "Invalid attendance type or parameters"}  # Preserve error-style contract
    

generate_report = generate_attendance  # Backward-compatible alias during the rename phase

# -----------------------------------------------------------
# Student Attendance Status
# - Derive unified attendance state from run events and absence
# -----------------------------------------------------------

def classify_student_attendance(assignment, events, absence_lookup):
    """Return attendance status for a student assignment."""  # Unified attendance state

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
# Run Attendance Summary
# - Build student and stop attendance view for a run
# -----------------------------------------------------------
def run_attendance_summary(db, run, assignments, events, absence_lookup):
    """Return attendance status for each student in a run."""  # Attendance-layer computation

    results = []  # Output list

    for assignment in assignments:
        status = classify_student_attendance(assignment, events, absence_lookup)  # Determine status

        results.append(
            {
                "student_id": assignment.student_id,  # Student identifier
                "student_name": assignment.student.name if assignment.student else None,  # Student display name
                "stop_id": assignment.stop_id,  # Assigned stop identifier
                "stop_name": assignment.stop.name if assignment.stop else None,  # Stop display name
                "status": status,  # Attendance status
            }
        )

    # -----------------------------------------------------------
    # Stop Attendance Totals
    # - Aggregate attendance by stop
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
    }  # Attendance counters

    for r in results:
        totals[r["status"]] += 1  # Increment status count

    return {
        "route_number": run.route.route_number if run.route else None,  # Operational route identifier
        "run_type": run.run_type,                                       # AM / PM run
        "students": results,                                            # Student-level attendance
        "totals": totals,                                               # Run totals
        "stop_totals": stop_totals,                                     # Stop-level totals
    }

# -----------------------------------------------------------  # Attendance summary by date
# Date attendance summary                                     # Dispatch daily attendance view
# -----------------------------------------------------------  # Section separator

def date_summary(db: Session, start: date, end: date):        # Build attendance for a specific date
    day_start = datetime.combine(start, time.min)             # Start of requested day
    day_end = datetime.combine(end, time.max)                 # End of requested day

    runs = (                                                  # Query runs within full-day range
        db.query(Run)                                         # Select runs
        .filter(Run.start_time >= day_start)                  # Lower datetime boundary
        .filter(Run.start_time <= day_end)                    # Upper datetime boundary
        .all()                                                # Execute query
    )

    results = []                                              # Collect run attendance summaries

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

        absence_lookup = {}                                           # Placeholder absence lookup for now

        summary = run_attendance_summary(                             # Build run attendance summary
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
        "runs": results,                                       # Run attendance payloads
    }
# -----------------------------------------------------------
# School Status Normalizer
# Convert operational attendance states into school-facing states
# -----------------------------------------------------------
def normalize_school_status(status: str) -> str:
    """Convert detailed attendance state to present/absent for schools."""  # School-safe status view

    if status in {"picked_up", "dropped_off"}:
        return "present"                                                     # Student rode the bus

    return "absent"                                                          # Hide operational absence reason

# -----------------------------------------------------------
# Attendance summary by school
# School attendance summary
# School-level attendance view
# -----------------------------------------------------------
# Section separator
def school_summary(db: Session, school_id: int):  # Build attendance for a school
    routes = (  # Load routes serving the school
        db.query(route_model.Route)  # Query routes
        .join(route_model.route_schools)  # Join route-school association
        .filter(route_model.route_schools.c.school_id == school_id)  # Keep only this school's routes
        .all()  # Execute query
    )

    school = (  # Load school once for final payload
        db.query(school_model.School)  # Query school table
        .filter(school_model.School.id == school_id)  # Match requested school
        .first()  # Execute query
    )

    results = []  # Collect run attendance summaries

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

            absence_lookup = {}  # Planned absence cache for current run

            if run.start_time:  # Only resolve absences when run date exists
                run_date = run.start_time.date()  # Authoritative run date

                for student in school_students:  # Preload planned absence for all school students on this run
                    absence_lookup[student.id] = has_student_bus_absence(
                        student.id,  # Student identifier
                        run,  # Current run object
                        db,  # Database session
                    )

            assignment_by_student_id = {
                assignment.student_id: assignment
                for assignment in assignments
            }  # Map runtime assignments by student id

            school_students_rows = []  # Final school-facing rows

            for student in school_students:                                              # Always build from full school roster
                assignment = assignment_by_student_id.get(student.id)                    # Runtime assignment if present

                if assignment:                                                           # Use runtime state when assigned
                    operational_status = classify_student_attendance(
                        assignment,
                        events,
                        absence_lookup,
                    )
                else:
                    operational_status = (
                        "planned_absent"
                        if absence_lookup.get(student.id)
                        else "expected"
                    )

                school_students_rows.append(
                    {
                        "student_id": student.id,                                        # Required for frontend/backend
                        "student_name": student.name,                                    # Display name
                        "status": normalize_school_status(operational_status),           # Present / absent
                        "is_assigned": assignment is not None                            # Controls button enable/disable
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

            # -------------------------------------------------------------------------
            # Build school-facing run payload                                     # include driver name
            # -------------------------------------------------------------------------
            assignment = assignment_by_student_id.get(student.id)                    # Runtime assignment if present

            verification_status = None                                               # Default school override

            if assignment:
                verification_status = assignment.school_status                       # Load saved school status

            if assignment:
                operational_status = classify_student_attendance(
                    assignment,
                    events,
                    absence_lookup,
                )
            else:
                operational_status = (
                    "planned_absent"
                    if absence_lookup.get(student.id)
                    else "expected"
                )

            final_status = verification_status if verification_status else normalize_school_status(operational_status)

            school_students_rows.append(
                {
                    "student_id": student.id,
                    "student_name": student.name,
                    "status": final_status,                                          # 🔥 persisted value
                    "is_assigned": assignment is not None,
                }
            )

    routes_map = {}  # Group runs by route number

    for run_data in results:  # Iterate through run attendance results
        route_number = run_data.get("route_number")  # Extract route identifier

        if route_number not in routes_map:  # Initialize route bucket if first time seen
            routes_map[route_number] = {
                "route_number": route_number,  # Route identifier
                "total_runs": 0,  # Counter for runs under this route
                "runs": [],  # Runs belonging to this route
            }

        run_entry = dict(run_data)  # Copy run payload
        run_entry.pop("route_number", None)  # Remove duplicate route number
        routes_map[route_number]["runs"].append(run_entry)  # Attach run to its route group
        routes_map[route_number]["total_runs"] += 1  # Increment route run count

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
# - Run Attendance Report
# - Return attendance status for each student in a run
# -----------------------------------------------------------
@router.get("/run/{run_id}", status_code=status.HTTP_200_OK)
def get_run_attendance(run_id: int, db: Session = Depends(get_db)):
    """Return student attendance status for a specific run."""  # Attendance-layer view

    run = db.query(Run).filter(Run.id == run_id).first()  # Load run
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")  # Preserve missing behavior

    assignments = (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .all()
    )  # Load run assignments

    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .all()
    )  # Load run events

    absence_lookup = {}  # Cache planned absences

    run_date = run.start_time.date()  # Authoritative run date

    for a in assignments:
        absence_lookup[a.student_id] = has_student_bus_absence(
            db,
            a.student_id,
            run_date,
            run.run_type,
        )  # Determine planned absence

    attendance = attendance_generator.run_attendance_summary(
        db,
        run,
        assignments,
        events,
        absence_lookup,
    )  # Build attendance list

    return {
        "run_id": run_id,  # Run identifier
        "run_type": run.run_type,  # AM/PM
        "student_count": len(attendance),  # Total students considered
        "students": attendance,  # Student attendance status list
    }