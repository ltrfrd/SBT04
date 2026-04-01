# ===========================================================
# app.py — SBT FastAPI Application Entry Point
# -----------------------------------------------------------
# Fully documented version: all imports, functions, and logic explained.
# ===========================================================

# ---------- SYSTEM ----------
import os                                # For environment variables and paths
from dotenv import load_dotenv           # Loads .env file for secrets/config
load_dotenv()                            # Initialize environment variables

# ---------- FASTAPI ----------
from fastapi import (
    FastAPI, Request, Depends, HTTPException,
    status, WebSocket, WebSocketDisconnect, Body
)                                        # Core FastAPI imports
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates  # For rendering HTML templates
from fastapi.middleware.cors import CORSMiddleware  # Allow cross-domain requests
from fastapi.staticfiles import StaticFiles         # Serve static files (CSS, JS)
from starlette.middleware.sessions import SessionMiddleware  # Session handling
from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload         # Database session for ORM
from datetime import datetime, date        # For timestamps and date filters
import json                                # Parse JSON payloads
from typing import Dict, List              # Type hints for dictionaries/lists
# ---------- DB & MODELS ----------
from database import get_db, engine, Base   # Local database setup (SQLAlchemy)
from backend import schemas                 # Import Pydantic schemas
from backend.models import (                # Import model modules for ORM binding
    driver as driver_model,
    school as school_model,
    student as student_model,
    route as route_model,
    run as run_model,
    dispatch as dispatch_model
)
from backend.models.associations import RouteDriverAssignment, StudentRunAssignment

# ---------- ROUTERS ----------
# Import each router module (each exposes a .router object)
from backend.routers import (
    driver, school, student, route, stop, run, dispatch, attendance, student_run_assignment
)  # Import active routers through attendance ownership

# ---------- UTILS ----------
# Custom utilities: GPS tools and authentication helpers
from backend.utils import gps_tools
from backend.utils import attendance_generator
from backend.utils.auth import get_current_driver, login_driver, logout_driver
from backend.utils.route_driver_assignment import get_route_driver_name

# ---------- WEBSOCKET TRACKING ----------
# Active WebSocket connections per run_id (real-time GPS broadcasting)
active_connections: Dict[int, List[WebSocket]] = {}


# -----------------------------------------------------------
# APP SETUP
# -----------------------------------------------------------
app = FastAPI(title="SBT — School Bus Tracking System", version="1.0.0")

# Session middleware for login sessions, using secret key from .env
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret-key-change-in-prod")
) 

# CORS policy — open for now, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder (CSS, JS, images)
app.mount("/static", StaticFiles(directory="backend/templates/static"), name="static")

# Jinja2 template engine setup for rendering HTML pages
templates = Jinja2Templates(directory="backend/templates")


# -----------------------------------------------------------
# ROUTERS REGISTRATION
# -----------------------------------------------------------
# Each router defines its own endpoints (CRUD APIs)
app.include_router(driver.router)  # Register driver endpoints
app.include_router(school.router)  # Register school endpoints
app.include_router(student.router)  # Register student endpoints
app.include_router(route.router)  # Register route endpoints
app.include_router(stop.router)  # Register stop endpoints
app.include_router(run.router)  # Register run endpoints
app.include_router(dispatch.router)  # Register dispatch endpoints
app.include_router(attendance.router)  # Register attendance layer endpoints
app.include_router(student_run_assignment.router)  # Register student run assignment endpoints
app.include_router(attendance.student_bus_absence_router)  # Register absence endpoints through attendance ownership

# -----------------------------------------------------------
# WEBSOCKET: GPS + ALERTS
# -----------------------------------------------------------
@app.websocket("/ws/gps/{run_id}")
async def websocket_gps_endpoint(websocket: WebSocket, run_id: int, db: Session = Depends(get_db)):
    """Handles real-time GPS data via WebSocket connections."""
    await websocket.accept()
    if run_id not in active_connections:
        active_connections[run_id] = []
    active_connections[run_id].append(websocket)

    try:
        while True:
            # Receive GPS coordinates from client
            data = await websocket.receive_text()
            gps = json.loads(data)

            # Validate coordinates
            if not gps_tools.validate_gps(gps["lat"], gps["lng"]):
                continue

            # Prepare broadcast payload
            broadcast_data = {
                "run_id": run_id,
                "lat": gps["lat"],
                "lng": gps["lng"],
                "timestamp": datetime.now().isoformat(),
                "progress": gps_tools.get_current_stop_progress(db, run_id, gps["lat"], gps["lng"])
            }

            # Append any nearby stop alerts
            alerts = gps_tools.get_approaching_alerts(db, run_id, gps["lat"], gps["lng"])
            if alerts:
                broadcast_data["alerts"] = alerts

            # Send update to all connected clients on same run_id
            for client in list(active_connections.get(run_id, [])):
                try:
                    await client.send_json(broadcast_data)
                except:
                    # Remove disconnected clients
                    if client in active_connections[run_id]:
                        active_connections[run_id].remove(client)

    except WebSocketDisconnect:
        # Clean disconnect: remove socket safely
        if run_id in active_connections and websocket in active_connections[run_id]:
            active_connections[run_id].remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")


# -----------------------------------------------------------
# DASHBOARD PAGE
# -----------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    """Renders admin dashboard summary with record counts."""
    counts = {
        "driver_count": db.query(driver_model.Driver).count(),
        "school_count": db.query(school_model.School).count(),
        "route_count": db.query(route_model.Route).count(),
        "student_count": db.query(student_model.Student).count(),
        "run_count": db.query(run_model.Run).filter(run_model.Run.end_time.is_(None)).count(),
    }
    return templates.TemplateResponse(
        request,                                              # Request first (prevents deprecation warning)
        "dashboard.html",                                     # Template name
        counts,                                               # Context dict (request auto-injected)
    )


# -----------------------------------------------------------
# ROUTE ATTENDANCE PAGE
# -----------------------------------------------------------
@app.get("/route_report/{route_id}", response_class=HTMLResponse)
def route_report(route_id: int, request: Request, db: Session = Depends(get_db)):
    """Shows route-specific attendance summary including driver name and route details."""
    route_data = attendance_generator.route_summary(db, route_id)
    if "error" in route_data:
        raise HTTPException(status_code=404, detail=route_data["error"])

    route = db.get(route_model.Route, route_id)
    driver_name = get_route_driver_name(route) if route else None
    return templates.TemplateResponse(
        request,                                              # New Starlette signature: request first
        "route_report.html",                                  # Template name
        {
            "request": request,
            "route": route,
            "route_data": route_data,
            "driver_name": driver_name or "Unassigned",
        },
    )


# -----------------------------------------------------------
# - Driver workspace helpers
# - Build route-first driver template state
# -----------------------------------------------------------
def _get_run_workspace_status(run: run_model.Run) -> str:
    if run.start_time is None:
        return "ready"                                       # Driver-facing label for a run that has not started yet
    if run.end_time is None:
        return "active"                                      # Started but not ended yet
    return "ended"                                           # Historical completed run


# -----------------------------------------------------------
# - Build route workspace
# - Serialize route, run, stop, and rider details for the driver page
# -----------------------------------------------------------
def _build_route_workspace(route: route_model.Route, selected_run_id: int | None = None) -> dict:
    active_assignment = next(                                # Route-level assigned driver for header display
        (assignment for assignment in route.driver_assignments if assignment.active),
        None,
    )

    # -----------------------------------------------------------
    # - Order route runs
    # - Keep run list stable for route-first browsing
    # -----------------------------------------------------------
    ordered_runs = sorted(                                   # Show the newest run context first
        route.runs,
        key=lambda run: (run.start_time or datetime.min, run.id),
        reverse=True,
    )

    run_rows = []                                            # Final nested run workspace rows

    for run in ordered_runs:
        # -----------------------------------------------------------
        # - Order run stops
        # - Keep stop sequence stable for running-board review
        # -----------------------------------------------------------
        ordered_stops = sorted(                              # Stable stop order inside each run
            run.stops,
            key=lambda stop: (
                stop.sequence if stop.sequence is not None else 999999,
                stop.id,
            ),
        )

        assignments_by_stop: dict[int, list[dict]] = {}     # Stop -> student rows for the template

        # -----------------------------------------------------------
        # - Group riders by stop
        # - Build stop-level running-board rows from runtime assignments
        # -----------------------------------------------------------
        for assignment in sorted(
            run.student_assignments,
            key=lambda item: (
                item.stop.sequence if item.stop and item.stop.sequence is not None else 999999,
                item.id,
            ),
        ):
            if assignment.stop_id is None or not assignment.student:
                continue

            assignments_by_stop.setdefault(assignment.stop_id, []).append(
                {
                    "student_id": assignment.student.id,     # Stable student identifier for row keys
                    "student_name": assignment.student.name, # Driver-facing student display
                    "grade": assignment.student.grade,       # Compact rider detail
                    "school_name": assignment.student.school.name if assignment.student.school else None,  # School context
                    "notification_distance_meters": assignment.student.notification_distance_meters,  # Rider alert distance
                }
            )

        stop_rows = []                                       # Ordered stop rows for this run

        # -----------------------------------------------------------
        # - Serialize stop rows
        # - Expose running-board stop details already available in the repo
        # -----------------------------------------------------------
        for stop in ordered_stops:
            stop_students = assignments_by_stop.get(stop.id, [])
            stop_rows.append(
                {
                    "id": stop.id,
                    "sequence": stop.sequence,
                    "type": stop.type.value if hasattr(stop.type, "value") else str(stop.type),  # Pickup or dropoff label
                    "name": stop.name,
                    "address": stop.address,
                    "planned_time": stop.planned_time,       # Planned stop time when available
                    "student_count": len(stop_students),
                    "students": stop_students,
                }
            )

        # -----------------------------------------------------------
        # - Serialize run row
        # - Keep review state and live-action flags separate
        # -----------------------------------------------------------
        status = _get_run_workspace_status(run)              # Ready / active / ended summary label
        run_rows.append(
            {
                "id": run.id,
                "run_type": run.run_type,
                "status": status,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "stop_count": len(stop_rows),
                "student_count": len(run.student_assignments),
                "current_stop_id": run.current_stop_id,
                "current_stop_sequence": run.current_stop_sequence,
                "can_start": run.start_time is None,         # Start only from ready runs
                "can_update": run.start_time is None,        # Non-started runs remain editable in backend flows
                "can_delete": run.start_time is None,        # Non-started runs remain deletable in backend flows
                "can_end": status == "active",               # Preserve active end-run behavior
                "stops": stop_rows,
            }
        )

    # -----------------------------------------------------------
    # - Resolve selected and active runs
    # - Keep review browsing independent from active-run controls
    # -----------------------------------------------------------
    active_run = next((run for run in run_rows if run["status"] == "active"), None)  # At most one active run per driver
    selected_run = next((run for run in run_rows if run["id"] == selected_run_id), None) if selected_run_id is not None else None
    if selected_run is None and run_rows:
        selected_run = run_rows[0]                            # Default to the first route run so stop details remain visible

    return {
        "id": route.id,
        "route_number": route.route_number,
        "unit_number": route.unit_number,
        "operator": route.operator,
        "capacity": route.capacity,
        "schools": [
            {
                "id": school.id,
                "name": school.name,
            }
            for school in route.schools
        ],
        "assigned_driver_id": active_assignment.driver_id if active_assignment else None,
        "assigned_driver_name": active_assignment.driver.name if active_assignment and active_assignment.driver else None,
        "runs": run_rows,
        "active_run": active_run,
        "selected_run": selected_run,
    }


# -----------------------------------------------------------
# - Driver run workspace page
# - Render route-first route, run, and run-review navigation
# -----------------------------------------------------------
@app.get("/driver_run/{driver_id}", response_class=HTMLResponse)
def driver_run_view(
    driver_id: int,
    request: Request,
    route_id: int | None = None,
    run_id: int | None = None,
    db: Session = Depends(get_db),
    current_driver: driver_model.Driver = Depends(get_current_driver)
):
    """Render the route-first driver workspace."""
    # -----------------------------------------------------------
    # - Validate driver access
    # - Require an authenticated driver to open their own workspace
    # -----------------------------------------------------------
    if not current_driver:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # -----------------------------------------------------------
    # - Load active run
    # - Preserve live-run context without forcing navigation
    # -----------------------------------------------------------
    active_run = (
        db.query(run_model.Run)
        .options(joinedload(run_model.Run.route))
        .filter(run_model.Run.driver_id == driver_id)
        .filter(run_model.Run.start_time.is_not(None))
        .filter(run_model.Run.end_time.is_(None))
        .first()
    )                                                        # Current active run for live workspace context

    # -----------------------------------------------------------
    # - Load assigned routes
    # - Preload route, run, stop, and rider details for the workspace
    # -----------------------------------------------------------
    available_routes = (
        db.query(route_model.Route)
        .options(
            joinedload(route_model.Route.schools),           # Route header school list
            joinedload(route_model.Route.driver_assignments).joinedload(RouteDriverAssignment.driver),  # Assigned driver display
            joinedload(route_model.Route.runs).joinedload(run_model.Run.stops),  # Run -> stop hierarchy
            joinedload(route_model.Route.runs).joinedload(run_model.Run.student_assignments).joinedload(StudentRunAssignment.student).joinedload(student_model.Student.school),  # Run -> stop -> student hierarchy
            joinedload(route_model.Route.runs).joinedload(run_model.Run.student_assignments).joinedload(StudentRunAssignment.stop),  # Assignment stop grouping
        )
        .filter(route_model.Route.driver_assignments.any(and_(
            RouteDriverAssignment.driver_id == driver_id,
            RouteDriverAssignment.active.is_(True),
        )))
        .order_by(route_model.Route.route_number.asc(), route_model.Route.id.asc())
        .all()
    )                                                        # Driver-selectable route workspace choices

    # -----------------------------------------------------------
    # - Resolve selected route
    # - Keep route selection explicit for flexible route-first browsing
    # -----------------------------------------------------------
    selected_route = None                                    # Keep route selection explicit for route-first browsing
    if route_id is not None:
        selected_route = next((route for route in available_routes if route.id == route_id), None)

    # -----------------------------------------------------------
    # - Build selected workspace
    # - Include selected run review state when present
    # -----------------------------------------------------------
    workspace = _build_route_workspace(selected_route, run_id) if selected_route else None

    return templates.TemplateResponse(
        request,                                              # Request must be first
        "driver_run.html", {
            "request": request,
            "driver_id": driver_id,
            "driver_name": current_driver.name,
            "available_routes": available_routes,
            "selected_route_id": selected_route.id if selected_route else None,
            "workspace": workspace,
            "active_run_id": active_run.id if active_run else None,
            "active_route_id": active_run.route_id if active_run else None,
            "selected_run_id": run_id,
            "today": datetime.now().date().isoformat(),
        }
    )


# -----------------------------------------------------------
# PAYROLL ATTENDANCE SUMMARY PAGE
# -----------------------------------------------------------
@app.get("/summary_report", response_class=HTMLResponse)
def summary_report(request: Request, start: date = None, end: date = None, db: Session = Depends(get_db)):
    """Shows payroll attendance summary between given dates."""
    end = end or date.today()
    start = start or end
    records = db.query(dispatch_model.Payroll).filter(
        dispatch_model.Payroll.work_date.between(start, end)
    ).all()
    total_drivers = len({r.driver_id for r in records})
    approved_days = sum(1 for r in records if r.approved)
    pending_days = len(records) - approved_days
    total_charter_hours = sum(float(r.charter_hours or 0) for r in records)

    return templates.TemplateResponse(
        request,                                              # Updated argument order
        "summary_report.html",                                # Template name
        {
            "request": request,
            "records": records,
            "start_date": start,
            "end_date": end,
            "total_drivers": total_drivers,
            "approved_days": approved_days,
            "pending_days": pending_days,
            "total_charter_hours": round(total_charter_hours, 2),
        },
    )


# -----------------------------------------------------------
# LOGIN / LOGOUT ENDPOINTS
# -----------------------------------------------------------
@app.post("/login")
def login(payload: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    driver_id = int(payload["driver_id"])
    driver = db.get(driver_model.Driver, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    login_driver(request, driver_id)
    return {"message": "Logged in", "driver_id": driver_id}


@app.post("/logout")
def logout(request: Request):
    """Clears current driver session."""
    logout_driver(request)
    return {"message": "Logged out"}


# -----------------------------------------------------------
# HEALTH CHECK ENDPOINT
# -----------------------------------------------------------
@app.get("/")
def root():
    """Basic API health endpoint."""
    return {"status": "SBT backend is running"}


# -----------------------------------------------------------
# DATABASE INITIALIZATION
# -----------------------------------------------------------
# Import all models for Base metadata and create tables if not exist
from database import Base, engine
from backend.models import *  # noqa: F403, F401
Base.metadata.create_all(bind=engine)
