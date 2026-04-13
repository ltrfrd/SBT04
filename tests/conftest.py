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
from datetime import date
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # Repo root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)  # Ensure repo root is importable

TEST_DRIVER_PIN = "1234"
TEST_DEFAULT_DRIVER_EMAIL = "default-driver@fleetos-tests.internal"


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
from backend.models.operator import Operator                                        # Operator model for direct DB bootstrap
from backend.models.driver import Driver                                          # Driver model for direct DB bootstrap
from backend.utils.auth import hash_driver_pin                                    # PIN hashing for DB-direct driver creation


# =============================================================================
# DB-direct bootstrap helpers (bypass API to avoid auth chicken-and-egg)
# =============================================================================

def _create_operator_in_db(db_engine, name: str) -> int:
    """Create a operator directly in the DB for test bootstrap."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        operator = Operator(name=name)
        db.add(operator)
        db.commit()
        db.refresh(operator)
        return operator.id
    finally:
        db.close()


def _create_driver_in_db(
    db_engine,
    operator_id: int,
    name: str,
    email: str,
    pin: str = TEST_DRIVER_PIN,
) -> int:
    """Create a driver directly in the DB, bypassing the API, for test session bootstrap."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        d = Driver(
            name=name,
            email=email,
            operator_id=operator_id,
            pin_hash=hash_driver_pin(pin),
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        return d.id
    finally:
        db.close()


# =============================================================================
# Test preparation helper
# =============================================================================

def ensure_prepared_run_student(client, run_id: int):
    """Create the minimum canonical student fixture required for /runs/start."""

    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    run_data = run_response.json()

    if run_data["students"]:
        return run_data["students"][0]

    assert run_data["stops"], "Run must have stops before preparing a runtime student"

    route_id = run_data["route"]["route_id"]
    route_response = client.get(f"/routes/{route_id}")
    assert route_response.status_code == 200
    route_data = route_response.json()

    schools = route_data.get("schools", [])
    if schools:
        school_id = schools[0]["school_id"]
    else:
        school_response = client.post(
            "/schools/",
            json={
                "name": f"Prepared School {run_id}",
                "address": f"{run_id} Prepared Way",
            },
        )
        assert school_response.status_code in (200, 201)
        school_id = school_response.json()["id"]

        update_payload = {
            "route_number": route_data["route_number"],
            "school_ids": [school_id],
        }

        route_update = client.put(f"/routes/{route_id}", json=update_payload)
        assert route_update.status_code == 200

    first_stop_id = run_data["stops"][0]["stop_id"]
    student_response = client.post(
        f"/runs/{run_id}/stops/{first_stop_id}/students",
        json={
            "name": f"Prepared Student {run_id}",
            "grade": "1",
            "school_id": school_id,
        },
    )
    assert student_response.status_code in (200, 201)
    return student_response.json()
# =============================================================================
# Collection guard
# =============================================================================

def pytest_ignore_collect(collection_path, config):
    """Skip leftover Windows temp directories under tests during collection."""

    name = getattr(collection_path, "name", None) or os.path.basename(str(collection_path))

    if str(collection_path).startswith(os.path.join(PROJECT_ROOT, "tests")):
        if "-tests-" in name or name.startswith("pytest_"):
            return True

    return False


# =============================================================================
# Database engine fixture (isolated per test)
# =============================================================================

@pytest.fixture()
def db_engine():
    """Create a temporary SQLite engine for this test (isolated from fleetos.db)."""

    fd, test_db_path = tempfile.mkstemp(prefix="fleetos-tests-", suffix=".db", dir=PROJECT_ROOT)  # Stable per-test DB file without pytest tmp_path
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

            def _with_default_run_schedule(run_payload: dict) -> dict:
                enriched = dict(run_payload)
                enriched.setdefault("scheduled_start_time", "07:00:00")
                enriched.setdefault("scheduled_end_time", "08:00:00")
                return enriched

            if url == "/routes/" and isinstance(payload, dict) and "driver_id" in payload:
                route_payload = dict(payload)
                driver_id = route_payload.pop("driver_id")
                response = self._wrapped_client.post(url, *args, json=route_payload, **{k: v for k, v in kwargs.items() if k != "json"})

                if response.status_code in (200, 201):
                    route_id = response.json().get("id")
                    if route_id is not None:
                        self._wrapped_client.post(f"/routes/{route_id}/assign_driver/{driver_id}")

                return response

            if url == "/runs/" and isinstance(payload, dict) and "driver_id" in payload:
                run_payload = _with_default_run_schedule(payload)
                run_payload.pop("driver_id", None)
                route_id = run_payload.pop("route_id", None)
                if route_id is None:
                    return self._wrapped_client.post(url, *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                return self._wrapped_client.post(f"/routes/{route_id}/runs", *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})

            if url == "/runs/" and isinstance(payload, dict):
                run_payload = _with_default_run_schedule(payload)
                route_id = run_payload.pop("route_id", None)
                if route_id is None:
                    return self._wrapped_client.post(url, *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                return self._wrapped_client.post(f"/routes/{route_id}/runs", *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})

            if url == "/stops/" and isinstance(payload, dict):
                stop_payload = dict(payload)
                run_id = stop_payload.pop("run_id", None)
                if run_id is None:
                    return self._wrapped_client.post(url, *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                return self._wrapped_client.post(f"/runs/{run_id}/stops", *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})

            if url.startswith("/routes/") and url.endswith("/stops") and isinstance(payload, dict):
                stop_payload = dict(payload)
                run_id = stop_payload.pop("run_id", None)
                if run_id is None:
                    return self._wrapped_client.post(url, *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                route_path = url.rstrip("/")
                return self._wrapped_client.post(f"{route_path}/runs/{run_id}/stops", *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})

            if url.startswith("/routes/") and url.endswith("/runs") and isinstance(payload, dict):
                return self._wrapped_client.post(url, *args, json=_with_default_run_schedule(payload), **{k: v for k, v in kwargs.items() if k != "json"})

            if url == "/students/" and isinstance(payload, dict) and "route_id" in payload:
                student_payload = dict(payload)
                route_id = student_payload.pop("route_id", None)
                student_payload.pop("district_id", None)
                return self._wrapped_client.post(f"/routes/{route_id}/students", *args, json=student_payload, **{k: v for k, v in kwargs.items() if k != "json"})

            if url.startswith("/runs/start"):
                parsed = urlparse(url)
                run_id_values = parse_qs(parsed.query).get("run_id", [])
                if run_id_values:
                    run_id = int(run_id_values[0])
                    run_response = self._wrapped_client.get(f"/runs/{run_id}")
                    if run_response.status_code == 200:
                        run_data = run_response.json()
                        route_response = self._wrapped_client.get(f"/routes/{run_data['route_id']}")
                        if route_response.status_code == 200:
                            route_data = route_response.json()
                            active_bus_id = route_data.get("active_bus_id") or route_data.get("bus_id")

                            if active_bus_id is None:
                                bus_response = self._wrapped_client.post(
                                    "/buses/",
                                    json={
                                        "bus_number": f"AUTO-BUS-{run_id}",
                                        "license_plate": f"AUTO-{run_id}",
                                        "capacity": 48,
                                        "size": "full",
                                    },
                                )
                                assert bus_response.status_code in (200, 201)
                                active_bus_id = bus_response.json()["id"]
                                assign_response = self._wrapped_client.post(f"/routes/{run_data['route_id']}/assign_bus/{active_bus_id}")
                                assert assign_response.status_code == 200

                            pretrip_response = self._wrapped_client.get(f"/pretrips/bus/{active_bus_id}/today")
                            if pretrip_response.status_code == 404:
                                bus_detail = self._wrapped_client.get(f"/buses/{active_bus_id}")
                                assert bus_detail.status_code == 200
                                bus_data = bus_detail.json()
                                create_pretrip = self._wrapped_client.post(
                                    "/pretrips/",
                                    json={
                                        "bus_number": bus_data["bus_number"],
                                        "license_plate": bus_data["license_plate"],
                                        "driver_name": run_data.get("driver_name") or "Prepared Driver",
                                        "inspection_date": date.today().isoformat(),
                                        "inspection_time": "06:30:00",
                                        "odometer": 1000 + run_id,
                                        "inspection_place": "Test Yard",
                                        "use_type": "school_bus",
                                        "brakes_checked": True,
                                        "lights_checked": True,
                                        "tires_checked": True,
                                        "emergency_equipment_checked": True,
                                        "fit_for_duty": "yes",
                                        "no_defects": True,
                                        "signature": "test-signature",
                                        "defects": [],
                                    },
                                )
                                assert create_pretrip.status_code in (200, 201)

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
        legacy = LegacyAwareClient(c)

        # Bootstrap: create default operator + driver directly in DB, then login.
        # get_operator_context now requires a valid session (no unauthenticated fallback),
        # so every test must start with an authenticated session.
        default_operator_id = _create_operator_in_db(db_engine, "Default Operator")
        default_driver_id = _create_driver_in_db(
            db_engine,
            default_operator_id,
            "Default Driver",
            TEST_DEFAULT_DRIVER_EMAIL,
        )
        login_r = c.post("/login", json={"driver_id": default_driver_id, "pin": TEST_DRIVER_PIN})
        assert login_r.status_code == 200, f"Test bootstrap login failed: {login_r.text}"

        yield legacy

    app.dependency_overrides.clear()  # Remove overrides after test

