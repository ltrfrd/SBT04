# ===========================================================
# backend/routers/student.py - FleetOS Student Router
# -----------------------------------------------------------
# Handles CRUD operations for students and route/school lookups.
# ===========================================================
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from backend import schemas
from backend.models.district import District
from backend.models.operator import Operator
from backend.models import associations as assoc_model
from backend.models import route as route_model
from backend.models import run as run_model
from backend.models import school as school_model
from backend.models import stop as stop_model
from backend.models import student as student_model
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_record_or_404
from backend.utils.planning_scope import (
    accessible_student_filter,
    get_route_with_schools_or_404,
    get_school_for_planning_or_404,
    get_student_for_planning_or_404,
    validate_planning_alignment,
    validate_route_school_alignment,
)
from backend.utils.run_setup import (
    ensure_run_is_planned_for_setup,
    get_run_stop_context_or_404,
    get_stop_or_404,
)


router = APIRouter(
    prefix="/students",
    tags=["Students"],
)
district_router = APIRouter(
    prefix="/districts",
    tags=["Students"],
)

def _validate_student_school_planning_alignment(
    *,
    student_district_id: int | None,
    student_operator_id: int,
    school: school_model.School,
) -> None:
    validate_planning_alignment(
        primary_district_id=student_district_id,
        primary_operator_id=student_operator_id,
        secondary_district_id=school.district_id,
        secondary_operator_id=school.operator_id,
        detail="School does not match student district",
    )


def _validate_student_route_planning_alignment(
    *,
    student_district_id: int | None,
    student_operator_id: int,
    route: route_model.Route,
) -> None:
    validate_planning_alignment(
        primary_district_id=student_district_id,
        primary_operator_id=student_operator_id,
        secondary_district_id=route.district_id,
        secondary_operator_id=route.operator_id,
        detail="Student does not match route district",
    )


def _get_route_with_schools(
    route_id: int,
    db: Session,
    operator_id: int,
    required_access: str = "read",
) -> route_model.Route:
    return get_route_with_schools_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator_id,
        required_access=required_access,
    )


def _validate_route_school_membership(route: route_model.Route, school_id: int) -> None:
    route_school_ids = {school.id for school in route.schools}
    if school_id not in route_school_ids:
        raise HTTPException(status_code=400, detail="School is not assigned to the run route")


def _get_school_for_planning_or_404(
    *,
    db: Session,
    school_id: int,
    operator_id: int,
    detail: str,
) -> school_model.School:
    return get_school_for_planning_or_404(
        db=db,
        school_id=school_id,
        operator_id=operator_id,
        detail=detail,
    )


def _get_student_for_planning_or_404(
    *,
    db: Session,
    student_id: int,
    operator_id: int,
    detail: str,
) -> student_model.Student:
    return get_student_for_planning_or_404(
        db=db,
        student_id=student_id,
        operator_id=operator_id,
        detail=detail,
    )


def _validate_compatibility_student_create_target(
    *,
    school: school_model.School,
    student_district_id: int | None,
    route_id: int | None,
    stop_id: int | None,
    operator_id: int,
    db: Session,
) -> tuple[route_model.Route | None, stop_model.Stop | None]:
    route = (
        _get_route_with_schools(route_id, db, operator_id, "read")
        if route_id is not None else None
    )
    stop = get_stop_or_404(stop_id, db) if stop_id is not None else None

    if stop is not None:
        run = stop.run
        if run is None:
            raise HTTPException(status_code=400, detail="Stop does not belong to route")
        if run.route is None:
            raise HTTPException(status_code=404, detail="Route not found")
        ensure_run_is_planned_for_setup(run)

        if route is not None and run.route_id != route.id:
            raise HTTPException(status_code=400, detail="Stop does not belong to route")

        if route is None:
            route = _get_route_with_schools(run.route_id, db, operator_id, "read")

    _validate_student_school_planning_alignment(
        student_district_id=student_district_id,
        student_operator_id=operator_id,
        school=school,
    )

    if route is not None:
        _validate_student_route_planning_alignment(
            student_district_id=student_district_id,
            student_operator_id=operator_id,
            route=route,
        )
        validate_route_school_alignment(
            route_district_id=route.district_id,
            route_operator_id=route.operator_id,
            school=school,
        )

    return route, stop


def _validate_student_assignment_target(
    *,
    student: student_model.Student,
    route_id: int,
    run_id: int,
    stop_id: int,
    operator_id: int,
    db: Session,
) -> tuple[route_model.Route, run_model.Run, stop_model.Stop]:
    route = _get_route_with_schools(route_id, db, operator_id, "read")
    run, stop = get_run_stop_context_or_404(
        run_id=run_id,
        stop_id=stop_id,
        db=db,
        require_planned=True,
    )

    if run.route_id != route.id:
        raise HTTPException(status_code=400, detail="Run does not belong to route")

    _validate_student_route_planning_alignment(
        student_district_id=student.district_id,
        student_operator_id=student.operator_id,
        route=route,
    )
    validate_route_school_alignment(
        route_district_id=route.district_id,
        route_operator_id=route.operator_id,
        school=student.school,
    )
    _validate_route_school_membership(route, student.school_id)

    return route, run, stop


def _sync_student_assignment_rows_for_assignment_move(
    *,
    student: student_model.Student,
    target_route: route_model.Route,
    target_run: run_model.Run,
    target_stop: stop_model.Stop,
    db: Session,
) -> None:
    assignments = (
        db.query(assoc_model.StudentRunAssignment)
        .join(run_model.Run, assoc_model.StudentRunAssignment.run_id == run_model.Run.id)
        .filter(assoc_model.StudentRunAssignment.student_id == student.id)
        .all()
    )

    target_assignment = None

    for assignment in assignments:
        run = assignment.run
        is_historical = run.end_time is not None or run.is_completed

        if assignment.run_id == target_run.id:
            target_assignment = assignment

        if is_historical:
            continue

        if run.route_id != target_route.id:
            db.delete(assignment)

    if target_assignment is None:
        target_assignment = assoc_model.StudentRunAssignment(
            student_id=student.id,
            run_id=target_run.id,
            stop_id=target_stop.id,
        )
        db.add(target_assignment)
    else:
        target_assignment.stop_id = target_stop.id

    db.flush()


def _update_student_record(
    *,
    student: student_model.Student,
    payload: schemas.StopStudentUpdate,
    operator_id: int,
    db: Session,
    authoritative_route_id: int | None = None,
    authoritative_stop: stop_model.Stop | None = None,
    assignment: assoc_model.StudentRunAssignment | None = None,
):
    updates = payload.model_dump(exclude_unset=True)

    target_route_id = authoritative_route_id if authoritative_route_id is not None else updates.get("route_id", student.route_id)
    target_stop_id = authoritative_stop.id if authoritative_stop is not None else updates.get("stop_id", student.stop_id)
    target_school_id = updates.get("school_id", student.school_id)

    route = None
    if target_route_id is not None:
        route = _get_route_with_schools(target_route_id, db, operator_id, "read")

    school = _get_school_for_planning_or_404(
        db=db,
        operator_id=operator_id,
        detail="School not found",
        school_id=target_school_id,
    )

    _validate_student_school_planning_alignment(
        student_district_id=student.district_id,
        student_operator_id=student.operator_id,
        school=school,
    )

    if route is not None:
        _validate_student_route_planning_alignment(
            student_district_id=student.district_id,
            student_operator_id=student.operator_id,
            route=route,
        )
        validate_route_school_alignment(
            route_district_id=route.district_id,
            route_operator_id=route.operator_id,
            school=school,
        )
        _validate_route_school_membership(route, school.id)

    stop = None
    if target_stop_id is not None:
        stop = db.get(stop_model.Stop, target_stop_id)
        if not stop:
            raise HTTPException(status_code=404, detail="Stop not found")

    if route is not None and stop is not None and stop.run and stop.run.route_id != route.id:
        raise HTTPException(status_code=400, detail="Stop does not belong to route")

    for field_name in ("name", "grade", "school_id"):
        if field_name in updates:
            setattr(student, field_name, updates[field_name])

    if authoritative_route_id is not None:
        student.route_id = authoritative_route_id

    if authoritative_stop is not None:
        student.stop_id = authoritative_stop.id

    if assignment is not None and authoritative_stop is not None:
        assignment.stop_id = authoritative_stop.id

    db.flush()
    db.refresh(student)
    return student


@router.post(
    "/",
    response_model=schemas.StudentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create student (secondary compatibility)",
    description=(
        "Secondary compatibility endpoint for creating a student record directly. "
        "Preferred layered workflow is POST /runs/{run_id}/stops/{stop_id}/students so route and stop context are inherited automatically. "
        "Optional route_id and stop_id fields are legacy planning pointers for compatibility only. "
        "When stop context is supplied, only planned runs can be modified."
    ),
    response_description="Created student",
)
def create_student(
    student: schemas.StudentCompatibilityCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    school = _get_school_for_planning_or_404(
        db=db,
        operator_id=operator.id,
        detail="School not found",
        school_id=student.school_id,
    )

    _validate_compatibility_student_create_target(
        school=school,
        student_district_id=student.district_id,
        route_id=student.route_id,
        stop_id=student.stop_id,
        operator_id=operator.id,
        db=db,
    )

    payload = student.model_dump()
    payload["school_id"] = school.id
    new_student = student_model.Student(
        **payload,
        operator_id=operator.id,
    )
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


@district_router.post(
    "/{district_id}/students",
    response_model=schemas.StudentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create student under district",
    description=(
        "Create a student under the selected district context. "
        "The path district_id is authoritative and operator context is preserved for compatibility."
    ),
    response_description="Created student",
)
def create_student_for_district(
    district_id: int,
    student: schemas.StudentCompatibilityCreate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    district = db.get(District, district_id)
    if not district:
        raise HTTPException(status_code=404, detail="District not found")

    school = _get_school_for_planning_or_404(
        db=db,
        operator_id=operator.id,
        detail="School not found",
        school_id=student.school_id,
    )

    _validate_compatibility_student_create_target(
        school=school,
        student_district_id=district_id,
        route_id=student.route_id,
        stop_id=student.stop_id,
        operator_id=operator.id,
        db=db,
    )

    payload = student.model_dump(exclude={"district_id"})
    payload["school_id"] = school.id
    new_student = student_model.Student(
        **payload,
        district_id=district_id,
        operator_id=operator.id,
    )
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    return new_student


@router.get(
    "/",
    response_model=List[schemas.StudentOut],
    summary="List students",
    description="Return all registered student records.",
    response_description="Student list",
)
def get_students(
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    return (
        db.query(student_model.Student)
        .filter(accessible_student_filter(operator.id))
        .all()
    )


@router.get(
    "/{student_id}",
    response_model=schemas.StudentOut,
    summary="Get student",
    description="Return a single student record by id.",
    response_description="Student record",
)
def get_student(
    student_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    student = (
        db.query(student_model.Student)
        .filter(student_model.Student.id == student_id)
        .filter(accessible_student_filter(operator.id))
        .first()
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@router.put(
    "/{student_id}/assignment",
    response_model=schemas.StudentOut,
    summary="Update student assignment (maintenance)",
    description=(
        "Maintenance endpoint for correcting or moving a student to a different route, run, and stop after initial setup. "
        "This is not the normal creation workflow; preferred initial setup is POST /runs/{run_id}/stops/{stop_id}/students. "
        "Runtime assignment rows are synchronized safely when the move is valid. "
        "Only planned runs can be modified."
    ),
    response_description="Updated student assignment",
)
def update_student_assignment(
    student_id: int,
    assignment_in: schemas.StudentAssignmentUpdate,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    student = _get_student_for_planning_or_404(
        db=db,
        operator_id=operator.id,
        detail="Student not found",
        student_id=student_id,
    )

    target_route, target_run, target_stop = _validate_student_assignment_target(
        student=student,
        route_id=assignment_in.route_id,
        run_id=assignment_in.run_id,
        stop_id=assignment_in.stop_id,
        operator_id=operator.id,
        db=db,
    )

    student.route_id = target_route.id
    student.stop_id = target_stop.id

    _sync_student_assignment_rows_for_assignment_move(
        student=student,
        target_route=target_route,
        target_run=target_run,
        target_stop=target_stop,
        db=db,
    )

    db.commit()
    db.refresh(student)
    return student


@router.delete(
    "/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete student entirely",
    description=(
        "Permanently remove the student record from the system. "
        "This is full system-wide student deletion, not the normal run-stop workflow removal action."
    ),
    response_description="Student permanently deleted",
)
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    student = get_operator_scoped_record_or_404(
        db=db,
        model=student_model.Student,
        record_id=student_id,
        operator_id=operator.id,
        detail="Student not found",
    )
    db.delete(student)
    db.commit()
    return None


@router.get(
    "/school/{school_id}",
    response_model=List[schemas.StudentOut],
    summary="List students by school",
    description="Return all students belonging to one school.",
    response_description="Student list for school",
)
def get_students_by_school(
    school_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    get_operator_scoped_record_or_404(
        db=db,
        model=school_model.School,
        record_id=school_id,
        operator_id=operator.id,
        detail="School not found",
    )

    return (
        db.query(student_model.Student)
        .filter(student_model.Student.operator_id == operator.id)
        .filter(student_model.Student.school_id == school_id)
        .all()
    )


@router.get(
    "/route/{route_id}",
    response_model=List[schemas.StudentOut],
    summary="List students by route",
    description="Return students with at least one run assignment on the selected route.",
    response_description="Student list for route",
)
def get_students_by_route(
    route_id: int,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )

    return (
        db.query(student_model.Student)
        .join(
            assoc_model.StudentRunAssignment,
            assoc_model.StudentRunAssignment.student_id == student_model.Student.id,
        )
        .join(
            run_model.Run,
            run_model.Run.id == assoc_model.StudentRunAssignment.run_id,
        )
        .filter(student_model.Student.operator_id == operator.id)
        .filter(run_model.Run.route_id == route_id)
        .distinct()
        .all()
    )

