# ===========================================================
# backend/routers/route.py - FleetOS Route Router
# -----------------------------------------------------------
# Canonical assembly router for route views, lifecycle,
# actions, and setup workflows.
# ===========================================================

from fastapi import APIRouter

from backend.routers.route_actions import router as route_actions_router
from backend.routers.route_lifecycle import router as route_lifecycle_router
from backend.routers.route_setup_routes import router as route_setup_routes_router
from backend.routers.route_views import router as route_views_router


router = APIRouter(prefix="/routes", tags=["Routes"])
router.include_router(route_views_router)
router.include_router(route_actions_router)
router.include_router(route_lifecycle_router)
router.include_router(route_setup_routes_router)
