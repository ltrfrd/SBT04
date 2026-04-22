# -----------------------------------------------------------
# - Reports generator
# - Build reports-layer summaries behind canonical /reports endpoints
# -----------------------------------------------------------
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from backend.models import (
    associations as assoc_model,
    dispatch as dispatch_model,
    driver as driver_model,
    route as route_model,
    run as run_model,
    student as student_model,
)
from backend.models.run import Run
from backend.models.run_event import RunEvent
from backend.models.associations import StudentRunAssignment
from backend.models.run_verification import RunVerification
from backend.models.school_attendance_verification import SchoolAttendanceVerification
from backend.models.yard import Yard
from backend.models import school as school_model
from backend.utils.planning_scope import (
    accessible_route_filter,
    accessible_school_filter,
    execution_route_filter,
    yards_accessible_route_filter,
    yards_accessible_school_filter,
)
from backend.utils.route_driver_assignment import get_route_driver_name, resolve_route_driver_assignment
from backend.utils.run_verification import (
    assignment_mismatch,
    assignment_operational_school_truth,
    assignment_school_truth,
    get_run_verification,
    normalize_run_direction,
)
from backend.utils.student_bus_absence import has_student_bus_absence


def driver_summary(db: Session, driver_id: int, operator_id: int | None = None) -> dict:
    driver_query = db.query(driver_model.Driver).filter(driver_model.Driver.id == driver_id)
    if operator_id is not None:
        driver_query = driver_query.join(driver_model.Driver.yard).filter(Yard.operator_id == operator_id)
    drv = driver_query.first()
    if not drv:
        return {"error": "Driver not found"}

    total_charter_hours = (
        db.query(dispatch_model.DispatchRecord)
        .filter(dispatch_model.DispatchRecord.driver_id == driver_id)
        .with_entities(dispatch_model.DispatchRecord.charter_hours)
        .all()
    )
    total_hours = sum(float(hours[0]) for hours in total_charter_hours if hours[0])

    approved = (
        db.query(dispatch_model.DispatchRecord)
        .filter(
            dispatch_model.DispatchRecord.driver_id == driver_id,
            dispatch_model.DispatchRecord.approved.is_(True),
        )
        .count()
    )
    pending = (
        db.query(dispatch_model.DispatchRecord)
        .filter(
            dispatch_model.DispatchRecord.driver_id == driver_id,
            dispatch_model.DispatchRecord.approved.is_(False),
        )
        .count()
    )

    return {
        "driver_id": driver_id,
        "driver_name": drv.name,
        "charter_hours": round(total_hours, 2),
        "approved_days": approved,
        "pending_days": pending,
    }


def route_summary_execution(db: Session, route_id: int) -> dict:
    route = db.get(route_model.Route, route_id)
    if not route:
        return {"error": "Route not found"}
    assigned_bus = route.bus

    active_driver_id = None
    try:
        active_assignment = resolve_route_driver_assignment(route)
        active_driver_id = active_assignment.driver_id
    except ValueError:
        active_assignment = None

    schools_list = [{"id": school.id, "name": school.name} for school in route.schools]

    stops_list = []
    for run in route.runs:
        for stop in sorted(run.stops, key=lambda row: row.sequence):
            stops_list.append(
                {
                    "id": stop.id,
                    "run_id": run.id,
                    "sequence": stop.sequence,
                    "type": stop.type.value if hasattr(stop.type, "value") else str(stop.type),
                }
            )

    route_run_ids = [run.id for run in route.runs]
    assignments = []
    if route_run_ids:
        assignments = (
            db.query(assoc_model.StudentRunAssignment)
            .filter(assoc_model.StudentRunAssignment.run_id.in_(route_run_ids))
            .all()
        )

    students_by_id = {}
    for assignment in assignments:
        student = db.get(student_model.Student, assignment.student_id)
        if not student or student.id in students_by_id:
            continue
        students_by_id[student.id] = {
            "id": student.id,
            "name": student.name,
            "grade": student.grade,
        }

    return {
        "route_id": route_id,
        "route_number": route.route_number,
        "bus_id": assigned_bus.id if assigned_bus else None,
        "bus_unit_number": assigned_bus.unit_number if assigned_bus else None,
        "bus_license_plate": assigned_bus.license_plate if assigned_bus else None,
        "bus_capacity": assigned_bus.capacity if assigned_bus else None,
        "bus_size": assigned_bus.size if assigned_bus else None,
        "num_runs": route.num_runs,
        "driver_id": active_driver_id,
        "active_driver_id": active_driver_id,
        "active_driver_name": get_route_driver_name(route),
        "schools": schools_list,
        "stops": stops_list,
        "students": list(students_by_id.values()),
        "total_runs": db.query(run_model.Run).filter(run_model.Run.route_id == route_id).count(),
    }


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
        query = query.filter(Yard.operator_id == operator_id)

    records = (
        query
        .order_by(
            driver_model.Driver.name.asc(),
            dispatch_model.DispatchRecord.work_date.asc(),
            dispatch_model.DispatchRecord.id.asc(),
        )
        .all()
    )

    driver_records = {}
    for record in records:
        driver_name = record.driver.name if record.driver else None
        if record.driver_id not in driver_records:
            driver_records[record.driver_id] = {
                "driver_id": record.driver_id,
                "driver_name": driver_name,
                "records": [],
            }
        driver_records[record.driver_id]["records"].append(
            {
                "work_date": record.work_date,
                "charter_hours": float(record.charter_hours or 0),
                "approved": record.approved,
            }
        )
    return list(driver_records.values())


def generate_reports(
    db: Session,
    reports_type: str,
    ref_id: int = None,
    start: date = None,
    end: date = None,
    operator_id: int | None = None,
    yard_ids: list[int] | None = None,
):
    if reports_type == "driver" and ref_id:
        return driver_summary(db, ref_id, operator_id=operator_id)
    if reports_type == "route" and ref_id:
        return route_summary_execution(db, ref_id)
    if reports_type == "dispatch" and ref_id and start and end:
        return dispatch_summary(db, ref_id, start, end, operator_id=operator_id)
    if reports_type == "run" and ref_id:
        run = db.get(Run, ref_id)
        if not run:
            return {"error": "Run not found"}
        assignments = db.query(StudentRunAssignment).filter(StudentRunAssignment.run_id == run.id).all()
        events = db.query(RunEvent).filter(RunEvent.run_id == run.id).all()
        absence_lookup = {
            assignment.student_id: has_student_bus_absence(assignment.student_id, run, db)
            for assignment in assignments
        }
        return run_reports_summary(db, run, assignments, events, absence_lookup)
    if reports_type == "date" and start and end:
        return date_summary_execution(db, start, end, operator_id=operator_id)
    if reports_type == "school" and ref_id:
        return school_reports_summary_execution(db, ref_id, yard_ids=yard_ids, operator_id=operator_id)
    return {"error": "Invalid reports type or parameters"}


def classify_student_status(assignment, events, absence_lookup):
    student_id = assignment.student_id

    if absence_lookup.get(student_id):
        return "planned_absent"
    if assignment.picked_up and assignment.dropped_off:
        return "dropped_off"
    if assignment.picked_up:
        return "picked_up"
    for event in events:
        if event.student_id == student_id and event.event_type == "STUDENT_NO_SHOW":
            return "no_show"
    return "expected"


def run_reports_summary(db, run, assignments, events, absence_lookup):
    results = []
    for assignment in assignments:
        status = classify_student_status(assignment, events, absence_lookup)
        results.append(
            {
                "student_id": assignment.student_id,
                "student_name": assignment.student.name if assignment.student else None,
                "stop_id": assignment.stop_id,
                "stop_name": assignment.stop.name if assignment.stop else None,
                "status": status,
            }
        )

    stop_totals = {}
    for result in results:
        stop_id = result["stop_id"]
        if stop_id not in stop_totals:
            stop_totals[stop_id] = {
                "stop_name": result["stop_name"],
                "planned_absent": 0,
                "picked_up": 0,
                "dropped_off": 0,
                "no_show": 0,
                "expected": 0,
            }
        stop_totals[stop_id][result["status"]] += 1

    totals = {
        "planned_absent": 0,
        "picked_up": 0,
        "dropped_off": 0,
        "no_show": 0,
        "expected": 0,
    }
    for result in results:
        totals[result["status"]] += 1

    return {
        "route_number": run.route.route_number if run.route else None,
        "run_type": run.run_type,
        "students": results,
        "totals": totals,
        "stop_totals": stop_totals,
    }


def date_summary_execution(db: Session, start: date, end: date, operator_id: int | None = None):
    day_start = datetime.combine(start, time.min)
    day_end = datetime.combine(end, time.max)

    runs_query = (
        db.query(Run)
        .filter(Run.start_time >= day_start)
        .filter(Run.start_time <= day_end)
    )
    if operator_id is not None:
        route_filter = execution_route_filter(db=db, operator_id=operator_id)
        accessible_route_ids = db.query(route_model.Route.id).filter(route_filter).scalar_subquery()
        runs_query = runs_query.filter(Run.route_id.in_(accessible_route_ids))

    runs = runs_query.all()
    results = []

    for run in runs:
        assignments = db.query(StudentRunAssignment).filter(StudentRunAssignment.run_id == run.id).all()
        events = db.query(RunEvent).filter(RunEvent.run_id == run.id).all()
        absence_lookup = {
            assignment.student_id: has_student_bus_absence(assignment.student_id, run, db)
            for assignment in assignments
        }
        summary = run_reports_summary(db, run, assignments, events, absence_lookup)
        if summary and "error" not in summary:
            results.append(summary)

    return {
        "date_range": {"start": str(start), "end": str(end)},
        "total_runs": len(results),
        "runs": results,
    }


def normalize_school_status(status: str) -> str:
    if status in {"picked_up", "dropped_off"}:
        return "present"
    return "absent"


def _serialize_run_verification(*, verification: RunVerification | None) -> dict:
    if verification is None:
        return {
            "status": "pending",
            "mismatch_count": 0,
            "is_confirmed": False,
            "confirmed_at": None,
            "confirmed_by": None,
        }
    return {
        "status": verification.status,
        "mismatch_count": verification.mismatch_count,
        "is_confirmed": verification.status == "confirmed",
        "confirmed_at": verification.confirmed_at,
        "confirmed_by": None,
    }


def _build_school_student_row(
    *,
    assignment: StudentRunAssignment,
    direction: str | None,
    operational_reports_status: str,
) -> dict:
    effective_direction = direction or "AM"
    operational_truth = assignment_operational_school_truth(
        assignment=assignment,
        direction=effective_direction,
    )
    operational_status = "present" if operational_truth else "absent"
    school_status = assignment.school_status

    mismatch = False
    mismatch_reason = None
    if direction in {"AM", "PM"}:
        mismatch, mismatch_reason = assignment_mismatch(
            assignment=assignment,
            direction=direction,
        )

    if direction == "PM":
        status = "present" if assignment.released_by_school else "absent"
    else:
        status = school_status if school_status in {"present", "absent"} else operational_status

    return {
        "student_id": assignment.student_id,
        "student_name": assignment.student.name if assignment.student else None,
        "status": status,
        "operational_status": operational_status,
        "school_status": school_status,
        "school_truth": assignment_school_truth(assignment=assignment, direction=effective_direction),
        "reports_status": operational_reports_status,
        "mismatch": mismatch,
        "mismatch_reason": mismatch_reason,
        "released_by_school": assignment.released_by_school,
        "boarded_by_driver": assignment.boarded_by_driver,
        "is_assigned": True,
    }


def school_reports_summary_execution(
    db: Session,
    school_id: int,
    yard_ids: list[int] | None = None,
    operator_id: int | None = None,
):
    school_query = db.query(school_model.School).filter(school_model.School.id == school_id)
    if yard_ids is not None:
        school_query = school_query.filter(yards_accessible_school_filter(yard_ids))
    elif operator_id is not None:
        school_query = school_query.filter(accessible_school_filter(operator_id))
    else:
        return {"error": "School not found"}

    school = school_query.first()
    if not school:
        return {"error": "School not found"}

    routes_query = (
        db.query(route_model.Route)
        .join(route_model.route_schools)
        .filter(route_model.route_schools.c.school_id == school_id)
    )
    if yard_ids is not None:
        routes_query = routes_query.filter(yards_accessible_route_filter(yard_ids))
    elif operator_id is not None:
        routes_query = routes_query.filter(accessible_route_filter(operator_id))
    else:
        return {"error": "School not found"}

    routes = routes_query.all()
    results = []

    for route in routes:
        runs = db.query(Run).filter(Run.route_id == route.id).all()
        for run in runs:
            assignments = db.query(StudentRunAssignment).filter(StudentRunAssignment.run_id == run.id).all()
            events = db.query(RunEvent).filter(RunEvent.run_id == run.id).all()
            direction = normalize_run_direction(run.run_type)
            visible_assignments = [
                assignment
                for assignment in assignments
                if assignment.student and assignment.student.school_id == school_id
            ]

            absence_lookup = {}
            if run.start_time:
                for assignment in visible_assignments:
                    absence_lookup[assignment.student_id] = has_student_bus_absence(
                        assignment.student_id,
                        run,
                        db,
                    )

            school_students_rows = []
            for assignment in visible_assignments:
                operational_reports_status = classify_student_status(
                    assignment,
                    events,
                    absence_lookup,
                )
                school_students_rows.append(
                    _build_school_student_row(
                        assignment=assignment,
                        direction=direction,
                        operational_reports_status=operational_reports_status,
                    )
                )
            school_students_rows.sort(key=lambda row: (row.get("student_name") or "").lower())

            if direction == "AM":
                mismatch_count = sum(
                    1
                    for assignment in visible_assignments
                    if assignment_mismatch(assignment=assignment, direction=direction)[0]
                )
                missing_school_truth = any(
                    assignment_school_truth(assignment=assignment, direction=direction) is None
                    for assignment in visible_assignments
                )
                school_confirmation = (
                    db.query(SchoolAttendanceVerification)
                    .filter(
                        SchoolAttendanceVerification.school_id == school_id,
                        SchoolAttendanceVerification.run_id == run.id,
                    )
                    .first()
                )
                confirmation = {
                    "status": "confirmed" if school_confirmation is not None else (
                        "pending" if missing_school_truth else ("mismatch" if mismatch_count > 0 else "resolved")
                    ),
                    "mismatch_count": mismatch_count,
                    "is_confirmed": school_confirmation is not None,
                    "confirmed_at": school_confirmation.confirmed_at if school_confirmation is not None else None,
                    "confirmed_by": school_confirmation.confirmed_by if school_confirmation is not None else None,
                }
            else:
                verification = None
                if direction is not None:
                    verification = get_run_verification(
                        db=db,
                        run_id=run.id,
                        direction=direction,
                    )
                confirmation = _serialize_run_verification(verification=verification)

            results.append(
                {
                    "id": run.id,
                    "run_id": run.id,
                    "route_id": route.id,
                    "route_number": route.route_number,
                    "driver_name": run.driver.name if run.driver else "Unassigned",
                    "run_type": run.run_type,
                    "direction": direction,
                    "date": run.start_time.date().isoformat() if run.start_time else None,
                    "students": school_students_rows,
                    "total_students": len(school_students_rows),
                    "total_present": sum(1 for row in school_students_rows if row.get("status") == "present"),
                    "total_absent": sum(1 for row in school_students_rows if row.get("status") == "absent"),
                    "confirmation": confirmation,
                }
            )

    routes_map = {}
    for run_data in results:
        route_id = run_data.get("route_id")
        route_number = run_data.get("route_number")
        if route_id not in routes_map:
            routes_map[route_id] = {
                "route_id": route_id,
                "route_number": route_number,
                "total_runs": 0,
                "runs": [],
            }
        run_entry = dict(run_data)
        run_entry.pop("route_number", None)
        run_entry.pop("route_id", None)
        routes_map[route_id]["runs"].append(run_entry)
        routes_map[route_id]["total_runs"] += 1

    for route_data in routes_map.values():
        route_data["runs"].sort(key=lambda run: (run.get("date") or "", run.get("run_type") or ""))

    return {
        "school_id": school_id,
        "school_name": school.name if school else None,
        "total_routes": len(routes_map),
        "routes": sorted(routes_map.values(), key=lambda route: route.get("route_number") or ""),
    }


def school_routes_summary(
    db: Session,
    school_id: int,
    yard_ids: list[int] | None = None,
    operator_id: int | None = None,
):
    school_data = school_reports_summary_execution(db, school_id, yard_ids=yard_ids, operator_id=operator_id)
    if school_data.get("school_name") is None:
        return {"error": "School not found"}
    return {
        "school_id": school_data["school_id"],
        "school_name": school_data["school_name"],
        "total_routes": school_data["total_routes"],
        "routes": school_data["routes"],
    }


def school_route_runs_summary(
    db: Session,
    school_id: int,
    route_id: int,
    yard_ids: list[int] | None = None,
    operator_id: int | None = None,
):
    school_data = school_reports_summary_execution(db, school_id, yard_ids=yard_ids, operator_id=operator_id)
    if school_data.get("school_name") is None:
        return {"error": "School not found"}

    selected_route = next(
        (route for route in school_data.get("routes", []) if route.get("route_id") == route_id),
        None,
    )
    if not selected_route:
        return {"error": "Route not found for school"}

    return {
        "school_id": school_data["school_id"],
        "school_name": school_data["school_name"],
        "route": selected_route,
        "total_runs": selected_route.get("total_runs", 0),
    }


def school_single_run_summary(
    db: Session,
    school_id: int,
    run_id: int,
    yard_ids: list[int] | None = None,
    operator_id: int | None = None,
):
    school_data = school_reports_summary_execution(db, school_id, yard_ids=yard_ids, operator_id=operator_id)
    if school_data.get("school_name") is None:
        return {"error": "School not found"}

    for route in school_data.get("routes", []):
        selected_run = next(
            (run for run in route.get("runs", []) if run.get("run_id") == run_id),
            None,
        )
        if selected_run:
            return {
                "school_id": school_data["school_id"],
                "school_name": school_data["school_name"],
                "route": route,
                "run": selected_run,
            }

    return {"error": "Run not found for school"}
