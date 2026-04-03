from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import run as run_model
from backend.models import stop as stop_model


def ensure_run_is_planned_for_setup(run: run_model.Run) -> run_model.Run:
    if run.start_time is not None or run.end_time is not None or run.is_completed:
        raise HTTPException(status_code=400, detail="Only planned runs can be modified")
    return run


def get_run_or_404(run_id: int, db: Session) -> run_model.Run:
    run = db.get(run_model.Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def get_stop_or_404(stop_id: int, db: Session) -> stop_model.Stop:
    stop = db.get(stop_model.Stop, stop_id)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")
    return stop


def validate_stop_belongs_to_run(
    *,
    run: run_model.Run,
    stop: stop_model.Stop,
) -> tuple[run_model.Run, stop_model.Stop]:
    if stop.run_id != run.id:
        raise HTTPException(status_code=400, detail="Stop does not belong to run")
    return run, stop


def get_run_stop_context_or_404(
    *,
    run_id: int,
    stop_id: int,
    db: Session,
    require_planned: bool = False,
) -> tuple[run_model.Run, stop_model.Stop]:
    run = get_run_or_404(run_id, db)
    if require_planned:
        ensure_run_is_planned_for_setup(run)

    stop = get_stop_or_404(stop_id, db)
    return validate_stop_belongs_to_run(run=run, stop=stop)
