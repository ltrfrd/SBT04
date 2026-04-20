# ===========================================================
# backend/routers/run.py - FleetOS Run Router
# -----------------------------------------------------------
# Canonical assembly router for run views, lifecycle, actions,
# and setup workflows.
# ===========================================================

from fastapi import APIRouter

from backend.routers.run_actions import router as run_actions_router
from backend.routers.run_lifecycle import router as run_lifecycle_router
from backend.routers.run_setup_routes import router as run_setup_routes_router
from backend.routers.run_views import router as run_views_router


router = APIRouter(prefix="/runs", tags=["Runs"])
router.include_router(run_setup_routes_router)
router.include_router(run_views_router)
router.include_router(run_lifecycle_router)
router.include_router(run_actions_router)
