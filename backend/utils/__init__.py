# ===========================================================
# backend/utils/__init__.py - FleetOS Utils Index
# -----------------------------------------------------------
# Re-exports utility modules for clean imports
# ===========================================================

from .reports_generator import (
    driver_summary,
    dispatch_summary,
    generate_reports,
    route_summary_execution,
)

# Optional: Add future utils here
# from .gps_tools import simulate_gps
# from .auth import verify_token

__all__ = [
    "driver_summary",
    "route_summary_execution",
    "dispatch_summary",
    "generate_reports",
]
