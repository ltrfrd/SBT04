from sqlalchemy.orm import Session
from datetime import date
from backend.models import (
    driver as driver_model,
    route as route_model,
    run as run_model,
    payroll as payroll_model,
    associations as assoc_model,
    student as student_model,
)


def driver_summary(db: Session, driver_id: int) -> dict:
    drv = db.get(driver_model.Driver, driver_id)
    if not drv:
        return {"error": "Driver not found"}

    total_runs = (
        db.query(run_model.Run).filter(run_model.Run.driver_id == driver_id).count()
    )

    total_charter_hours = (
        db.query(payroll_model.Payroll)
        .filter(payroll_model.Payroll.driver_id == driver_id)
        .with_entities(payroll_model.Payroll.charter_hours)
        .all()
    )

    total_hours = sum(float(h[0]) for h in total_charter_hours if h[0])

    approved = (
        db.query(payroll_model.Payroll)
        .filter(
            payroll_model.Payroll.driver_id == driver_id,
            payroll_model.Payroll.approved.is_(True),
        )
        .count()
    )

    pending = (
        db.query(payroll_model.Payroll)
        .filter(
            payroll_model.Payroll.driver_id == driver_id,
            payroll_model.Payroll.approved.is_(False),
        )
        .count()
    )

    return {
        "driver_id": driver_id,
        "driver_name": drv.name,
        "total_runs": total_runs,
        "charter_hours": round(total_hours, 2),
        "approved_days": approved,
        "pending_days": pending,
    }


def route_summary(db: Session, route_id: int) -> dict:
    r = db.get(route_model.Route, route_id)
    if not r:
        return {"error": "Route not found"}

    schools_list = [{"id": s.id, "name": s.name} for s in r.schools]

    stops_list = []
    for run in r.runs:
        run_stops = sorted(run.stops, key=lambda st: st.sequence)
        for st in run_stops:
            stops_list.append(
                {
                    "id": st.id,
                    "run_id": run.id,
                    "sequence": st.sequence,
                    "type": st.type.value,
                }
            )

    route_run_ids = [run.id for run in r.runs]
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

    students_list = list(students_by_id.values())

    total_runs = db.query(run_model.Run).filter(run_model.Run.route_id == route_id).count()

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
    }


def payroll_summary(db: Session, start: date, end: date) -> list:
    records = (
        db.query(payroll_model.Payroll)
        .filter(
            payroll_model.Payroll.work_date >= start,
            payroll_model.Payroll.work_date <= end,
        )
        .all()
    )

    summary = []
    for r in records:
        summary.append(
            {
                "driver_id": r.driver_id,
                "work_date": r.work_date,
                "charter_hours": float(r.charter_hours or 0),
                "approved": r.approved,
            }
        )
    return summary


def generate_report(
    db: Session,
    report_type: str,
    ref_id: int = None,
    start: date = None,
    end: date = None,
):
    if report_type == "driver" and ref_id:
        return driver_summary(db, ref_id)
    if report_type == "route" and ref_id:
        return route_summary(db, ref_id)
    if report_type == "payroll" and start and end:
        return payroll_summary(db, start, end)
    return {"error": "Invalid report type or parameters"}
