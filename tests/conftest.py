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
import shutil
import sys  # Python import path control
import tempfile
import json
from base64 import b64encode
from uuid import uuid4
from itsdangerous import TimestampSigner

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
from backend.config import settings
from backend.models import driver, route, run          # Core models used by app
from backend.models import associations                                            # Ensure StudentRunAssignment is registered
from backend.models.operator import Operator                                        # Operator model for direct DB bootstrap
from backend.models.driver import Driver                                          # Driver model for direct DB bootstrap
from backend.models.yard import Yard


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
) -> int:
    """Create a driver directly in the DB for fixture setup."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        yard = (
            db.query(Yard)
            .filter(Yard.operator_id == operator_id)
            .order_by(Yard.id.asc())
            .first()
        )
        if yard is None:
            yard = Yard(name="Main Yard", operator_id=operator_id)
            db.add(yard)
            db.flush()

        d = Driver(
            name=name,
            email=email,
            yard_id=yard.id,
            pin_hash="test-hash",
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        return d.id
    finally:
        db.close()


def _set_operator_session(client, operator_id: int):
    signer = TimestampSigner(os.getenv("SESSION_SECRET", "dev-secret-key-change-in-prod"))
    session_payload = b64encode(json.dumps({"operator_id": operator_id}).encode("utf-8"))
    session_cookie = signer.sign(session_payload).decode("utf-8")
    cookie_client = getattr(client, "_wrapped_client", client)
    cookie_client.cookies.set("session", session_cookie, path="/")
    if hasattr(client, "_operator_id"):
        client._operator_id = operator_id
    if hasattr(client, "_yard_ids"):
        client._yard_ids.pop(operator_id, None)


def _get_client_db_engine(client):
    wrapped_client = getattr(client, "_wrapped_client", client)
    override = wrapped_client.app.dependency_overrides[get_db]
    for cell in override.__closure__ or ():
        candidate = cell.cell_contents
        bind = getattr(candidate, "kw", {}).get("bind")
        if bind is not None:
            return bind
    raise AssertionError("Unable to resolve test database engine from client fixture")


def _get_or_create_operator_yard_id(db_engine, operator_id: int) -> int:
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        yard = (
            db.query(Yard)
            .filter(Yard.operator_id == operator_id)
            .order_by(Yard.id.asc())
            .first()
        )
        if yard is None:
            yard = Yard(name="Main Yard", operator_id=operator_id)
            db.add(yard)
            db.commit()
            db.refresh(yard)
        return yard.id
    finally:
        db.close()


def ensure_route_has_execution_yard(client, route_id: int, *, operator_id: int = 1):
    db_engine = _get_client_db_engine(client)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        route_row = db.get(route.Route, route_id)
        assert route_row is not None, f"Route {route_id} not found in test DB"

        district_id = route_row.district_id
        existing_yard_ids = {yard.id for yard in route_row.yards}
    finally:
        db.close()

    assert district_id is not None, f"Route {route_id} must have a district before yard assignment"

    yard_id = _get_or_create_operator_yard_id(db_engine, operator_id)
    if yard_id in existing_yard_ids:
        return yard_id

    assigned = client.post(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert assigned.status_code == 200, assigned.text
    return yard_id


def _get_run_route_id(client, run_id: int) -> int | None:
    db_engine = _get_client_db_engine(client)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        run_row = db.get(run.Run, run_id)
        return run_row.route_id if run_row is not None else None
    finally:
        db.close()


def ensure_run_has_execution_yard(client, run_id: int, *, operator_id: int = 1) -> int | None:
    route_id = _get_run_route_id(client, run_id)
    if route_id is None:
        return None
    ensure_route_has_execution_yard(client, route_id, operator_id=operator_id)
    return route_id


# =============================================================================
# Test preparation helper
# =============================================================================

def ensure_prepared_run_student(client, run_id: int):
    """Create the minimum canonical student fixture required for /runs/start."""

    route_id = ensure_run_has_execution_yard(client, run_id)
    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    run_data = run_response.json()

    if run_data["students"]:
        return run_data["students"][0]

    assert run_data["stops"], "Run must have stops before preparing a runtime student"

    route_id = route_id or run_data["route"]["route_id"]
    ensure_route_has_execution_yard(client, route_id)
    route_response = client.get(f"/routes/{route_id}")
    assert route_response.status_code == 200
    route_data = route_response.json()

    schools = route_data.get("schools", [])
    if schools:
        school_id = schools[0]["school_id"]
    else:
        route_row = None
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
        db = TestingSessionLocal()
        try:
            route_row = db.get(route.Route, route_id)
        finally:
            db.close()

        assert route_row is not None
        assert route_row.district_id is not None
        school_response = client.post(
            f"/districts/{route_row.district_id}/schools",
            json={
                "name": f"Prepared School {run_id}",
                "address": f"{run_id} Prepared Way",
            },
        )
        assert school_response.status_code in (200, 201)
        school_id = school_response.json()["id"]

        update_payload = {
            "route_number": route_row.route_number,
            "school_ids": [school_id],
        }

        route_update = client.put(
            f"/districts/{route_row.district_id}/routes/{route_id}",
            json=update_payload,
        )
        assert route_update.status_code == 200

    first_stop_id = run_data["stops"][0]["stop_id"]
    route_row = None
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        route_row = db.get(route.Route, route_id)
    finally:
        db.close()

    assert route_row is not None
    assert route_row.district_id is not None
    student_response = client.post(
        f"/districts/{route_row.district_id}/routes/{route_id}/runs/{run_id}/stops/{first_stop_id}/students",
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
    media_root = os.path.join(PROJECT_ROOT, "backend", "media", f"test_{uuid4().hex}")
    os.makedirs(media_root, exist_ok=True)
    previous_media_root = settings.MEDIA_ROOT
    settings.MEDIA_ROOT = media_root

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
    try:
        yield engine  # Provide engine to tests
    finally:
        Base.metadata.drop_all(bind=engine)  # Drop tables after test
        engine.dispose()  # Release file handles (important on Windows)
        settings.MEDIA_ROOT = previous_media_root
        try:
            os.remove(test_db_path)  # Best-effort cleanup without pytest tmpdir involvement
        except FileNotFoundError:
            pass
        shutil.rmtree(media_root, ignore_errors=True)


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
            self._operator_id: int | None = 1
            self._yard_ids: dict[int, int] = {}

        def _current_operator_id(self):
            return self._operator_id or 1

        def ensure_route_has_execution_yard(self, route_id: int):
            return ensure_route_has_execution_yard(
                self,
                route_id,
                operator_id=self._current_operator_id(),
            )

        def ensure_run_has_execution_yard(self, run_id: int):
            return ensure_run_has_execution_yard(
                self,
                run_id,
                operator_id=self._current_operator_id(),
            )

        def ensure_current_operator_yard_id(self, *, name: str | None = None) -> int:
            operator_id = self._current_operator_id()
            if operator_id in self._yard_ids:
                return self._yard_ids[operator_id]

            yards_response = self._wrapped_client.get("/yards/")
            assert yards_response.status_code == 200, yards_response.text
            yards = yards_response.json()
            if yards:
                yard_id = int(yards[0]["id"])
                self._yard_ids[operator_id] = yard_id
                return yard_id

            create_response = self._wrapped_client.post(
                "/yards/",
                json={"name": name or f"Operator {operator_id} Yard"},
            )
            assert create_response.status_code in (200, 201), create_response.text
            yard_id = int(create_response.json()["id"])
            self._yard_ids[operator_id] = yard_id
            return yard_id

        def __getattr__(self, name):
            return getattr(self._wrapped_client, name)

        def get(self, url, *args, **kwargs):
            return self._wrapped_client.get(url, *args, **kwargs)

        def post(self, url, *args, **kwargs):
            return self._wrapped_client.post(url, *args, **kwargs)

        def put(self, url, *args, **kwargs):
            return self._wrapped_client.put(url, *args, **kwargs)

        def delete(self, url, *args, **kwargs):
            return self._wrapped_client.delete(url, *args, **kwargs)

    with TestClient(app) as c:
        legacy = LegacyAwareClient(c)

        # Bootstrap: create default operator + driver directly in DB, then set the
        # authenticated session cookie required by get_operator_context().
        default_operator_id = _create_operator_in_db(db_engine, "Default Operator")
        _create_driver_in_db(
            db_engine,
            default_operator_id,
            "Default Driver",
            TEST_DEFAULT_DRIVER_EMAIL,
        )
        _set_operator_session(c, default_operator_id)

        yield legacy

    app.dependency_overrides.clear()  # Remove overrides after test


@pytest.fixture()
def empty_client(db_engine):
    """FastAPI TestClient backed by an empty DB — no default operator pre-created."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
