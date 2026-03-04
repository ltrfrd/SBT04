# ===========================================================
# database.py — Database Configuration (SBT01)
# -----------------------------------------------------------
# Responsibilities:
#   - Load environment variables
#   - Create SQLAlchemy engine
#   - Provide SessionLocal session factory
#   - Provide Base for ORM models
#   - Provide get_db() dependency for FastAPI
# ===========================================================

from __future__ import annotations                         # Forward refs for typing

# -----------------------------------------------------------
# Standard library
# -----------------------------------------------------------
import os                                                   # Environment variables
from typing import Generator                                # Generator typing

# -----------------------------------------------------------
# Third-party
# -----------------------------------------------------------
from dotenv import load_dotenv                              # Load .env into os.environ
from sqlalchemy import create_engine                         # Create DB engine
from sqlalchemy.orm import declarative_base  # SQLAlchemy 2.x: declarative_base now imported from sqlalchemy.orm
from sqlalchemy.orm import sessionmaker      # Session factory for creating DB sessions

# -----------------------------------------------------------
# Environment
# -----------------------------------------------------------
load_dotenv()                                               # Read .env and populate os.environ


# -----------------------------------------------------------
# Database URL
# -----------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sbt.db")  # Default SQLite path


# -----------------------------------------------------------
# Engine
# - SQLite needs check_same_thread=False
# - Other DBs (PostgreSQL) do not
# -----------------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)


# -----------------------------------------------------------
# Session factory
# - autocommit=False: explicit commit control
# - autoflush=False: predictable flush behavior
# -----------------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# -----------------------------------------------------------
# Base
# - All ORM models inherit from Base
# -----------------------------------------------------------
Base = declarative_base()


# -----------------------------------------------------------
# get_db
# - FastAPI dependency: yields a DB session per request
# - Ensures session is always closed
# -----------------------------------------------------------
def get_db() -> Generator:
    db = SessionLocal()                                     # Create new DB session
    try:
        yield db                                            # Provide session to route logic
    finally:
        db.close()                                          # Always close session