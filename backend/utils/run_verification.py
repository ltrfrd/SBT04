from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models.associations import StudentRunAssignment
from backend.models.run import Run
from backend.models.run_verification import RunVerification


VALID_RUN_DIRECTIONS = {"AM", "PM"}


def normalize_run_direction(run_type: str | None) -> str | None:
    if run_type is None:
        return None
    normalized = run_type.upper()
    if normalized not in VALID_RUN_DIRECTIONS:
        return None
    return normalized


def get_run_verification(
    *,
    db: Session,
    run_id: int,
    direction: str,
) -> RunVerification | None:
    return (
        db.query(RunVerification)
        .filter(
            RunVerification.run_id == run_id,
            RunVerification.direction == direction,
        )
        .first()
    )


def get_or_create_run_verification(
    *,
    db: Session,
    run_id: int,
    direction: str,
) -> RunVerification:
    verification = get_run_verification(db=db, run_id=run_id, direction=direction)
    if verification:
        return verification

    verification = RunVerification(
        run_id=run_id,
        direction=direction,
        status="pending",
        mismatch_count=0,
    )
    db.add(verification)
    db.flush()
    return verification


def load_run_assignments(
    *,
    db: Session,
    run_id: int,
) -> list[StudentRunAssignment]:
    return (
        db.query(StudentRunAssignment)
        .filter(StudentRunAssignment.run_id == run_id)
        .all()
    )


def assignment_operational_school_truth(*, assignment: StudentRunAssignment, direction: str) -> bool:
    if direction == "AM":
        return bool(assignment.dropped_off)
    return bool(assignment.boarded_by_driver)


def assignment_school_truth(*, assignment: StudentRunAssignment, direction: str) -> bool | None:
    if direction == "AM":
        if assignment.school_status == "present":
            return True
        if assignment.school_status == "absent":
            return False
        return None
    # PM: truth is released_by_school (always a bool, never None)
    return bool(assignment.released_by_school)


def assignment_mismatch(
    *,
    assignment: StudentRunAssignment,
    direction: str,
) -> tuple[bool, str | None]:
    school_truth = assignment_school_truth(assignment=assignment, direction=direction)
    if school_truth is None:
        return True, "school_verification_missing"

    if direction == "AM":
        if school_truth != bool(assignment.dropped_off):
            return True, "am_dropoff_mismatch"
        return False, None

    # PM: school_truth is released_by_school
    if school_truth != bool(assignment.boarded_by_driver):
        return True, "pm_release_boarding_mismatch"
    return False, None


def sync_run_verification(
    *,
    db: Session,
    run: Run,
    assignments: list[StudentRunAssignment] | None = None,
) -> RunVerification | None:
    direction = normalize_run_direction(run.run_type)
    if direction is None:
        return None

    if assignments is None:
        assignments = load_run_assignments(db=db, run_id=run.id)

    verification = get_or_create_run_verification(
        db=db,
        run_id=run.id,
        direction=direction,
    )

    missing_count = 0
    mismatch_count = 0

    for assignment in assignments:
        school_truth = assignment_school_truth(assignment=assignment, direction=direction)
        if school_truth is None:
            missing_count += 1
            mismatch_count += 1
            continue

        mismatch, _ = assignment_mismatch(assignment=assignment, direction=direction)
        if mismatch:
            mismatch_count += 1

    if missing_count > 0:
        status = "pending"
    elif mismatch_count > 0:
        status = "mismatch"
    else:
        status = "resolved"

    verification.status = status
    verification.mismatch_count = mismatch_count
    if verification.status != "confirmed":
        verification.confirmed_by_role = None
        verification.confirmed_at = None
    return verification


def confirm_run_verification(
    *,
    db: Session,
    run: Run,
    confirmed_by_role: str,
    assignments: list[StudentRunAssignment] | None = None,
) -> RunVerification:
    verification = sync_run_verification(db=db, run=run, assignments=assignments)
    if verification is None:
        raise ValueError("Run verification is only supported for AM and PM runs")

    if verification.mismatch_count > 0:
        verification.status = "mismatch"
        verification.confirmed_by_role = None
        verification.confirmed_at = None
        return verification

    verification.status = "confirmed"
    verification.confirmed_by_role = confirmed_by_role
    verification.confirmed_at = datetime.now(timezone.utc)
    return verification
