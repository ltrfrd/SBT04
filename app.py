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
    bus,
    district,
    dispatch,
    driver,
    posttrip,
    pretrip,
    reports,
    route,
    run,
    school,
    session,
    stop,
    student,
    student_run_assignment,
    ws,
)
from backend.web import web_pages


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
# Yard domain routers
app.include_router(driver.router)
app.include_router(bus.router)
app.include_router(dispatch.router)
app.include_router(pretrip.router)
app.include_router(posttrip.router)
app.include_router(reports.router)
app.include_router(session.router)

# School domain routers
app.include_router(district.router)
app.include_router(school.router)
app.include_router(student.router)
app.include_router(route.router)
app.include_router(stop.router)
app.include_router(run.router)
app.include_router(student_run_assignment.router)
app.include_router(reports.student_bus_absence_router)

# UI and realtime routers
app.include_router(web_pages.router)
app.include_router(ws.router)


# -----------------------------------------------------------
# HEALTH CHECK ENDPOINT
# -----------------------------------------------------------
@app.get("/")
def root():
    """Basic API health endpoint."""
    return {"status": "FleetOS backend is running"}
