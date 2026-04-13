# ===========================================================
# app.py - FleetOS FastAPI Application Entry Point
# -----------------------------------------------------------
# Fully documented version: all imports, functions, and logic explained.
# ===========================================================

# ---------- SYSTEM ----------
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

# ---------- FASTAPI ----------
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
# ---------- DB & MODELS ----------
from database import Base, engine, get_db
import backend.models  # noqa: F401

# ---------- ROUTERS ----------
from backend.routers import (
    auth, bus, district, driver, school, student, route, stop, run, dispatch, reports, student_run_assignment, web_pages, ws, pretrip, posttrip
)  # Import active routers through reports ownership


# -----------------------------------------------------------
# Lifespan - App startup/shutdown handler
# -----------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
# -----------------------------------------------------------
# APP SETUP
# -----------------------------------------------------------
app = FastAPI(
    title="FleetOS - School Bus Tracking System",
    version="1.0.0",
    lifespan=lifespan,
)
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


# -----------------------------------------------------------
# ROUTERS REGISTRATION
# -----------------------------------------------------------
# Each router defines its own endpoints (CRUD APIs)
app.include_router(driver.router)  # Register driver endpoints
app.include_router(bus.router)  # Register bus endpoints
app.include_router(district.router)  # Register district planning entry points
app.include_router(school.router)  # Register school endpoints
app.include_router(student.router)  # Register student endpoints
app.include_router(route.router)  # Register route endpoints
app.include_router(stop.router)  # Register stop endpoints
app.include_router(run.router)  # Register run endpoints
app.include_router(dispatch.router)  # Register dispatch endpoints
app.include_router(reports.router)  # Register reports endpoints
app.include_router(student_run_assignment.router)  # Register student run assignment endpoints
app.include_router(reports.student_bus_absence_router)  # Register absence endpoints through reports ownership
app.include_router(pretrip.router)  # Register pre-trip inspection endpoints
app.include_router(posttrip.router)  # Register post-trip inspection endpoints
app.include_router(web_pages.router)  # Register HTML page endpoints
app.include_router(auth.router)  # Register auth/session endpoints
app.include_router(ws.router)  # Register websocket endpoints


# -----------------------------------------------------------
# HEALTH CHECK ENDPOINT
# -----------------------------------------------------------
@app.get("/")
def root():
    """Basic API health endpoint."""
    return {"status": "FleetOS backend is running"}
