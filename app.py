# ===========================================================
# app.py — BST FastAPI Application Entry Point
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
    status, WebSocket, WebSocketDisconnect
)                                        # Core FastAPI imports
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates  # For rendering HTML templates
from fastapi.middleware.cors import CORSMiddleware  # Allow cross-domain requests
from fastapi.staticfiles import StaticFiles         # Serve static files (CSS, JS)
from starlette.middleware.sessions import SessionMiddleware  # Session handling
from sqlalchemy.orm import Session         # Database session for ORM
from datetime import datetime, date        # For timestamps and date filters
import json                                # Parse JSON payloads
from typing import Dict, List              # Type hints for dictionaries/lists
from fastapi import Body
# ---------- DB & MODELS ----------
from database import get_db, engine, Base   # Local database setup (SQLAlchemy)
from backend import schemas                 # Import Pydantic schemas
from backend.models import (                # Import model modules for ORM binding
    driver as driver_model,
    school as school_model,
    student as student_model,
    route as route_model,
    run as run_model,
    payroll as payroll_model
)

# ---------- ROUTERS ----------
# Import each router module (each exposes a .router object)
from backend.routers import (
    driver, school, student, route, stop, run, payroll, report
)

# ---------- UTILS ----------
# Custom utilities: GPS tools and authentication helpers
from backend.utils import gps_tools
from backend.utils.auth import get_current_driver, login_driver, logout_driver

# ---------- WEBSOCKET TRACKING ----------
# Active WebSocket connections per run_id (real-time GPS broadcasting)
active_connections: Dict[int, List[WebSocket]] = {}


# -----------------------------------------------------------
# APP SETUP
# -----------------------------------------------------------
app = FastAPI(title="BST — School Bus Tracking System", version="1.0.0")

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
app.include_router(driver.router)
app.include_router(school.router)
app.include_router(student.router)
app.include_router(route.router)
app.include_router(stop.router)
app.include_router(run.router)
app.include_router(payroll.router)
app.include_router(report.router)


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
    return templates.TemplateResponse("dashboard.html", {"request": request, **counts})


# -----------------------------------------------------------
# ROUTE REPORT PAGE
# -----------------------------------------------------------
@app.get("/route_report/{route_id}", response_class=HTMLResponse)
def route_report(route_id: int, request: Request, db: Session = Depends(get_db)):
    """Shows route-specific report including driver name and route details."""
    route = db.get(route_model.Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    driver_name = route.driver.name if route.driver else "Unassigned"
    return templates.TemplateResponse("route_report.html", {
        "request": request,
        "route": route,
        "driver_name": driver_name
    })


# -----------------------------------------------------------
# DRIVER RUN PAGE
# -----------------------------------------------------------
@app.get("/driver_run/{driver_id}", response_class=HTMLResponse)
def driver_run_view(
    driver_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_driver: driver_model.Driver = Depends(get_current_driver)
):
    """Renders driver's active or pending run view with route and stop data."""
    if not current_driver:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get current active run (if any)
    active_run = db.query(run_model.Run).filter(
        run_model.Run.driver_id == driver_id,
        run_model.Run.end_time.is_(None)
    ).first()

    # Determine run state and stops
    run_status = "active" if active_run else "pending"
    stops = sorted(active_run.route.stops, key=lambda s: s.sequence) if active_run else []
    current_stop_index = 1

    return templates.TemplateResponse("driver_run.html", {
        "request": request,
        "driver_id": driver_id,
        "driver_name": current_driver.name,
        "run_status": run_status,
        "run": active_run,
        "route": active_run.route if active_run else None,
        "stops": stops,
        "current_stop_index": current_stop_index,
        "available_routes": db.query(route_model.Route).all(),
        "today": datetime.now().date().isoformat()
    })


# -----------------------------------------------------------
# PAYROLL SUMMARY REPORT
# -----------------------------------------------------------
@app.get("/summary_report", response_class=HTMLResponse)
def summary_report(request: Request, start: date = None, end: date = None, db: Session = Depends(get_db)):
    """Shows payroll summary between given dates."""
    end = end or date.today()
    start = start or end
    records = db.query(payroll_model.Payroll).filter(
        payroll_model.Payroll.work_date.between(start, end)
    ).all()
    total_drivers = len({r.driver_id for r in records})
    approved_days = sum(1 for r in records if r.approved)
    pending_days = len(records) - approved_days
    total_charter_hours = sum(float(r.charter_hours or 0) for r in records)

    return templates.TemplateResponse("summary_report.html", {
        "request": request,
        "records": records,
        "start_date": start,
        "end_date": end,
        "total_drivers": total_drivers,
        "approved_days": approved_days,
        "pending_days": pending_days,
        "total_charter_hours": round(total_charter_hours, 2)
    })


# -----------------------------------------------------------
# LOGIN / LOGOUT ENDPOINTS
# -----------------------------------------------------------
from fastapi import Request, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from backend.models import driver as driver_model
from database import get_db

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
    return {"status": "BST01 backend is running"}


# -----------------------------------------------------------
# DATABASE INITIALIZATION
# -----------------------------------------------------------
# Import all models for Base metadata and create tables if not exist
from database import Base, engine
from backend.models import *  # noqa: F403, F401
Base.metadata.create_all(bind=engine)
