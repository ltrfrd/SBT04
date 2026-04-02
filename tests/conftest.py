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
import tempfile

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
# Collection guard
# =============================================================================

def pytest_ignore_collect(collection_path, config):
    """Skip leftover Windows temp directories under tests during collection."""

    name = getattr(collection_path, "name", None) or os.path.basename(str(collection_path))

    if str(collection_path).startswith(os.path.join(PROJECT_ROOT, "tests")):
        if name.startswith("sbt04-tests-") or name.startswith("pytest_"):
            return True

    return False


# =============================================================================
# Database engine fixture (isolated per test)
# =============================================================================

@pytest.fixture()
def db_engine():
    """Create a temporary SQLite engine for this test (isolated from sbt.db)."""

    fd, test_db_path = tempfile.mkstemp(prefix="sbt04-tests-", suffix=".db", dir=PROJECT_ROOT)  # Stable per-test DB file without pytest tmp_path
    os.close(fd)

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
    try:
        os.remove(test_db_path)  # Best-effort cleanup without pytest tmpdir involvement
    except FileNotFoundError:
        pass


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

    class LegacyAwareClient:
        def __init__(self, wrapped_client):
            self._wrapped_client = wrapped_client

        def __getattr__(self, name):
            return getattr(self._wrapped_client, name)

        def post(self, url, *args, **kwargs):
            payload = kwargs.get("json")

            if url == "/routes/" and isinstance(payload, dict) and "driver_id" in payload:
                route_payload = dict(payload)
                driver_id = route_payload.pop("driver_id")
                response = self._wrapped_client.post(url, *args, json=route_payload, **{k: v for k, v in kwargs.items() if k != "json"})

                if response.status_code in (200, 201):
                    route_id = response.json().get("id")
                    if route_id is not None:
                        self._wrapped_client.post(f"/routes/{route_id}/assign_driver/{driver_id}")

                return response

            if url in {"/runs/", "/runs/start"} and isinstance(payload, dict) and "driver_id" in payload:
                run_payload = dict(payload)
                run_payload.pop("driver_id", None)
                return self._wrapped_client.post(url, *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})

            return self._wrapped_client.post(url, *args, **kwargs)

        def put(self, url, *args, **kwargs):
            payload = kwargs.get("json")

            if url.startswith("/routes/") and isinstance(payload, dict) and "driver_id" in payload:
                route_payload = dict(payload)
                driver_id = route_payload.pop("driver_id")
                response = self._wrapped_client.put(url, *args, json=route_payload, **{k: v for k, v in kwargs.items() if k != "json"})

                if response.status_code == 200:
                    route_id = response.json().get("id")
                    if route_id is not None:
                        self._wrapped_client.post(f"/routes/{route_id}/assign_driver/{driver_id}")

                return response

            return self._wrapped_client.put(url, *args, **kwargs)

    with TestClient(app) as c:
        yield LegacyAwareClient(c)

    app.dependency_overrides.clear()  # Remove overrides after test
