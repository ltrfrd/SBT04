# ============================================================
# Student-run assignment schemas for FleetOS
# ============================================================

# -----------------------------
# Imports
# -----------------------------
from pydantic import BaseModel, ConfigDict  # Pydantic schema helpers


# -----------------------------
# Router / Model / Schema
# -----------------------------
class StudentRunAssignmentCreate(BaseModel):
    student_id: int  # Compatibility request student ID for the blocked direct-create route
    run_id: int  # Compatibility request run ID for the blocked direct-create route
    stop_id: int  # Compatibility request stop ID for the blocked direct-create route


# -----------------------------
# Logic
# -----------------------------
class StudentRunAssignmentOut(BaseModel):
    id: int  # Assignment identifier
    student_id: int  # Assigned student ID
    run_id: int  # Assigned run ID
    stop_id: int  # Planned stop ID
    actual_pickup_stop_id: int | None = None  # Actual pickup stop if recorded
    actual_dropoff_stop_id: int | None = None  # Actual dropoff stop if recorded
    model_config = ConfigDict(from_attributes=True)  # Enable ORM serialization
