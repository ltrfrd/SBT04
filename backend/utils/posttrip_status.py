# -----------------------------------------------------------
# - Post-Trip Status Helpers
# - Read-only classification for pending phase 2 state
# -----------------------------------------------------------
from __future__ import annotations

from datetime import datetime, timezone  # Timestamp helpers

from backend.models.posttrip import PostTripInspection  # Post-trip inspection model


RECENT_DRIVER_ACTIVITY_MINUTES = 10  # Temporary threshold for recent driver interaction
RECENT_LOCATION_ACTIVITY_MINUTES = 10  # Temporary threshold for recent GPS activity
NEGLECT_READY_MINUTES = 15  # Temporary threshold for later neglect-ready classification


def _minutes_since(timestamp: datetime | None, now: datetime) -> float | None:
    if timestamp is None:
        return None
    return round((now - timestamp).total_seconds() / 60, 1)


# -----------------------------------------------------------
# - Evaluate post-trip phase 2 status
# - Return a read-only classification for current pending state
# -----------------------------------------------------------
def evaluate_posttrip_phase2_status(inspection: PostTripInspection) -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)      # Naive UTC for consistency with stored timestamps
    minutes_since_phase2_pending = _minutes_since(inspection.phase2_pending_since, now)
    minutes_since_driver_activity = _minutes_since(inspection.last_driver_activity_at, now)
    minutes_since_location_update = _minutes_since(inspection.last_location_update_at, now)

    has_recent_driver_activity = (
        minutes_since_driver_activity is not None
        and minutes_since_driver_activity <= RECENT_DRIVER_ACTIVITY_MINUTES
    )
    has_recent_location_activity = (
        minutes_since_location_update is not None
        and minutes_since_location_update <= RECENT_LOCATION_ACTIVITY_MINUTES
    )

    if inspection.phase2_completed is True:
        phase2_decision_status = "completed"
    elif inspection.phase1_completed is not True:
        phase2_decision_status = "not_started"
    elif has_recent_driver_activity and has_recent_location_activity:
        phase2_decision_status = "pending_recent_activity"
    elif not has_recent_driver_activity and has_recent_location_activity:
        phase2_decision_status = "pending_no_recent_driver_activity"
    elif has_recent_driver_activity and not has_recent_location_activity:
        phase2_decision_status = "pending_no_recent_location"
    elif (
        minutes_since_phase2_pending is not None
        and minutes_since_phase2_pending >= NEGLECT_READY_MINUTES
    ):
        phase2_decision_status = "suspected_neglect_ready"
    else:
        phase2_decision_status = "pending_low_confidence_inactive"

    return {
        "phase2_decision_status": phase2_decision_status,
        "has_recent_driver_activity": has_recent_driver_activity,
        "has_recent_location_activity": has_recent_location_activity,
        "minutes_since_phase2_pending": minutes_since_phase2_pending,
        "minutes_since_driver_activity": minutes_since_driver_activity,
        "minutes_since_location_update": minutes_since_location_update,
    }
