# =============================================================================
# tests/conftest.py
# -----------------------------------------------------------------------------
# Shared pytest fixtures:
#   - PATH fix so `import backend` works on Windows
#   - Isolated SQLite DB per test (tmp_path)
#   - FastAPI TestClient with get_db overridden to use the test DB
# =============================================================================

# =============================================================================
# PATH FIX (MUST BE FIRST)
# =============================================================================

import os  # Path utilities
import sys  # Python import path control

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # Repo root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)  # Ensure repo root is importable


# =============================================================================
# Imports (after PATH FIX)
# =============================================================================

import pytest  # Pytest fixtures
from sqlalchemy import create_engine  # DB engine factory
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker  # Session factory

from database import Base  # SQLAlchemy Base (root database.py)
from app import app, get_db  # FastAPI app + DB dependency
from backend.models import driver, school, student, route, run, dispatch          # Core models used by app
from backend.models import associations                                            # Ensure StudentRunAssignment is registered
# =============================================================================
# Database engine fixture (isolated per test)
# =============================================================================

@pytest.fixture()
def db_engine(tmp_path):
    """Create a temporary SQLite engine for this test (isolated from sbt.db)."""

    test_db_path = tmp_path / "test_sbt.db"  # Unique temp DB file per test

    engine = create_engine(
        f"sqlite:///{test_db_path}",  # File-based SQLite in temp directory
        connect_args={"check_same_thread": False},  # Needed for TestClient threads
        pool_pre_ping=True,  # Helps avoid stale connections
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    
    Base.metadata.create_all(bind=engine)  # Create tables
    yield engine  # Provide engine to tests
    Base.metadata.drop_all(bind=engine)  # Drop tables after test
    engine.dispose()  # Release file handles (important on Windows)


# =============================================================================
# Test client fixture (overrides get_db to use db_engine)
# =============================================================================

@pytest.fixture()
def client(db_engine):
    """FastAPI TestClient with get_db overridden to use the temporary test DB."""

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_engine,
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
            db.commit()  # Flush/close transaction cleanly (prevents SQLite locks)
        except Exception:
            db.rollback()  # Prevent open transactions holding locks
            raise
        finally:
            db.close()  # Always release connection

    app.dependency_overrides[get_db] = override_get_db  # Override DB dependency

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()  # Remove overrides after test
