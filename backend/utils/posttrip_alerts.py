# -----------------------------------------------------------
# - Post-Trip Alert Helpers
# - Keep post-trip alert sync small and idempotent
# -----------------------------------------------------------
from datetime import datetime, timezone  # Timestamp helpers

from sqlalchemy.orm import Session  # SQLAlchemy session type

from backend.models.dispatch_alert import DispatchAlert  # Persistent alert model
from backend.models.posttrip import PostTripInspection  # Post-trip inspection model


ALERT_TYPE_POSTTRIP_MAJOR_DEFECT = "POSTTRIP_MAJOR_DEFECT"  # Post-trip major defect alert key
ALERT_TYPE_POSTTRIP_NEGLECT = "POSTTRIP_NEGLECT"  # Post-trip neglect alert key
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

    return query.first()


def _create_alert_if_missing(
    *,
    db: Session,
    alert_type: str,
    message: str,
    bus_id: int | None = None,
    route_id: int | None = None,
    run_id: int | None = None,
) -> DispatchAlert:
    existing = _get_unresolved_alert(
        db=db,
        alert_type=alert_type,
        bus_id=bus_id,
        route_id=route_id,
        run_id=run_id,
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

    resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for alert in query.all():
        alert.resolved = True                                  # Mark alert closed
        alert.resolved_at = resolved_at                        # Track when it was closed


# -----------------------------------------------------------
# - Post-trip issue alert sync
# - Create or resolve major-defect alerts per run context
# -----------------------------------------------------------
def sync_posttrip_issue_alerts(
    *,
    inspection: PostTripInspection,
    db: Session,
) -> None:
    if inspection.exterior_status == "major":
        _create_alert_if_missing(
            db=db,
            alert_type=ALERT_TYPE_POSTTRIP_MAJOR_DEFECT,
            message="Urgent: major defect reported on Post-Trip Inspection",
            bus_id=inspection.bus_id,
            route_id=inspection.route_id,
            run_id=inspection.run_id,
        )
    else:
        _resolve_matching_alerts(
            db=db,
            alert_type=ALERT_TYPE_POSTTRIP_MAJOR_DEFECT,
            bus_id=inspection.bus_id,
            route_id=inspection.route_id,
            run_id=inspection.run_id,
        )


# -----------------------------------------------------------
# - Post-trip neglect alert helpers
# - Create or resolve read-triggered neglect alerts per run
# -----------------------------------------------------------
def create_posttrip_neglect_alert_if_needed(
    *,
    inspection: PostTripInspection,
    db: Session,
) -> None:
    if inspection.neglect_flagged_at is None:
        inspection.neglect_flagged_at = datetime.now(timezone.utc).replace(tzinfo=None)  # Preserve first-neglect flag time
    _create_alert_if_missing(
        db=db,
        alert_type=ALERT_TYPE_POSTTRIP_NEGLECT,
        message="Urgent: Post-Trip Inspection Phase 2 appears neglected for run",
        bus_id=inspection.bus_id,
        route_id=inspection.route_id,
        run_id=inspection.run_id,
    )


def resolve_posttrip_neglect_alert_if_needed(
    *,
    inspection: PostTripInspection,
    db: Session,
) -> None:
    _resolve_matching_alerts(
        db=db,
        alert_type=ALERT_TYPE_POSTTRIP_NEGLECT,
        bus_id=inspection.bus_id,
        route_id=inspection.route_id,
        run_id=inspection.run_id,
    )


def sync_posttrip_neglect_alert_if_needed(
    *,
    inspection: PostTripInspection,
    decision: dict[str, object],
    db: Session,
) -> None:
    if decision.get("phase2_decision_status") == "suspected_neglect_ready":
        create_posttrip_neglect_alert_if_needed(
            inspection=inspection,
            db=db,
        )
    else:
        resolve_posttrip_neglect_alert_if_needed(
            inspection=inspection,
            db=db,
        )
