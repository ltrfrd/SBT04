# ===========================================================
# backend/utils/gps_tools.py — BST GPS Utilities (Student App Only)
# -----------------------------------------------------------
# No parent model. All alerts go to STUDENT APP via WebSocket.
# Every function is documented and ordered correctly.
# ===========================================================

# ---------- CORE IMPORTS ----------
from datetime import datetime, timedelta  # For ETA and timestamps
from math import (
    radians,
    cos,
    sin,
    sqrt,
    atan2,
    asin,
    degrees,
)  # Haversine math functions
from typing import Tuple, Optional, Dict, List  # Type hints for clarity
from sqlalchemy.orm import Session  # DB session for queries

# Import your models (adjust if names differ)
from backend.models import (
    stop as stop_model,
    run as run_model,
    student as student_model,
)


# -----------------------------------------------------------
# 1. VALIDATE GPS COORDINATES
# -----------------------------------------------------------
def validate_gps(lat: float, lng: float) -> bool:
    """
    Validate GPS coordinates are within Earth's bounds.
    Returns True if valid, False otherwise.
    """
    return -90 <= lat <= 90 and -180 <= lng <= 180


# -----------------------------------------------------------
# 2. CALCULATE DISTANCE BETWEEN TWO POINTS
# -----------------------------------------------------------
def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate great-circle distance in meters using Haversine formula.
    Used for: stop progress, ETA, alerts.
    """
    R = 6371000  # Earth radius in meters
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lng2 - lng1)

    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # Distance in meters


# -----------------------------------------------------------
# 3. SIMULATE BUS MOVEMENT
# -----------------------------------------------------------
def simulate_gps_position(
    start_lat: float, start_lng: float, bearing: float, speed_kmh: float, seconds: int
) -> Tuple[float, float]:
    """
    Simulate bus moving along a bearing at given speed.
    Used for testing without real GPS.
    """
    distance_m = (speed_kmh * 1000 / 3600) * seconds  # Convert km/h → m/s → meters
    R = 6371000  # Earth radius
    bearing_rad = radians(bearing)

    lat1 = radians(start_lat)
    lng1 = radians(start_lng)

    lat2 = asin(
        sin(lat1) * cos(distance_m / R)
        + cos(lat1) * sin(distance_m / R) * cos(bearing_rad)
    )
    lng2 = lng1 + atan2(
        sin(bearing_rad) * sin(distance_m / R) * cos(lat1),
        cos(distance_m / R) - sin(lat1) * sin(lat2),
    )

    return round(degrees(lat2), 6), round(degrees(lng2), 6)


# -----------------------------------------------------------
# 4. CHECK IF BUS IS APPROACHING A STOP
# -----------------------------------------------------------
def is_bus_approaching(
    bus_lat: float,
    bus_lng: float,
    target_lat: float,
    target_lng: float,
    threshold_meters: float = 500,
) -> bool:
    """
    Check if bus is within custom threshold of a stop.
    Threshold comes from student.notification_distance_meters.
    """
    if not validate_gps(bus_lat, bus_lng) or not validate_gps(target_lat, target_lng):
        return False
    distance = haversine_distance(bus_lat, bus_lng, target_lat, target_lng)
    return distance <= threshold_meters


# -----------------------------------------------------------
# 5. GET CURRENT STOP PROGRESS
# -----------------------------------------------------------
def get_current_stop_progress(
    db: Session, run_id: int, current_lat: float, current_lng: float
) -> Dict:
    """
    Return current stop, next stop, and progress %.
    Used for: map, progress bar, ETA.
    """
    run = db.get(run_model.Run, run_id)
    if not run or not run.route:
        return {"error": "Run or route not found"}

    stops = sorted(run.route.stops, key=lambda s: s.sequence)
    if not stops:
        return {"error": "No stops on route"}

    # Only stops with GPS
    valid_stops = [
        stop
        for stop in stops
        if stop.latitude is not None and stop.longitude is not None
    ]
    if not valid_stops:
        return {"error": "No GPS-enabled stops"}

    # Find closest stop
    distances = [
        (
            stop,
            haversine_distance(current_lat, current_lng, stop.latitude, stop.longitude),
        )
        for stop in valid_stops
    ]
    current_stop, _ = min(distances, key=lambda x: x[1])
    current_idx = stops.index(current_stop)

    next_stop = stops[current_idx + 1] if current_idx + 1 < len(stops) else None

    # Progress to next stop
    progress = 0.0
    if next_stop and next_stop.latitude is not None:
        total = haversine_distance(
            current_stop.latitude,
            current_stop.longitude,
            next_stop.latitude,
            next_stop.longitude,
        )
        remaining = haversine_distance(
            current_lat, current_lng, next_stop.latitude, next_stop.longitude
        )
        if total > 0:
            progress = max(0, min(100, ((total - remaining) / total) * 100))

    return {
        "current_stop": {
            "id": current_stop.id,
            "sequence": current_stop.sequence,
            "type": (
                current_stop.type.value
                if hasattr(current_stop.type, "value")
                else str(current_stop.type)
            ),
            "name": current_stop.name or f"Stop {current_stop.sequence}",
        },
        "next_stop": (
            {
                "id": next_stop.id,
                "sequence": next_stop.sequence,
                "name": next_stop.name or "End of Route",
            }
            if next_stop
            else None
        ),
        "progress_percent": round(progress, 1),
        "total_stops": len(stops),
    }


# -----------------------------------------------------------
# 6. ESTIMATE TIME OF ARRIVAL
# -----------------------------------------------------------
def estimate_eta(
    db: Session,
    run_id: int,
    current_lat: float,
    current_lng: float,
    avg_speed_kmh: float = 30,
) -> Optional[datetime]:
    """
    Estimate ETA to next stop.
    Used in alerts and UI.
    """
    progress = get_current_stop_progress(db, run_id, current_lat, current_lng)
    if "error" in progress or not progress.get("next_stop"):
        return None

    next_stop_id = progress["next_stop"]["id"]
    next_stop = db.get(stop_model.Stop, next_stop_id)
    if not next_stop or next_stop.latitude is None:
        return None

    distance_m = haversine_distance(
        current_lat, current_lng, next_stop.latitude, next_stop.longitude
    )
    minutes = distance_m / (avg_speed_kmh * 1000 / 60)
    return datetime.now() + timedelta(minutes=minutes)


# -----------------------------------------------------------
# 7. STUDENT ALERTS (No Parent Model)
# -----------------------------------------------------------
def get_approaching_alerts(
    db: Session, run_id: int, bus_lat: float, bus_lng: float
) -> List[Dict]:
    """
    Generate alerts for students at the next stop.
    Sent via WebSocket to STUDENT APP.
    """
    progress = get_current_stop_progress(db, run_id, bus_lat, bus_lng)
    if "error" in progress or not progress.get("next_stop"):
        return []

    next_stop = db.get(stop_model.Stop, progress["next_stop"]["id"])
    if not next_stop or next_stop.latitude is None:
        return []

    # Get all students at this stop
    students = (
        db.query(student_model.Student)
        .filter(student_model.Student.stop_id == next_stop.id)
        .all()
    )

    alerts = []
    for student in students:
        threshold = student.notification_distance_meters or 500
        if is_bus_approaching(
            bus_lat, bus_lng, next_stop.latitude, next_stop.longitude, threshold
        ):
            eta = estimate_eta(db, run_id, bus_lat, bus_lng)
            eta_str = eta.strftime("%I:%M %p") if eta else "soon"

            alerts.append(
                {
                    "student_id": student.id,
                    "student_name": student.name,
                    "message": f"Bus is approaching your stop! ETA: {eta_str}",
                    "distance_meters": round(
                        haversine_distance(
                            bus_lat, bus_lng, next_stop.latitude, next_stop.longitude
                        ),
                        1,
                    ),
                    "stop_name": next_stop.name or f"Stop {next_stop.sequence}",
                }
            )
    return alerts
