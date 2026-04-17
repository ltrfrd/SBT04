from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.models.operator import OperatorRouteAccess
from backend.models.route import Route
from backend.models.run import Run
from backend.models.school import School
from backend.models.stop import Stop
from backend.models.student import Student
from backend.utils.operator_scope import get_operator_scoped_route_or_404


# -----------------------------------------------------------
# School-domain planning scope helpers
# -----------------------------------------------------------
def planning_relationship_matches(
    *,
    primary_district_id: int | None,
    primary_operator_id: int | None,
    secondary_district_id: int | None,
    secondary_operator_id: int | None,
) -> bool:
    return (
        primary_district_id is not None
        and secondary_district_id is not None
        and primary_district_id == secondary_district_id
    )


def validate_planning_alignment(
    *,
    primary_district_id: int | None,
    primary_operator_id: int | None,
    secondary_district_id: int | None,
    secondary_operator_id: int | None,
    detail: str,
) -> None:
    if not planning_relationship_matches(
        primary_district_id=primary_district_id,
        primary_operator_id=primary_operator_id,
        secondary_district_id=secondary_district_id,
        secondary_operator_id=secondary_operator_id,
    ):
        raise HTTPException(status_code=400, detail=detail)


def accessible_route_filter(operator_id: int):
    return or_(
        Route.operator_id == operator_id,
        Route.operator_access.any(OperatorRouteAccess.operator_id == operator_id),
    )


def accessible_school_filter(operator_id: int):
    return or_(
        School.district_id.is_not(None),
        School.routes.any(accessible_route_filter(operator_id)),
    )


def accessible_student_filter(operator_id: int):
    return or_(
        Student.route.has(accessible_route_filter(operator_id)),
        Student.school.has(School.routes.any(accessible_route_filter(operator_id))),
    )


def get_route_with_schools_or_404(
    *,
    db: Session,
    route_id: int,
    operator_id: int,
    required_access: str = "read",
) -> Route:
    return get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator_id,
        required_access=required_access,
        options=[selectinload(Route.schools)],
    )


def get_school_for_planning_or_404(
    *,
    db: Session,
    school_id: int,
    operator_id: int,
    detail: str,
):
    school = (
        db.query(School)
        .filter(School.id == school_id)
        .filter(accessible_school_filter(operator_id))
        .first()
    )
    if not school:
        raise HTTPException(status_code=404, detail=detail)
    return school


def get_student_for_planning_or_404(
    *,
    db: Session,
    student_id: int,
    operator_id: int,
    detail: str,
):
    student = (
        db.query(Student)
        .filter(Student.id == student_id)
        .filter(accessible_student_filter(operator_id))
        .first()
    )
    if not student:
        raise HTTPException(status_code=404, detail=detail)
    return student


def validate_route_school_alignment(
    *,
    route_district_id: int | None,
    route_operator_id: int | None,
    school: School,
    detail: str = "School does not match route district",
) -> None:
    validate_planning_alignment(
        primary_district_id=route_district_id,
        primary_operator_id=route_operator_id,
        secondary_district_id=school.district_id,
        secondary_operator_id=None,
        detail=detail,
    )


def validate_route_school_links(
    *,
    route_district_id: int | None,
    route_operator_id: int | None,
    schools: list[School],
    detail: str = "School does not match route district",
) -> None:
    for school in schools:
        validate_route_school_alignment(
            route_district_id=route_district_id,
            route_operator_id=route_operator_id,
            school=school,
            detail=detail,
        )


def get_schools_for_route_attachment_or_404(
    *,
    db: Session,
    school_ids: list[int],
) -> list[School]:
    schools = (
        db.query(School)
        .filter(School.id.in_(school_ids))
        .all()
    )
    if len(schools) != len(set(school_ids)):
        raise HTTPException(status_code=404, detail="School not found")
    return schools


def get_route_run_or_404(
    *,
    route_id: int,
    run_id: int,
    db: Session,
) -> Run:
    run = (
        db.query(Run)
        .options(joinedload(Run.route), joinedload(Run.driver))
        .filter(Run.id == run_id)
        .first()
    )
    if not run or run.route_id != route_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def get_route_stop_or_404(
    *,
    route_id: int,
    stop_id: int,
    db: Session,
) -> Stop:
    stop = (
        db.query(Stop)
        .options(joinedload(Stop.run))
        .filter(Stop.id == stop_id)
        .first()
    )
    stop_route_id = None
    if stop is not None:
        stop_route_id = stop.route_id if stop.route_id is not None else stop.run.route_id if stop.run else None

    if not stop or stop_route_id != route_id:
        raise HTTPException(status_code=404, detail="Stop not found")
    return stop


def get_route_student_or_404(
    *,
    route_id: int,
    student_id: int,
    db: Session,
) -> Student:
    student = (
        db.query(Student)
        .options(joinedload(Student.school))
        .filter(Student.id == student_id)
        .first()
    )
    if not student or student.route_id != route_id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student
