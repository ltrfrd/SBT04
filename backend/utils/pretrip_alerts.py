# -----------------------------------------------------------
# Pre-Trip Alert Helpers
# - Keep alert creation and dedupe logic small and reusable
# -----------------------------------------------------------
from datetime import date, datetime, timedelta, timezone  # Date and timestamp helpers

from sqlalchemy.orm import Session  # SQLAlchemy session type

from backend.models.dispatch_alert import DispatchAlert  # Persistent alert model
from backend.models.pretrip import PreTripInspection  # Pre-trip inspection model


ALERT_TYPE_MAJOR_DEFECT = "PRETRIP_MAJOR_DEFECT"  # Major defect alert key
ALERT_TYPE_NOT_FIT = "PRETRIP_NOT_FIT_FOR_DUTY"  # Not-fit alert key
ALERT_TYPE_MISSING_PRETRIP = "MISSING_PRETRIP_BEFORE_RUN_START"  # Missing pre-trip alert key
ALERT_SEVERITY_URGENT = "urgent"  # Urgent alert severity label


# -----------------------------------------------------------
# - Alert query helpers
# - Reuse narrow unresolved-alert filters for dedupe and resolve
# -----------------------------------------------------------
def _get_unresolved_alert(
    *,
    db: Session,
    alert_type: str,
    bus_id: int | None = None,
    route_id: int | None = None,
    run_id: int | None = None,
    pretrip_id: int | None = None,
) -> DispatchAlert | None:
    query = (
        db.query(DispatchAlert)
        .filter(DispatchAlert.alert_type == alert_type)
        .filter(DispatchAlert.resolved.is_(False))
    )                                                          # Start from matching unresolved alerts only

    if bus_id is None:
        query = query.filter(DispatchAlert.bus_id.is_(None))
    else:
        query = query.filter(DispatchAlert.bus_id == bus_id)

    if route_id is None:
        query = query.filter(DispatchAlert.route_id.is_(None))
    else:
        query = query.filter(DispatchAlert.route_id == route_id)

    if run_id is None:
        query = query.filter(DispatchAlert.run_id.is_(None))
    else:
        query = query.filter(DispatchAlert.run_id == run_id)

    if pretrip_id is None:
        query = query.filter(DispatchAlert.pretrip_id.is_(None))
    else:
        query = query.filter(DispatchAlert.pretrip_id == pretrip_id)

    return query.first()


def _create_alert_if_missing(
    *,
    db: Session,
    alert_type: str,
    message: str,
    bus_id: int | None = None,
    route_id: int | None = None,
    run_id: int | None = None,
    pretrip_id: int | None = None,
) -> DispatchAlert:
    existing = _get_unresolved_alert(
        db=db,
        alert_type=alert_type,
        bus_id=bus_id,
        route_id=route_id,
        run_id=run_id,
        pretrip_id=pretrip_id,
    )
    if existing:
        return existing                                         # Reuse the unresolved alert instead of creating noise

    alert = DispatchAlert(
        alert_type=alert_type,
        severity=ALERT_SEVERITY_URGENT,
        message=message,
        bus_id=bus_id,
        route_id=route_id,
        run_id=run_id,
        pretrip_id=pretrip_id,
    )
    db.add(alert)
    db.flush()
    return alert


def _resolve_matching_alerts(
    *,
    db: Session,
    alert_type: str,
    bus_id: int | None = None,
    route_id: int | None = None,
    run_id: int | None = None,
    pretrip_id: int | None = None,
) -> None:
    query = (
        db.query(DispatchAlert)
        .filter(DispatchAlert.alert_type == alert_type)
        .filter(DispatchAlert.resolved.is_(False))
    )                                                          # Resolve only currently-open alerts

    if bus_id is None:
        query = query.filter(DispatchAlert.bus_id.is_(None))
    else:
        query = query.filter(DispatchAlert.bus_id == bus_id)

    if route_id is None:
        query = query.filter(DispatchAlert.route_id.is_(None))
    else:
        query = query.filter(DispatchAlert.route_id == route_id)

    if run_id is None:
        query = query.filter(DispatchAlert.run_id.is_(None))
    else:
        query = query.filter(DispatchAlert.run_id == run_id)

    if pretrip_id is None:
        query = query.filter(DispatchAlert.pretrip_id.is_(None))
    else:
        query = query.filter(DispatchAlert.pretrip_id == pretrip_id)

    resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for alert in query.all():
        alert.resolved = True                                  # Mark alert closed
        alert.resolved_at = resolved_at                        # Track when it was closed


# -----------------------------------------------------------
# - Pre-trip alert reset
# - Clear unresolved alerts tied to one pre-trip before resync
# -----------------------------------------------------------
def _resolve_unresolved_pretrip_alerts(
    *,
    db: Session,
    pretrip_id: int,
) -> None:
    resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    alerts = (
        db.query(DispatchAlert)
        .filter(DispatchAlert.pretrip_id == pretrip_id)
        .filter(DispatchAlert.resolved.is_(False))
        .all()
    )                                                          # Only alerts tied directly to this pre-trip record

    for alert in alerts:
        alert.resolved = True                                  # Reset pre-trip-linked alert state before rebuilding it
        alert.resolved_at = resolved_at                        # Keep resolution timestamp consistent


# -----------------------------------------------------------
# - Pre-trip issue alert sync
# - Create or resolve major-defect / not-fit alerts per pre-trip
# -----------------------------------------------------------
def sync_pretrip_issue_alerts(
    *,
    inspection: PreTripInspection,
    db: Session,
) -> None:
    _resolve_unresolved_pretrip_alerts(
        db=db,
        pretrip_id=inspection.id,
    )

    has_major_defect = any(defect.severity == "major" for defect in inspection.defects)
    not_fit = inspection.fit_for_duty == "no"

    if has_major_defect:
        _create_alert_if_missing(
            db=db,
            alert_type=ALERT_TYPE_MAJOR_DEFECT,
            message="Urgent: major defect reported on pre-trip",
            bus_id=inspection.bus_id,
            pretrip_id=inspection.id,
        )
    else:
        _resolve_matching_alerts(
            db=db,
            alert_type=ALERT_TYPE_MAJOR_DEFECT,
            pretrip_id=inspection.id,
        )

    if not_fit:
        _create_alert_if_missing(
            db=db,
            alert_type=ALERT_TYPE_NOT_FIT,
            message="Urgent: driver marked not fit for duty on pre-trip",
            bus_id=inspection.bus_id,
            pretrip_id=inspection.id,
        )
    else:
        _resolve_matching_alerts(
            db=db,
            alert_type=ALERT_TYPE_NOT_FIT,
            pretrip_id=inspection.id,
        )

    resolve_missing_pretrip_alerts_for_bus_day(
        db=db,
        bus_id=inspection.bus_id,
        inspection_date=inspection.inspection_date,
    )                                                          # Close any missing-pretrip alerts satisfied by this submission


# -----------------------------------------------------------
# - Missing pre-trip alert helpers
# - Create and resolve bus/day run-start pre-trip alerts
# -----------------------------------------------------------
def create_missing_pretrip_alert_if_needed(
    *,
    db: Session,
    bus_id: int,
    route_id: int,
    run_id: int,
    scheduled_start_time,
) -> None:
    now = datetime.now()                                       # Local current time for same-day schedule comparison
    scheduled_start = datetime.combine(date.today(), scheduled_start_time)
    lead_time = scheduled_start - now

    if lead_time < timedelta(0) or lead_time > timedelta(minutes=15):
        return                                                 # Only alert inside the final 15-minute pre-start window

    _create_alert_if_missing(
        db=db,
        alert_type=ALERT_TYPE_MISSING_PRETRIP,
        message="Urgent: no pre-trip found for active bus within 15 minutes of scheduled run start",
        bus_id=bus_id,
        route_id=route_id,
        run_id=run_id,
    )


def resolve_missing_pretrip_alerts_for_bus_day(
    *,
    db: Session,
    bus_id: int,
    inspection_date,
) -> None:
    if inspection_date != date.today():
        return                                                 # Only today's submitted pre-trip resolves today's missing alerts

    query = (
        db.query(DispatchAlert)
        .filter(DispatchAlert.alert_type == ALERT_TYPE_MISSING_PRETRIP)
        .filter(DispatchAlert.bus_id == bus_id)
        .filter(DispatchAlert.resolved.is_(False))
    )

    resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for alert in query.all():
        alert.resolved = True                                  # Missing condition no longer applies for today's bus
        alert.resolved_at = resolved_at
