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
from uuid import uuid4
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
from backend.config import settings
from backend.models import driver, school, student, route, run, stop, dispatch          # Core models used by app
from backend.models import associations                                            # Ensure StudentRunAssignment is registered
from backend.models.operator import Operator                                        # Operator model for direct DB bootstrap
from backend.models.driver import Driver                                          # Driver model for direct DB bootstrap
from backend.models.district import District
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
    response = client.post("/session/operator", json={"operator_id": operator_id})
    assert response.status_code == 200, f"Operator session bootstrap failed: {response.text}"
    return response


def _get_or_create_test_district_id(db_engine, operator_id: int) -> int:
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        district = (
            db.query(District)
            .order_by(District.id.asc())
            .first()
        )
        if district is None:
            district = District(name=f"Test District {operator_id}")
            db.add(district)
            db.commit()
            db.refresh(district)
        return district.id
    finally:
        db.close()


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
            self._school_district_ids: dict[int, int] = {}
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

        def _ensure_school_payload_has_district(self, payload: dict) -> dict:
            school_payload = dict(payload)
            if school_payload.get("district_id") is None:
                school_payload["district_id"] = _get_or_create_test_district_id(
                    db_engine,
                    self._current_operator_id(),
                )
            return school_payload

        def _get_existing_school_payload_district(self, school_id: int) -> int | None:
            return self._get_school_district_id(school_id)

        def _remember_school_district(self, response):
            if response.status_code not in (200, 201):
                return response
            body = response.json()
            school_id = body.get("id")
            if school_id is not None:
                district_id = self._get_school_district_id(school_id)
                if district_id is not None:
                    self._school_district_ids[school_id] = district_id
            return response

        def _get_school_district_id(self, school_id: int) -> int | None:
            if school_id in self._school_district_ids:
                return self._school_district_ids[school_id]
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
            db = TestingSessionLocal()
            try:
                school_row = db.get(school.School, school_id)
                district_id = school_row.district_id if school_row else None
                if district_id is not None:
                    self._school_district_ids[school_id] = district_id
                return district_id
            finally:
                db.close()

        def _get_route_district_id(self, route_id: int) -> int | None:
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
            db = TestingSessionLocal()
            try:
                route_row = db.get(route.Route, route_id)
                return route_row.district_id if route_row else None
            finally:
                db.close()

        def _get_route_planning_snapshot(self, route_id: int) -> dict | None:
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
            db = TestingSessionLocal()
            try:
                route_row = db.get(route.Route, route_id)
                if route_row is None:
                    return None
                return {
                    "route_id": route_row.id,
                    "district_id": route_row.district_id,
                    "route_number": route_row.route_number,
                    "school_ids": [school_row.id for school_row in route_row.schools],
                }
            finally:
                db.close()

        def _get_run_context(self, run_id: int) -> dict | None:
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
            db = TestingSessionLocal()
            try:
                run_row = db.get(run.Run, run_id)
                if run_row is None:
                    return None
                route_row = db.get(route.Route, run_row.route_id) if run_row.route_id is not None else None
                district_id = route_row.district_id if route_row is not None else None
                return {
                    "run_id": run_row.id,
                    "route_id": run_row.route_id,
                    "district_id": district_id,
                }
            finally:
                db.close()

        def _get_stop_context(self, stop_id: int) -> dict | None:
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
            db = TestingSessionLocal()
            try:
                stop_row = db.get(stop.Stop, stop_id)
                if stop_row is None:
                    return None
                run_row = db.get(run.Run, stop_row.run_id) if stop_row.run_id is not None else None
                route_row = db.get(route.Route, run_row.route_id) if run_row is not None and run_row.route_id is not None else None
                district_id = route_row.district_id if route_row is not None else None
                return {
                    "stop_id": stop_row.id,
                    "run_id": stop_row.run_id,
                    "route_id": route_row.id if route_row is not None else None,
                    "district_id": district_id,
                }
            finally:
                db.close()

        def _ensure_route_payload_has_district(self, payload: dict) -> dict:
            route_payload = dict(payload)
            if route_payload.get("district_id") is not None:
                return route_payload
            school_ids = route_payload.get("school_ids") or []
            if school_ids:
                district_id = self._get_school_district_id(int(school_ids[0]))
                if district_id is not None:
                    route_payload["district_id"] = district_id
                    return route_payload
            route_payload["district_id"] = _get_or_create_test_district_id(
                db_engine,
                self._current_operator_id(),
            )
            return route_payload

        def _ensure_route_matches_school_district(self, school_id: int, route_id: int):
            school_district_id = self._get_school_district_id(school_id)
            if school_district_id is None:
                return
            current_route_district_id = self._get_route_district_id(route_id)
            if current_route_district_id is not None:
                return
            route_response = self._wrapped_client.get(f"/routes/{route_id}")
            if route_response.status_code != 200:
                return
            route_body = route_response.json()
            update_response = self._wrapped_client.put(
                f"/routes/{route_id}",
                json={
                    "route_number": route_body["route_number"],
                    "district_id": school_district_id,
                    "school_ids": route_body.get("school_ids", []),
                },
            )
            assert update_response.status_code == 200

        def _ensure_route_matches_payload_school(self, route_id: int, payload: dict | None):
            if not isinstance(payload, dict):
                return
            school_id = payload.get("school_id")
            if school_id is None:
                return
            self._ensure_route_matches_school_district(int(school_id), route_id)

        def __getattr__(self, name):
            return getattr(self._wrapped_client, name)

        def get(self, url, *args, **kwargs):
            parsed = urlparse(url)
            return self._wrapped_client.get(url, *args, **kwargs)

        def post(self, url, *args, **kwargs):
            payload = kwargs.get("json")

            def _with_default_run_schedule(run_payload: dict) -> dict:
                enriched = dict(run_payload)
                enriched.setdefault("scheduled_start_time", "07:00:00")
                enriched.setdefault("scheduled_end_time", "08:00:00")
                return enriched

            if url == "/schools/" and isinstance(payload, dict):
                school_payload = self._ensure_school_payload_has_district(payload)
                response = self._wrapped_client.post(
                    url,
                    *args,
                    json=school_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )
                return self._remember_school_district(response)

            if url == "/session/operator" and isinstance(payload, dict):
                response = self._wrapped_client.post(url, *args, **kwargs)
                if response.status_code == 200:
                    self._operator_id = int(response.json().get("operator_id", payload["operator_id"]))
                    self._yard_ids.pop(self._operator_id, None)
                return response

            if url == "/routes/" and isinstance(payload, dict) and "driver_id" in payload:
                route_payload = self._ensure_route_payload_has_district(payload)
                driver_id = route_payload.pop("driver_id")
                district_id = route_payload.pop("district_id")
                response = self._wrapped_client.post(
                    f"/districts/{district_id}/routes",
                    *args,
                    json=route_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

                if response.status_code in (200, 201):
                    route_id = response.json().get("id")
                    if route_id is not None:
                        self._wrapped_client.post(f"/routes/{route_id}/assign_driver/{driver_id}")

                return response

            if url == "/routes/" and isinstance(payload, dict):
                route_payload = self._ensure_route_payload_has_district(payload)
                district_id = route_payload.pop("district_id")
                return self._wrapped_client.post(
                    f"/districts/{district_id}/routes",
                    *args,
                    json=route_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if url.startswith("/schools/") and "/assign_route/" in url:
                path_parts = url.strip("/").split("/")
                school_id = int(path_parts[1])
                route_id = int(path_parts[3])
                self._ensure_route_matches_school_district(school_id, route_id)
                route_snapshot = self._get_route_planning_snapshot(route_id)
                assert route_snapshot is not None
                school_ids = route_snapshot["school_ids"]
                if school_id not in school_ids:
                    school_ids = [*school_ids, school_id]
                return self._wrapped_client.put(
                    f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
                    *args,
                    json={
                        "route_number": route_snapshot["route_number"],
                        "school_ids": school_ids,
                    },
                    **kwargs,
                )

            if url.startswith("/routes/") and url.endswith("/students"):
                route_id = int(url.strip("/").split("/")[1])
                self._ensure_route_matches_payload_school(route_id, payload)
                route_snapshot = self._get_route_planning_snapshot(route_id)
                assert route_snapshot is not None
                return self._wrapped_client.post(
                    f"/districts/{route_snapshot['district_id']}/routes/{route_id}/students",
                    *args,
                    **kwargs,
                )

            if url == "/runs/" and isinstance(payload, dict) and "driver_id" in payload:
                run_payload = _with_default_run_schedule(payload)
                run_payload.pop("driver_id", None)
                route_id = run_payload.pop("route_id", None)
                if route_id is None:
                    return self._wrapped_client.post(url, *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                district_id = self._get_route_district_id(route_id)
                assert district_id is not None
                return self._wrapped_client.post(
                    f"/districts/{district_id}/routes/{route_id}/runs",
                    *args,
                    json=run_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if url == "/runs/" and isinstance(payload, dict):
                run_payload = _with_default_run_schedule(payload)
                route_id = run_payload.pop("route_id", None)
                if route_id is None:
                    return self._wrapped_client.post(url, *args, json=run_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                district_id = self._get_route_district_id(route_id)
                assert district_id is not None
                return self._wrapped_client.post(
                    f"/districts/{district_id}/routes/{route_id}/runs",
                    *args,
                    json=run_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if url == "/stops/" and isinstance(payload, dict):
                stop_payload = dict(payload)
                run_id = stop_payload.pop("run_id", None)
                if run_id is None:
                    return self._wrapped_client.post(url, *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                run_context = self._get_run_context(run_id)
                if run_context is None:
                    return self._wrapped_client.post(url, *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                return self._wrapped_client.post(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{run_id}/stops",
                    *args,
                    json=stop_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                url.startswith("/routes/")
                and url.endswith("/stops")
                and "/runs/" not in url
                and isinstance(payload, dict)
            ):
                stop_payload = dict(payload)
                run_id = stop_payload.pop("run_id", None)
                if run_id is None:
                    return self._wrapped_client.post(url, *args, json=stop_payload, **{k: v for k, v in kwargs.items() if k != "json"})
                route_path = url.rstrip("/")
                route_id = int(route_path.strip("/").split("/")[1])
                district_id = self._get_route_district_id(route_id)
                assert district_id is not None
                return self._wrapped_client.post(
                    f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
                    *args,
                    json=stop_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len([part for part in url.strip("/").split("/") if part]) == 5
                and url.startswith("/routes/")
                and "/runs/" in url
                and url.endswith("/stops")
                and isinstance(payload, dict)
            ):
                path_parts = [part for part in url.strip("/").split("/") if part]
                route_id = int(path_parts[1])
                run_id = int(path_parts[3])
                district_id = self._get_route_district_id(route_id)
                if district_id is None:
                    return self._wrapped_client.post(url, *args, **kwargs)
                return self._wrapped_client.post(
                    f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if url.startswith("/routes/") and url.endswith("/runs") and isinstance(payload, dict):
                route_id = int(url.strip("/").split("/")[1])
                district_id = self._get_route_district_id(route_id)
                assert district_id is not None
                return self._wrapped_client.post(
                    f"/districts/{district_id}/routes/{route_id}/runs",
                    *args,
                    json=_with_default_run_schedule(payload),
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len([part for part in url.strip("/").split("/") if part]) == 3
                and url.startswith("/runs/")
                and url.endswith("/stops")
                and isinstance(payload, dict)
            ):
                path_parts = [part for part in url.strip("/").split("/") if part]
                run_id = int(path_parts[1])
                run_context = self._get_run_context(run_id)
                if run_context is None:
                    return self._wrapped_client.post(url, *args, **kwargs)
                return self._wrapped_client.post(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{run_id}/stops",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if url == "/students/" and isinstance(payload, dict) and "route_id" in payload:
                student_payload = dict(payload)
                route_id = student_payload.pop("route_id", None)
                self._ensure_route_matches_payload_school(route_id, student_payload)
                student_payload.pop("district_id", None)
                route_snapshot = self._get_route_planning_snapshot(route_id)
                assert route_snapshot is not None
                return self._wrapped_client.post(
                    f"/districts/{route_snapshot['district_id']}/routes/{route_id}/students",
                    *args,
                    json=student_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len([part for part in url.strip("/").split("/") if part]) >= 5
                and url.startswith("/runs/")
                and "/stops/" in url
                and url.endswith("/students")
                and isinstance(payload, dict)
            ):
                path_parts = [part for part in url.strip("/").split("/") if part]
                run_id = int(path_parts[1])
                stop_id = int(path_parts[3])
                run_context = self._get_run_context(run_id)
                if run_context is None:
                    return self._wrapped_client.post(url, *args, **kwargs)
                return self._wrapped_client.post(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{run_id}/stops/{stop_id}/students",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len([part for part in url.strip("/").split("/") if part]) >= 6
                and url.startswith("/runs/")
                and url.endswith("/students/bulk")
                and isinstance(payload, dict)
            ):
                path_parts = [part for part in url.strip("/").split("/") if part]
                run_id = int(path_parts[1])
                stop_id = int(path_parts[3])
                run_context = self._get_run_context(run_id)
                if run_context is None:
                    return self._wrapped_client.post(url, *args, **kwargs)
                return self._wrapped_client.post(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{run_id}/stops/{stop_id}/students/bulk",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len([part for part in url.strip("/").split("/") if part]) == 5
                and url.startswith("/runs/")
                and url.endswith("/school-status")
                and isinstance(payload, dict)
            ):
                path_parts = [part for part in url.strip("/").split("/") if part]
                run_id = int(path_parts[1])
                student_id = int(path_parts[3])
                run_context = self._get_run_context(run_id)
                if run_context is None:
                    return self._wrapped_client.post(url, *args, **kwargs)
                return self._wrapped_client.post(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{run_id}/students/{student_id}/school-status",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

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
                                        "yard_id": self.ensure_current_operator_yard_id(),
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
            path_parts = [part for part in url.strip("/").split("/") if part]

            if url.startswith("/schools/") and isinstance(payload, dict):
                school_payload = dict(payload)
                if school_payload.get("district_id") is None:
                    school_id = int(url.strip("/").split("/")[1])
                    existing_district_id = self._get_existing_school_payload_district(school_id)
                    if existing_district_id is not None:
                        school_payload["district_id"] = existing_district_id
                    else:
                        school_payload = self._ensure_school_payload_has_district(school_payload)
                response = self._wrapped_client.put(
                    url,
                    *args,
                    json=school_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )
                return self._remember_school_district(response)

            if url.startswith("/routes/") and isinstance(payload, dict) and "driver_id" in payload:
                route_payload = self._ensure_route_payload_has_district(payload)
                driver_id = route_payload.pop("driver_id")
                route_id = int(url.strip("/").split("/")[1])
                district_id = route_payload.pop("district_id")
                response = self._wrapped_client.put(
                    f"/districts/{district_id}/routes/{route_id}",
                    *args,
                    json=route_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

                if response.status_code == 200:
                    route_id = response.json().get("id")
                    if route_id is not None:
                        self._wrapped_client.post(f"/routes/{route_id}/assign_driver/{driver_id}")

                return response

            if len(path_parts) == 2 and path_parts[0] == "routes" and isinstance(payload, dict):
                route_payload = self._ensure_route_payload_has_district(payload)
                district_id = route_payload.pop("district_id")
                return self._wrapped_client.put(
                    f"/districts/{district_id}/routes/{path_parts[1]}",
                    *args,
                    json=route_payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if len(path_parts) == 2 and path_parts[0] == "runs" and isinstance(payload, dict):
                run_context = self._get_run_context(int(path_parts[1]))
                if run_context is None:
                    return self._wrapped_client.put(url, *args, **kwargs)
                return self._wrapped_client.put(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{path_parts[1]}",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len(path_parts) == 4
                and path_parts[0] == "routes"
                and path_parts[2] == "stops"
                and isinstance(payload, dict)
            ):
                route_id = int(path_parts[1])
                district_id = self._get_route_district_id(route_id)
                if district_id is None:
                    return self._wrapped_client.put(url, *args, **kwargs)
                return self._wrapped_client.put(
                    f"/districts/{district_id}/routes/{route_id}/stops/{path_parts[3]}",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len(path_parts) == 4
                and path_parts[0] == "routes"
                and path_parts[2] == "runs"
                and isinstance(payload, dict)
            ):
                route_id = int(path_parts[1])
                district_id = self._get_route_district_id(route_id)
                if district_id is None:
                    return self._wrapped_client.put(url, *args, **kwargs)
                return self._wrapped_client.put(
                    f"/districts/{district_id}/routes/{route_id}/runs/{path_parts[3]}",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len(path_parts) == 4
                and path_parts[0] == "runs"
                and path_parts[2] == "stops"
                and isinstance(payload, dict)
            ):
                run_context = self._get_run_context(int(path_parts[1]))
                if run_context is None:
                    return self._wrapped_client.put(url, *args, **kwargs)
                return self._wrapped_client.put(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/stops/{path_parts[3]}",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            if (
                len(path_parts) == 6
                and path_parts[0] == "runs"
                and path_parts[2] == "stops"
                and path_parts[4] == "students"
                and isinstance(payload, dict)
            ):
                run_context = self._get_run_context(int(path_parts[1]))
                if run_context is None:
                    return self._wrapped_client.put(url, *args, **kwargs)
                return self._wrapped_client.put(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{path_parts[1]}/stops/{path_parts[3]}/students/{path_parts[5]}",
                    *args,
                    json=payload,
                    **{k: v for k, v in kwargs.items() if k != "json"},
                )

            return self._wrapped_client.put(url, *args, **kwargs)

        def delete(self, url, *args, **kwargs):
            path_parts = [part for part in url.strip("/").split("/") if part]

            if url.startswith("/schools/") and "/unassign_route/" in url:
                school_id = int(path_parts[1])
                route_id = int(path_parts[3])
                route_snapshot = self._get_route_planning_snapshot(route_id)
                assert route_snapshot is not None
                school_ids = [existing_id for existing_id in route_snapshot["school_ids"] if existing_id != school_id]
                return self._wrapped_client.put(
                    f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
                    *args,
                    json={
                        "route_number": route_snapshot["route_number"],
                        "school_ids": school_ids,
                    },
                    **kwargs,
                )

            if len(path_parts) == 2 and path_parts[0] == "routes":
                district_id = self._get_route_district_id(int(path_parts[1]))
                assert district_id is not None
                return self._wrapped_client.delete(
                    f"/districts/{district_id}/routes/{path_parts[1]}",
                    *args,
                    **kwargs,
                )

            if len(path_parts) == 4 and path_parts[0] == "routes" and path_parts[2] == "runs":
                district_id = self._get_route_district_id(int(path_parts[1]))
                if district_id is None:
                    return self._wrapped_client.delete(url, *args, **kwargs)
                return self._wrapped_client.delete(
                    f"/districts/{district_id}/routes/{path_parts[1]}/runs/{path_parts[3]}",
                    *args,
                    **kwargs,
                )

            if len(path_parts) == 4 and path_parts[0] == "routes" and path_parts[2] == "stops":
                stop_context = self._get_stop_context(int(path_parts[3]))
                assert stop_context is not None
                return self._wrapped_client.delete(
                    f"/districts/{stop_context['district_id']}/routes/{path_parts[1]}/stops/{path_parts[3]}",
                    *args,
                    **kwargs,
                )

            if len(path_parts) == 4 and path_parts[0] == "routes" and path_parts[2] == "students":
                route_snapshot = self._get_route_planning_snapshot(int(path_parts[1]))
                assert route_snapshot is not None
                return self._wrapped_client.delete(
                    f"/districts/{route_snapshot['district_id']}/routes/{path_parts[1]}/students/{path_parts[3]}",
                    *args,
                    **kwargs,
                )

            if len(path_parts) == 2 and path_parts[0] == "runs":
                run_context = self._get_run_context(int(path_parts[1]))
                if run_context is None:
                    return self._wrapped_client.delete(url, *args, **kwargs)
                return self._wrapped_client.delete(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{path_parts[1]}",
                    *args,
                    **kwargs,
                )

            if len(path_parts) == 6 and path_parts[0] == "runs" and path_parts[2] == "stops" and path_parts[4] == "students":
                run_context = self._get_run_context(int(path_parts[1]))
                if run_context is None:
                    return self._wrapped_client.delete(url, *args, **kwargs)
                return self._wrapped_client.delete(
                    f"/districts/{run_context['district_id']}/routes/{run_context['route_id']}/runs/{path_parts[1]}/stops/{path_parts[3]}/students/{path_parts[5]}",
                    *args,
                    **kwargs,
                )

            return self._wrapped_client.delete(url, *args, **kwargs)

    with TestClient(app) as c:
        legacy = LegacyAwareClient(c)

        # Bootstrap: create default operator + driver directly in DB, then set the
        # transitional operator session required by get_operator_context().
        # get_operator_context now requires a valid session (no unauthenticated fallback),
        # so every test must start with an authenticated session.
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
