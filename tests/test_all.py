# ============================================================
# End-to-end API tests for BusTrack backend behavior
# ============================================================

# -----------------------------
# Imports
# -----------------------------

# -----------------------------
# Router / Model / Schema
# -----------------------------

# -----------------------------
# Logic
import pytest                                                      # Pytest framework
from datetime import datetime, timezone                            # Time utilities
from sqlalchemy.orm import Session, sessionmaker                   # DB session tools
from backend.models.associations import StudentRunAssignment       # Runtime assignment model
from backend.models import run as run_model                        # Direct run verification model
from backend.models.route import Route                             # Direct route verification model
from backend.models.student import Student                         # Direct student verification model
from database import engine                                        # DB engine
import uuid

from tests.conftest import client, ensure_prepared_run_student
# =============================================================================
# Project Models (used directly in tests)
# =============================================================================


# -----------------------------------------------------------
# Route-driver test helpers
# - Keep migration setup consistent across tests
# -----------------------------------------------------------
def _create_route_with_assignment_flow(
    client,
    route_number: str,
    unit_number: str,
    driver_id: int | None = None,
    school_ids: list[int] | None = None,
):
    route_response = client.post(
        "/routes/",
        json={
            "route_number": route_number,
            "school_ids": school_ids or [],
        },
    )
    assert route_response.status_code in (200, 201)
    route = route_response.json()

    if driver_id is not None:
        assignment_response = client.post(
            f"/routes/{route['id']}/assign_driver/{driver_id}",
        )
        assert assignment_response.status_code in (200, 201)

    return route


def _create_planned_run(client, route_id: int, run_type: str):
    run_response = client.post(f"/routes/{route_id}/runs", json={"run_type": run_type})
    assert run_response.status_code in (200, 201)
    return run_response


def _start_run_by_id(client, run_id: int):
    ensure_prepared_run_student(client, run_id)
    start_response = client.post(f"/runs/start?run_id={run_id}")
    assert start_response.status_code in (200, 201)
    return start_response


def _create_started_run_context(client, *, route_number: str, unit_number: str, run_type: str):
    school = client.post(
        "/schools/",
        json={"name": f"{route_number} School", "address": f"{route_number} Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post(
        "/drivers/",
        json={"name": f"{route_number} Driver", "email": f"{route_number.lower()}@test.com", "phone": "5550001"},
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        route_number,
        unit_number,
        driver_id=driver.json()["id"],
        school_ids=[school_id],
    )

    run = _create_planned_run(client, route["id"], run_type)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"name": f"{route_number} Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": f"{route_number} Student", "grade": "4", "school_id": school_id},
    )
    assert student.status_code in (200, 201)

    started_run = _start_run_by_id(client, run_id)
    return {
        "run_id": started_run.json()["id"],
        "stop_id": stop_id,
        "student_id": student.json()["id"],
        "school_id": school_id,
    }

def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "SBT backend is running"


def test_driver_crud(client):
    payload = {"name": "John Doe", "email": "john@example.com", "phone": "12345"}
    r = client.post("/drivers/", json=payload)
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    r = client.get("/drivers/")
    assert r.status_code == 200
    assert any(d["name"] == "John Doe" for d in r.json())

    r = client.get(f"/drivers/{driver_id}")
    assert r.status_code == 200

    r = client.put(f"/drivers/{driver_id}", json={"name": "Jane Doe"})
    assert r.status_code == 200

    r = client.delete(f"/drivers/{driver_id}")
    assert r.status_code in (200, 204)

    r = client.get(f"/drivers/{driver_id}")
    assert r.status_code == 404


def test_login_logout(client):
    client.post("/drivers/", json={"name": "Login Test", "email": "login@test.com", "phone": "999"})

    r = client.post("/login", json={"driver_id": 1})
    assert r.status_code == 200

    r = client.get("/driver_run/1")
    assert r.status_code == 200

    r = client.post("/logout")
    assert r.status_code == 200

    r = client.get("/driver_run/1")
    assert r.status_code == 401


def test_driver_run_workspace_shows_route_run_stop_student_hierarchy(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Workspace Driver", "email": "workspace.driver@test.com", "phone": "11122"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    school = client.post(
        "/schools/",
        json={"name": "Workspace School", "address": "123 Workspace Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = _create_route_with_assignment_flow(
        client,
        "WORKSPACE-1",
        "BUS-WORKSPACE-1",
        driver_id=driver_id,
        school_ids=[school_id],
    )
    route_id = route["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={
            "name": "Workspace Stop",
            "address": "456 Stop St",
            "latitude": 40.0,
            "longitude": -105.0,
            "type": "pickup",
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={
            "name": "Workspace Student",
            "grade": "5",
            "school_id": school_id,
        },
    )
    assert student.status_code in (200, 201)

    login = client.post("/login", json={"driver_id": driver_id})
    assert login.status_code == 200

    response = client.get(f"/driver_run/{driver_id}?route_id={route_id}")
    assert response.status_code == 200

    body = response.text

    assert "WORKSPACE-1" in body
    assert "Workspace School" in body
    assert "Create Run" not in body
    assert "Update" not in body
    assert "Delete" not in body
    assert "Start Run" in body
    assert "End Active Run" not in body
    assert "MORNING" in body
    assert "Workspace Stop" in body
    assert "Workspace Student" in body


def test_driver_run_workspace_uses_assigned_bus_values_without_route_fallback(client, db_engine):
    driver = client.post(
        "/drivers/",
        json={"name": "Workspace Bus Driver", "email": "workspace.bus.driver@test.com", "phone": "11123"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    school = client.post(
        "/schools/",
        json={"name": "Workspace Bus School", "address": "124 Workspace Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = _create_route_with_assignment_flow(
        client,
        "WORKSPACE-BUS-1",
        "LEGACY-WORKSPACE-BUS-1",
        driver_id=driver_id,
        school_ids=[school_id],
    )
    route_id = route["id"]

    bus = client.post(
        "/buses/",
        json={
            "unit_number": "BUS-WORKSPACE-REAL",
            "license_plate": "WS-PLATE-1",
            "capacity": 53,
            "size": "full",
        },
    )
    assert bus.status_code in (200, 201)

    assigned = client.post(f"/routes/{route_id}/assign_bus/{bus.json()['id']}")
    assert assigned.status_code == 200

    login = client.post("/login", json={"driver_id": driver_id})
    assert login.status_code == 200

    assigned_response = client.get(f"/driver_run/{driver_id}?route_id={route_id}")
    assert assigned_response.status_code == 200
    assigned_body = assigned_response.text

    assert "BUS-WORKSPACE-REAL" in assigned_body
    assert "full" in assigned_body
    assert "WS-PLATE-1" in assigned_body
    assert "Legacy Operator" not in assigned_body
    assert "Operator" not in assigned_body
    assert "Bus Capacity" not in assigned_body

    unassigned = client.delete(f"/routes/{route_id}/unassign_bus")
    assert unassigned.status_code == 200

    fallback_response = client.get(f"/driver_run/{driver_id}?route_id={route_id}")
    assert fallback_response.status_code == 200
    fallback_body = fallback_response.text

    assert "LEGACY-WORKSPACE-BUS-1" not in fallback_body
    assert "Legacy Operator" not in fallback_body
    assert "Bus Capacity" not in fallback_body
    assert '<div class="route-info-label">Bus</div>' in fallback_body
    assert '<div class="route-info-value">-</div>' in fallback_body


def test_route_report_uses_assigned_bus_values_without_route_fallback(client, db_engine):
    driver = client.post(
        "/drivers/",
        json={"name": "Report Bus Driver", "email": "report.bus.driver@test.com", "phone": "11124"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    school = client.post(
        "/schools/",
        json={"name": "Report Bus School", "address": "125 Report Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = _create_route_with_assignment_flow(
        client,
        "REPORT-BUS-1",
        "LEGACY-REPORT-BUS-1",
        driver_id=driver_id,
        school_ids=[school_id],
    )
    route_id = route["id"]

    run = _create_planned_run(client, route_id, "AM")

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"name": "Report Stop", "latitude": 1, "longitude": 1, "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{run.json()['id']}/stops/{stop.json()['id']}/students",
        json={"name": "Report Student", "school_id": school_id},
    )
    assert student.status_code in (200, 201)

    run = _start_run_by_id(client, run.json()["id"])

    bus = client.post(
        "/buses/",
        json={
            "unit_number": "BUS-REPORT-REAL",
            "license_plate": "RP-PLATE-1",
            "capacity": 47,
            "size": "mid",
        },
    )
    assert bus.status_code in (200, 201)

    assigned = client.post(f"/routes/{route_id}/assign_bus/{bus.json()['id']}")
    assert assigned.status_code == 200

    assigned_response = client.get(f"/route_report/{route_id}")
    assert assigned_response.status_code == 200
    assigned_body = assigned_response.text

    assert "Route Attendance: REPORT-BUS-1" in assigned_body
    assert "BUS-REPORT-REAL" in assigned_body
    assert "mid" in assigned_body
    assert "RP-PLATE-1" in assigned_body
    assert "Bus Capacity:" not in assigned_body

    unassigned = client.delete(f"/routes/{route_id}/unassign_bus")
    assert unassigned.status_code == 200

    fallback_response = client.get(f"/route_report/{route_id}")
    assert fallback_response.status_code == 200
    fallback_body = fallback_response.text

    assert "Route Attendance: REPORT-BUS-1" in fallback_body
    assert "Bus:</strong> -" in fallback_body
    assert "Bus Capacity:" not in fallback_body
    assert "Legacy Report Operator" not in fallback_body


def test_websocket_gps(client):
    client.post("/drivers/", json={"name": "D", "email": "d@d.com", "phone": "000"})
    client.post("/login", json={"driver_id": 1})

    route = _create_route_with_assignment_flow(client, "R1", "Test", driver_id=1)
    route_id = route["id"]

    planned_run = _create_planned_run(client, route_id, "AM")
    run_stop = client.post(
        f"/runs/{planned_run.json()['id']}/stops",
        json={"name": "GPS Stop", "latitude": 40.7128, "longitude": -74.0060, "type": "pickup", "sequence": 1},
    )
    assert run_stop.status_code in (200, 201)
    r = _start_run_by_id(client, planned_run.json()["id"])
    run_id = r.json()["id"]

    with client.websocket_connect(f"/ws/gps/{run_id}") as ws:
        ws.send_json({"lat": 40.7128, "lng": -74.0060})
        data = ws.receive_json()
        assert data["run_id"] == run_id
        assert "progress" in data


def test_alerts(client):
    r = client.post("/drivers/", json={"name": "Driver", "email": "d@d.com", "phone": "000"})
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    client.post("/login", json={"driver_id": driver_id})

    route = _create_route_with_assignment_flow(client, "R1", "Bus-01", driver_id=driver_id)
    route_id = route["id"]

    planned_run = _create_planned_run(client, route_id, "AM")
    run_id = planned_run.json()["id"]

    r = client.post("/schools/", json={"name": "Test School", "address": "123 Test St"})
    assert r.status_code in (200, 201)
    school_id = r.json()["id"]

    r = client.post(
        "/stops/",
        json={
            "name": "Park",
            "latitude": 40.7580,
            "longitude": -73.9855,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert r.status_code in (200, 201)
    stop_id = r.json()["id"]

    r = client.post(
        "/students/",
        json={
            "name": "Kid",
            "school_id": school_id,
            "stop_id": stop_id,
        },
    )
    assert r.status_code in (200, 201)

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    with client.websocket_connect(f"/ws/gps/{run_id}") as ws:
        ws.send_json({"lat": 40.7580, "lng": -73.9855})
        data = ws.receive_json()
        assert "progress" in data


# -----------------------------------------------------------
# Route-driver migration flow
# - Verify route assignment workflow and run driver derivation
# -----------------------------------------------------------
def test_route_driver_assignment_flow(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Assigned Driver", "email": "assigned.driver@test.com", "phone": "10001"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    school = client.post(
        "/schools/",
        json={"name": "Assignment School", "address": "100 Assignment Ave"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "ASSIGN-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    assert route.json()["active_driver_id"] is None

    assign = client.post(
        f"/routes/{route_id}/assign_driver/{driver_id}",
    )
    assert assign.status_code in (200, 201)
    assert assign.json()["driver_id"] == driver_id
    assert assign.json()["active"] is True
    assert assign.json()["is_primary"] is True

    route_after_assign = client.get(f"/routes/{route_id}")
    assert route_after_assign.status_code == 200
    assert route_after_assign.json()["active_driver_id"] == driver_id
    assert route_after_assign.json()["active_driver_name"] == "Assigned Driver"
    assert route_after_assign.json()["primary_driver_id"] == driver_id
    assert route_after_assign.json()["primary_driver_name"] == "Assigned Driver"

    route_drivers = client.get(f"/routes/{route_id}/drivers")
    assert route_drivers.status_code == 200
    assert len(route_drivers.json()) == 1
    assert route_drivers.json()[0]["driver_id"] == driver_id
    assert route_drivers.json()[0]["active"] is True
    assert route_drivers.json()[0]["is_primary"] is True

    driver_routes = client.get(f"/drivers/{driver_id}/routes")
    assert driver_routes.status_code == 200
    assert [item["id"] for item in driver_routes.json()] == [route_id]


def test_route_create_allows_missing_unit_number(client):
    school = client.post(
        "/schools/",
        json={"name": "No Unit School", "address": "101 No Unit Ave"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "NO-UNIT-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)

    body = route.json()
    assert body["route_number"] == "NO-UNIT-1"
    assert "unit_number" not in body
    assert body["school_ids"] == [school_id]

    detail = client.get(f"/routes/{body['id']}")
    assert detail.status_code == 200
    assert "unit_number" not in detail.json()


def test_create_run_uses_single_active_route_assignment(client):
    first_driver = client.post(
        "/drivers/",
        json={"name": "First Route Driver", "email": "first.route.driver@test.com", "phone": "10002"},
    )
    second_driver = client.post(
        "/drivers/",
        json={"name": "Second Route Driver", "email": "second.route.driver@test.com", "phone": "10003"},
    )
    assert first_driver.status_code in (200, 201)
    assert second_driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "RUN-PRIMARY"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    first_assign = client.post(f"/routes/{route_id}/assign_driver/{first_driver.json()['id']}")
    second_assign = client.post(f"/routes/{route_id}/assign_driver/{second_driver.json()['id']}")
    assert first_assign.status_code in (200, 201)
    assert second_assign.status_code in (200, 201)

    route_drivers = client.get(f"/routes/{route_id}/drivers")
    assert route_drivers.status_code == 200

    active_assignments = [item for item in route_drivers.json() if item["active"] is True]
    inactive_assignments = [item for item in route_drivers.json() if item["active"] is False]
    primary_assignments = [item for item in route_drivers.json() if item["is_primary"] is True]

    assert len(active_assignments) == 1
    assert active_assignments[0]["driver_id"] == second_driver.json()["id"]
    assert active_assignments[0]["is_primary"] is False
    assert len(inactive_assignments) == 1
    assert inactive_assignments[0]["driver_id"] == first_driver.json()["id"]
    assert inactive_assignments[0]["is_primary"] is True
    assert len(primary_assignments) == 1
    assert primary_assignments[0]["driver_id"] == first_driver.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    assert run.json()["driver_id"] == second_driver.json()["id"]
    assert run.json()["driver_name"] == "Second Route Driver"
    assert run.json()["start_time"] is None

    route_detail = client.get(f"/routes/{route_id}")
    assert route_detail.status_code == 200
    assert route_detail.json()["active_driver_id"] == second_driver.json()["id"]
    assert route_detail.json()["primary_driver_id"] == first_driver.json()["id"]


def test_driver_routes_lists_only_active_route_assignments(client):
    first_driver = client.post(
        "/drivers/",
        json={"name": "History Driver", "email": "history.driver@test.com", "phone": "10002a"},
    )
    second_driver = client.post(
        "/drivers/",
        json={"name": "Current Driver", "email": "current.driver@test.com", "phone": "10003a"},
    )
    assert first_driver.status_code in (200, 201)
    assert second_driver.status_code in (200, 201)

    retained_route = client.post(
        "/routes/",
        json={"route_number": "ACTIVE-KEEP"},
    )
    replaced_route = client.post(
        "/routes/",
        json={"route_number": "ACTIVE-REPLACE"},
    )
    assert retained_route.status_code in (200, 201)
    assert replaced_route.status_code in (200, 201)

    retained_route_id = retained_route.json()["id"]
    replaced_route_id = replaced_route.json()["id"]

    keep_assign = client.post(f"/routes/{retained_route_id}/assign_driver/{first_driver.json()['id']}")
    first_assign = client.post(f"/routes/{replaced_route_id}/assign_driver/{first_driver.json()['id']}")
    second_assign = client.post(f"/routes/{replaced_route_id}/assign_driver/{second_driver.json()['id']}")
    assert keep_assign.status_code in (200, 201)
    assert first_assign.status_code in (200, 201)
    assert second_assign.status_code in (200, 201)

    first_driver_routes = client.get(f"/drivers/{first_driver.json()['id']}/routes")
    second_driver_routes = client.get(f"/drivers/{second_driver.json()['id']}/routes")
    assert first_driver_routes.status_code == 200
    assert second_driver_routes.status_code == 200

    assert [item["id"] for item in first_driver_routes.json()] == [retained_route_id]
    assert [item["id"] for item in second_driver_routes.json()] == [replaced_route_id]


def test_unassign_active_replacement_reactivates_primary_driver(client):
    primary_driver = client.post(
        "/drivers/",
        json={"name": "Primary Restore Driver", "email": "primary.restore@test.com", "phone": "10003b"},
    )
    replacement_driver = client.post(
        "/drivers/",
        json={"name": "Replacement Restore Driver", "email": "replacement.restore@test.com", "phone": "10003c"},
    )
    assert primary_driver.status_code in (200, 201)
    assert replacement_driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "RESTORE-PRIMARY"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    first_assign = client.post(f"/routes/{route_id}/assign_driver/{primary_driver.json()['id']}")
    second_assign = client.post(f"/routes/{route_id}/assign_driver/{replacement_driver.json()['id']}")
    assert first_assign.status_code in (200, 201)
    assert second_assign.status_code in (200, 201)

    unassign = client.delete(f"/routes/{route_id}/unassign_driver/{replacement_driver.json()['id']}")
    assert unassign.status_code == 204

    route_drivers = client.get(f"/routes/{route_id}/drivers")
    assert route_drivers.status_code == 200

    active_assignments = [item for item in route_drivers.json() if item["active"] is True]
    primary_assignments = [item for item in route_drivers.json() if item["is_primary"] is True]

    assert len(active_assignments) == 1
    assert active_assignments[0]["driver_id"] == primary_driver.json()["id"]
    assert active_assignments[0]["is_primary"] is True
    assert len(primary_assignments) == 1
    assert primary_assignments[0]["driver_id"] == primary_driver.json()["id"]


def test_reassigning_primary_driver_back_into_service_reuses_existing_primary_assignment(client):
    primary_driver = client.post(
        "/drivers/",
        json={"name": "Primary Reuse Driver", "email": "primary.reuse@test.com", "phone": "10003d"},
    )
    replacement_driver = client.post(
        "/drivers/",
        json={"name": "Replacement Reuse Driver", "email": "replacement.reuse@test.com", "phone": "10003e"},
    )
    assert primary_driver.status_code in (200, 201)
    assert replacement_driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "REUSE-PRIMARY"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    first_assign = client.post(f"/routes/{route_id}/assign_driver/{primary_driver.json()['id']}")
    second_assign = client.post(f"/routes/{route_id}/assign_driver/{replacement_driver.json()['id']}")
    restored_assign = client.post(f"/routes/{route_id}/assign_driver/{primary_driver.json()['id']}")
    assert first_assign.status_code in (200, 201)
    assert second_assign.status_code in (200, 201)
    assert restored_assign.status_code in (200, 201)

    assert restored_assign.json()["id"] == first_assign.json()["id"]
    assert restored_assign.json()["driver_id"] == primary_driver.json()["id"]
    assert restored_assign.json()["active"] is True
    assert restored_assign.json()["is_primary"] is True

    route_drivers = client.get(f"/routes/{route_id}/drivers")
    assert route_drivers.status_code == 200
    assert len(route_drivers.json()) == 2

    active_assignments = [item for item in route_drivers.json() if item["active"] is True]
    inactive_assignments = [item for item in route_drivers.json() if item["active"] is False]

    assert len(active_assignments) == 1
    assert active_assignments[0]["id"] == first_assign.json()["id"]
    assert active_assignments[0]["driver_id"] == primary_driver.json()["id"]
    assert len(inactive_assignments) == 1
    assert inactive_assignments[0]["driver_id"] == replacement_driver.json()["id"]


def test_assign_driver_fails_safely_when_route_has_multiple_primary_assignments(client, db_engine):
    driver_one = client.post(
        "/drivers/",
        json={"name": "Primary Conflict One", "email": "primary.conflict.one@test.com", "phone": "10003f"},
    )
    driver_two = client.post(
        "/drivers/",
        json={"name": "Primary Conflict Two", "email": "primary.conflict.two@test.com", "phone": "10003g"},
    )
    driver_three = client.post(
        "/drivers/",
        json={"name": "Primary Conflict Three", "email": "primary.conflict.three@test.com", "phone": "10003h"},
    )
    assert driver_one.status_code in (200, 201)
    assert driver_two.status_code in (200, 201)
    assert driver_three.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "PRIMARY-CONFLICT"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        from backend.models.associations import RouteDriverAssignment

        db.add(
            RouteDriverAssignment(
                route_id=route_id,
                driver_id=driver_one.json()["id"],
                active=False,
                is_primary=True,
            )
        )
        db.add(
            RouteDriverAssignment(
                route_id=route_id,
                driver_id=driver_two.json()["id"],
                active=True,
                is_primary=True,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(f"/routes/{route_id}/assign_driver/{driver_three.json()['id']}")
    assert response.status_code == 409
    assert response.json()["detail"] == "Route has multiple primary driver assignments"


def test_create_run_allows_planned_run_without_active_route_driver_assignment(client):
    route = client.post(
        "/routes/",
        json={"route_number": "NO-DRIVER"},
    )
    assert route.status_code in (200, 201)

    run = client.post(f"/routes/{route.json()['id']}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    assert run.json()["route_id"] == route.json()["id"]
    assert run.json()["run_type"] == "AM"
    assert run.json()["driver_id"] is None
    assert run.json()["driver_name"] is None
    assert run.json()["start_time"] is None
    assert run.json()["end_time"] is None


def test_create_run_allows_multiple_planned_runs_for_same_driver(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Planned Driver", "email": "planned.driver@test.com", "phone": "10007"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "PLAN-ROUTE"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    first_run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    second_run = client.post(f"/routes/{route_id}/runs", json={"run_type": "PM"})

    assert first_run.status_code in (200, 201)
    assert second_run.status_code in (200, 201)
    assert first_run.json()["driver_id"] == driver.json()["id"]
    assert second_run.json()["driver_id"] == driver.json()["id"]
    assert first_run.json()["start_time"] is None
    assert second_run.json()["start_time"] is None


def test_start_run_blocks_second_active_run_for_same_driver(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Active Driver", "email": "active.driver@test.com", "phone": "10008"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "ACTIVE-ROUTE"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    first_run = _create_planned_run(client, route_id, "AM")
    first_stop = client.post(
        f"/runs/{first_run.json()['id']}/stops",
        json={"name": "First Active Stop", "type": "pickup", "sequence": 1},
    )
    assert first_stop.status_code in (200, 201)
    first_start = _start_run_by_id(client, first_run.json()["id"])

    second_run = _create_planned_run(client, route_id, "PM")
    second_stop = client.post(
        f"/runs/{second_run.json()['id']}/stops",
        json={"name": "Second Active Stop", "type": "pickup", "sequence": 1},
    )
    assert second_stop.status_code in (200, 201)
    ensure_prepared_run_student(client, second_run.json()["id"])
    second_start = client.post(f"/runs/start?run_id={second_run.json()['id']}")

    assert first_start.status_code in (200, 201)
    assert first_start.json()["start_time"] is not None
    assert second_start.status_code == 409
    assert second_start.json()["detail"] == "Driver already has an active run"


def test_create_run_accepts_custom_run_type_string(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Custom Label Driver", "email": "custom.label.driver@test.com", "phone": "10009"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "CUSTOM-LABEL"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "School A First Trip"})
    assert run.status_code in (200, 201)
    assert run.json()["run_type"] == "SCHOOL A FIRST TRIP"


def test_start_run_starts_existing_planned_run_by_id(client):
    route = client.post(
        "/routes/",
        json={"route_number": "START-EXISTING"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    planned_run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
    assert planned_run.status_code in (200, 201)
    planned_run_id = planned_run.json()["id"]
    assert planned_run.json()["driver_id"] is None
    assert planned_run.json()["start_time"] is None

    driver = client.post(
        "/drivers/",
        json={"name": "Start Existing Driver", "email": "start.existing.driver@test.com", "phone": "10010"},
    )
    assert driver.status_code in (200, 201)

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    stop = client.post(
        f"/runs/{planned_run_id}/stops",
        json={"name": "Start Existing Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    ensure_prepared_run_student(client, planned_run_id)

    started_run = client.post(f"/runs/start?run_id={planned_run_id}")

    assert started_run.status_code in (200, 201)
    assert started_run.json()["id"] == planned_run_id
    assert started_run.json()["run_type"] == "MORNING"
    assert started_run.json()["driver_id"] == driver.json()["id"]
    assert started_run.json()["start_time"] is not None

    runs_for_route = client.get(f"/runs/?route_id={route_id}")
    assert runs_for_route.status_code == 200
    assert [run["run_id"] for run in runs_for_route.json()] == [planned_run_id]


def test_update_planned_run_succeeds(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Editable Planned Driver", "email": "editable.planned.driver@test.com", "phone": "10011"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "EDIT-PLAN"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Wrong Label"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]
    assert run.json()["start_time"] is None

    update = client.put(f"/runs/{run_id}", json={"run_type": "Corrected Label"})

    assert update.status_code == 200
    assert update.json()["id"] == run_id
    assert update.json()["run_type"] == "CORRECTED LABEL"
    assert update.json()["start_time"] is None


def test_delete_planned_run_succeeds(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Delete Planned Driver", "email": "delete.planned.driver@test.com", "phone": "10012"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "DELETE-PLAN"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Delete Me"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]
    assert run.json()["start_time"] is None

    delete = client.delete(f"/runs/{run_id}")

    assert delete.status_code == 204

    get_deleted = client.get(f"/runs/{run_id}")
    assert get_deleted.status_code == 404


def test_update_started_run_fails(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Locked Started Driver", "email": "locked.started.driver@test.com", "phone": "10013"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "LOCK-UPDATE"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = _create_planned_run(client, route_id, "Started Label")
    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"name": "Started Update Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    run = _start_run_by_id(client, run.json()["id"])
    run_id = run.json()["id"]
    assert run.json()["start_time"] is not None

    update = client.put(f"/runs/{run_id}", json={"run_type": "Should Not Change"})

    assert update.status_code == 400
    assert update.json()["detail"] == "Only planned runs can be updated"


def test_delete_started_run_fails(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Locked Delete Driver", "email": "locked.delete.driver@test.com", "phone": "10014"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "LOCK-DELETE"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = _create_planned_run(client, route_id, "Started Label")
    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"name": "Started Delete Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    run = _start_run_by_id(client, run.json()["id"])
    run_id = run.json()["id"]
    assert run.json()["start_time"] is not None

    delete = client.delete(f"/runs/{run_id}")

    assert delete.status_code == 400
    assert delete.json()["detail"] == "Only planned runs can be deleted"


def test_start_run_accepts_legacy_enum_value_as_plain_string(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Legacy Label Driver", "email": "legacy.label.driver@test.com", "phone": "10010"},
    )
    assert driver.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={"route_number": "LEGACY-LABEL"},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    planned_run = _create_planned_run(client, route_id, "AM")
    stop = client.post(
        f"/runs/{planned_run.json()['id']}/stops",
        json={"name": "Legacy Start Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    run = _start_run_by_id(client, planned_run.json()["id"])
    assert run.status_code in (200, 201)
    assert run.json()["run_type"] == "AM"


def test_create_run_fails_when_route_has_multiple_active_assignments(client, db_engine):
    driver_one = client.post(
        "/drivers/",
        json={"name": "Multi Driver One", "email": "multi.driver.one@test.com", "phone": "10004"},
    )
    driver_two = client.post(
        "/drivers/",
        json={"name": "Multi Driver Two", "email": "multi.driver.two@test.com", "phone": "10005"},
    )
    assert driver_one.status_code in (200, 201)
    assert driver_two.status_code in (200, 201)

    school = client.post(
        "/schools/",
        json={"name": "Multi Driver School", "address": "100 Multi Driver Way"},
    )
    assert school.status_code in (200, 201)

    route = client.post(
        "/routes/",
        json={
            "route_number": "MULTI-ROUTE",
            "school_ids": [school.json()["id"]],
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    client.post(f"/routes/{route_id}/assign_driver/{driver_one.json()['id']}")

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"name": "Multi Driver Start Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{run.json()['id']}/stops/{stop.json()['id']}/students",
        json={"name": "Multi Driver Start Student", "school_id": school.json()["id"]},
    )
    assert student.status_code in (200, 201)

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    try:
        from backend.models.associations import RouteDriverAssignment

        db.add(
            RouteDriverAssignment(
                route_id=route_id,
                driver_id=driver_two.json()["id"],
                active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    run = client.post(f"/runs/start?run_id={run.json()['id']}")
    assert run.status_code == 409
    assert run.json()["detail"] == "Route has multiple active driver assignments"


def test_unassign_driver_blocks_future_run_start(client):
    driver = client.post(
        "/drivers/",
        json={"name": "Unassign Driver", "email": "unassign.driver@test.com", "phone": "10006"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route = _create_route_with_assignment_flow(client, "UNASSIGN-1", "BUS-UNASSIGN-1", driver_id=driver_id)
    route_id = route["id"]

    unassign = client.delete(f"/routes/{route_id}/unassign_driver/{driver_id}")
    assert unassign.status_code == 204

    run = client.post("/runs/", json={"route_id": route_id, "run_type": "AM"})
    assert run.status_code in (200, 201)
    assert run.json()["start_time"] is None
    assert run.json()["driver_id"] is None

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"name": "Future Start Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)

    started = client.post(f"/runs/start?run_id={run.json()['id']}")
    assert started.status_code == 409
    assert started.json()["detail"] == "Route has no active driver assignment"


def test_start_run_fails_without_active_route_driver_assignment(client):
    route = client.post(
        "/routes/",
        json={"route_number": "START-NO-DRIVER"},
    )
    assert route.status_code in (200, 201)

    run = client.post(f"/routes/{route.json()['id']}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)

    school = client.post(
        "/schools/",
        json={"name": "Start No Driver School", "address": "1 No Driver Way"},
    )
    assert school.status_code in (200, 201)

    route_update = client.put(
        f"/routes/{route.json()['id']}",
        json={
            "route_number": "START-NO-DRIVER",
            "school_ids": [school.json()["id"]],
        },
    )
    assert route_update.status_code == 200

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"name": "No Driver Start Stop", "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{run.json()['id']}/stops/{stop.json()['id']}/students",
        json={"name": "No Driver Start Student", "school_id": school.json()["id"]},
    )
    assert student.status_code in (200, 201)

    run = client.post(f"/runs/start?run_id={run.json()['id']}")
    assert run.status_code == 409
    assert run.json()["detail"] == "Route has no active driver assignment"


def test_run_context_stop_create_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-STOP-CREATE",
        unit_number="BUS-LOCK-STOP-CREATE",
        run_type="AM",
    )

    response = client.post(
        f"/runs/{context['run_id']}/stops",
        json={"name": "Blocked Stop", "type": "pickup", "sequence": 2},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_run_context_stop_update_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-STOP-UPDATE",
        unit_number="BUS-LOCK-STOP-UPDATE",
        run_type="AM",
    )

    response = client.put(
        f"/runs/{context['run_id']}/stops/{context['stop_id']}",
        json={"name": "Blocked Stop Update"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_legacy_stop_create_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-LEGACY-STOP-CREATE",
        unit_number="BUS-LOCK-LEGACY-STOP-CREATE",
        run_type="AM",
    )

    response = client.post(
        "/stops/",
        json={"run_id": context["run_id"], "name": "Blocked Legacy Stop", "type": "pickup", "sequence": 2},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_legacy_stop_update_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-LEGACY-STOP-UPDATE",
        unit_number="BUS-LOCK-LEGACY-STOP-UPDATE",
        run_type="AM",
    )

    response = client.put(
        f"/stops/{context['stop_id']}",
        json={"name": "Blocked Legacy Stop Update"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_run_context_student_create_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-STUDENT-CREATE",
        unit_number="BUS-LOCK-STUDENT-CREATE",
        run_type="AM",
    )

    response = client.post(
        f"/runs/{context['run_id']}/stops/{context['stop_id']}/students",
        json={"name": "Blocked Student", "grade": "5", "school_id": context["school_id"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_legacy_student_create_is_blocked_when_target_stop_run_is_started(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-LEGACY-STUDENT-CREATE",
        unit_number="BUS-LOCK-LEGACY-STUDENT-CREATE",
        run_type="AM",
    )

    response = client.post(
        "/students/",
        json={
            "name": "Blocked Legacy Student",
            "grade": "5",
            "school_id": context["school_id"],
            "stop_id": context["stop_id"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_run_context_student_update_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-STUDENT-UPDATE",
        unit_number="BUS-LOCK-STUDENT-UPDATE",
        run_type="AM",
    )

    response = client.put(
        f"/runs/{context['run_id']}/stops/{context['stop_id']}/students/{context['student_id']}",
        json={"name": "Blocked Student Update"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_run_context_bulk_student_create_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-STUDENT-BULK",
        unit_number="BUS-LOCK-STUDENT-BULK",
        run_type="AM",
    )

    response = client.post(
        f"/runs/{context['run_id']}/stops/{context['stop_id']}/students/bulk",
        json={
            "students": [
                {"name": "Blocked Bulk Student", "grade": "5", "school_id": context["school_id"]},
            ]
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


# =============================================================================
# Pickup Student Tests
# -----------------------------------------------------------------------------
# These tests verify runtime student boarding behavior for active runs.
#
# Coverage:
#   - successful pickup
#   - student not assigned to run
#   - duplicate pickup blocked
# =============================================================================


# =============================================================================
# Test pickup_student success
# -----------------------------------------------------------------------------
# Flow:
#   - create driver / school / route
#   - create run
#   - add stops to run
#   - create student
#   - create runtime assignment
#   - move run to assigned stop
#   - pickup student successfully
# =============================================================================
def test_pickup_student_success(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    driver_id = driver.json()["id"]  # Save driver ID

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    school_id = school.json()["id"]  # Save school ID

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]  # Save run ID

    # -------------------------------------------------------------------------
    # Add run stops
    # -------------------------------------------------------------------------
    stop1 = client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    stop1_id = stop1.json()["id"]  # Save first stop ID

    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    stop2_id = stop2.json()["id"]  # Save second stop ID

    # -------------------------------------------------------------------------
    # Create student assigned to second stop
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop2_id}/students",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
        },
    )
    student_id = student.json()["id"]  # Save student ID

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Move run directly to stop 2 (student's assigned stop)
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive.status_code == 200
    
    # -------------------------------------------------------------------------
    # Pickup student at current stop
    # -------------------------------------------------------------------------
    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )

    assert pickup.status_code == 200
    body = pickup.json()

    assert body["message"] == "Student picked up successfully"
    assert body["run_id"] == run_id
    assert body["student_id"] == student_id
    assert body["picked_up"] is True
    assert body["is_onboard"] is True
    assert body["picked_up_at"] is not None


# =============================================================================
# Test pickup_student fails when student is not assigned to run
# =============================================================================
def test_pickup_student_not_assigned(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]

    # -------------------------------------------------------------------------
    # Add stops to run
    # -------------------------------------------------------------------------
    client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )

    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    stop2_id = stop2.json()["id"]

    # -------------------------------------------------------------------------
    # Create student but do NOT assign to the run
    # -------------------------------------------------------------------------
    student = client.post(
        "/students/",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop2_id,
        },
    )
    student_id = student.json()["id"]

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Move run to stop 2
    # -------------------------------------------------------------------------
    client.post(f"/runs/{run_id}/arrive_stop")
    client.post(f"/runs/{run_id}/next_stop")

    # -------------------------------------------------------------------------
    # Attempt pickup without runtime assignment
    # -------------------------------------------------------------------------
    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )

    assert pickup.status_code == 404
    assert pickup.json()["detail"] == "Student is not assigned to this run"


# =============================================================================
# Test pickup_student blocks duplicate pickup
# =============================================================================
def test_pickup_student_already_picked_up(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]

    # -------------------------------------------------------------------------
    # Add stops to run
    # -------------------------------------------------------------------------
    client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )

    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    stop2_id = stop2.json()["id"]

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop2_id}/students",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
        },
    )
    student_id = student.json()["id"]

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Move run to stop 2
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive.status_code == 200

    # -------------------------------------------------------------------------
    # First pickup succeeds
    # -------------------------------------------------------------------------
    first_pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert first_pickup.status_code == 200

    # -------------------------------------------------------------------------
    # Second pickup should fail
    # -------------------------------------------------------------------------
    second_pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )

    assert second_pickup.status_code == 400
    assert second_pickup.json()["detail"] == "Student has already been picked up"

# =============================================================================
# Dropoff Student Tests
# -----------------------------------------------------------------------------
# These tests verify runtime student drop-off behavior for active runs.
#
# Coverage:
#   - successful drop-off
#   - student not currently onboard
#   - duplicate drop-off blocked
# =============================================================================


# =============================================================================
# Test dropoff_student success
# =============================================================================
def test_dropoff_student_success(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]

    # -------------------------------------------------------------------------
    # Add stops
    # -------------------------------------------------------------------------
    client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    
    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    stop2_id = stop2.json()["id"]

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop2_id}/students",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
        },
    )
    student_id = student.json()["id"]

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Move run to stop 2 and pick up student first
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive.status_code == 200

    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert pickup.status_code == 200

    # -------------------------------------------------------------------------
    # Drop off student
    # -------------------------------------------------------------------------
    dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )

    assert dropoff.status_code == 200
    body = dropoff.json()

    assert body["message"] == "Student dropped off successfully"
    assert body["run_id"] == run_id
    assert body["student_id"] == student_id
    assert body["dropped_off"] is True
    assert body["is_onboard"] is False
    assert body["dropped_off_at"] is not None


# =============================================================================
# Test dropoff_student fails when student is not currently onboard
# =============================================================================
def test_dropoff_student_not_onboard(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]

        # -------------------------------------------------------------------------
    # Add stop 1
    # -------------------------------------------------------------------------
    client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )

    # -------------------------------------------------------------------------
    # Add stop 2
    # -------------------------------------------------------------------------
    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    stop2_id = stop2.json()["id"]

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop2_id}/students",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
        },
    )
    student_id = student.json()["id"]

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Move run to stop 2 but do NOT pick up student
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive.status_code == 200

    # -------------------------------------------------------------------------
    # Drop-off should fail because student is not onboard
    # -------------------------------------------------------------------------
    dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )

    assert dropoff.status_code == 400
    assert dropoff.json()["detail"] == "Student has not been picked up yet"


# =============================================================================
# Test dropoff_student blocks duplicate drop-off
# =============================================================================
def test_dropoff_student_already_dropped_off(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]

        # -------------------------------------------------------------------------
    # Add stop 1
    # -------------------------------------------------------------------------
    client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    # -------------------------------------------------------------------------
    # Add stop 2
    # -------------------------------------------------------------------------
    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    stop2_id = stop2.json()["id"]

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop2_id}/students",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
        },
    )
    student_id = student.json()["id"]

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Move run to stop 2, pick up student, then drop off once
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive.status_code == 200

    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert pickup.status_code == 200

    first_dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )
    assert first_dropoff.status_code == 200

    # -------------------------------------------------------------------------
    # Second drop-off should fail
    # -------------------------------------------------------------------------
    second_dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )

    assert second_dropoff.status_code == 400
    assert second_dropoff.json()["detail"] == "Student has already been dropped off"



# =============================================================================
# Test onboard_students returns empty list when nobody is onboard
# =============================================================================
def test_get_onboard_students_empty(client):
   
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run_response = _create_planned_run(client, route_id, "AM")
    assert run_response.status_code in (200, 201)
    run_id = run_response.json()["id"]

    stop = client.post(
        "/stops/",
        json={
            "name": "Onboard Empty Stop",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]


    # -------------------------------------------------------------------------
    # Query onboard students without any pickups
    # -------------------------------------------------------------------------
    response = client.get(f"/runs/{run_id}/onboard_students")

    assert response.status_code == 200
    body = response.json()

    assert body["run_id"] == run_id
    assert body["total_onboard_students"] == 0
    assert body["students"] == []


# =============================================================================
# Test onboard_students returns 404 when run does not exist
# =============================================================================
def test_get_onboard_students_run_not_found(client):
    response = client.get("/runs/999/onboard_students")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"

def test_get_occupancy_summary_success(client, db_engine):
    """
    Verify occupancy summary returns correct counts for a run.
    """

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "driver_id": driver_id,
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run_response = _create_planned_run(client, route_id, "AM")
    assert run_response.status_code in (200, 201)
    run_id = run_response.json()["id"]

    # -------------------------------------------------------------------------
    # Create local DB session from the existing test engine
    # -------------------------------------------------------------------------
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = TestingSessionLocal()
    # -------------------------------------------------------------------------
# Create school
# -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
         json={
            "name": "Test School",
            "address": "123 Test St",
        },
   )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

# -------------------------------------------------------------------------
# Create stop 1
# -------------------------------------------------------------------------
    stop1 = client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop1.status_code in (200, 201)
    stop1_id = stop1.json()["id"]

# -------------------------------------------------------------------------
# Create stop 2
# -------------------------------------------------------------------------
    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    assert stop2.status_code in (200, 201)
    stop2_id = stop2.json()["id"]

# -------------------------------------------------------------------------
# Create student 1
# -------------------------------------------------------------------------
    student1 = client.post(
        "/students/",
        json={
            "name": "Student One",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop1_id,
        },
    )
    assert student1.status_code in (200, 201)
    student1_id = student1.json()["id"]

# -------------------------------------------------------------------------
# Create student 2
# -------------------------------------------------------------------------
    student2 = client.post(
        "/students/",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop2_id,
        },
    )
    assert student2.status_code in (200, 201)
    student2_id = student2.json()["id"]

    try:
        # ---------------------------------------------------------------------
        # Create two runtime student assignments with mixed occupancy state
        # ---------------------------------------------------------------------
        assignment_1 = StudentRunAssignment(
            run_id=run_id,                               # Link to created run
            student_id=student1_id,                      # Actual created student
            stop_id=stop1_id,                            # Actual created stop
            picked_up=True,                              # Student was picked up
            picked_up_at=datetime.now(timezone.utc),     # Pickup timestamp
            dropped_off=False,
            dropped_off_at=None,
            is_onboard=True,
        )

        assignment_2 = StudentRunAssignment(
            run_id=run_id,
            student_id=student2_id,                      # Actual created student
            stop_id=stop2_id,                            # Actual created stop
            picked_up=False,
            picked_up_at=None,
            dropped_off=False,
            dropped_off_at=None,
            is_onboard=False,
        )

        db.add_all([assignment_1, assignment_2])
        db.commit()
    finally:
        db.close()

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Call occupancy summary endpoint
    # -------------------------------------------------------------------------
    response = client.get(f"/runs/{run_id}/occupancy_summary")
    assert response.status_code == 200

    data = response.json()

    assert data["run_id"] == run_id
    assert data["route_id"] == route_id
    assert data["run_type"] == "AM"
    assert data["total_assigned_students"] == 2
    assert data["total_picked_up"] == 1
    assert data["total_dropped_off"] == 0
    assert data["total_currently_onboard"] == 1
    assert data["total_not_yet_boarded"] == 1

def test_get_occupancy_summary_empty_assignments(client):
    """
    Verify summary works when a run has no student assignments.
    """

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver Two",
            "email": "driver2@test.com",
            "phone": "22222",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R2",
            "driver_id": driver_id,
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run_response = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
    assert run_response.status_code in (200, 201)
    run_id = run_response.json()["id"]

    # -------------------------------------------------------------------------
    # Call occupancy summary endpoint
    # -------------------------------------------------------------------------
    response = client.get(f"/runs/{run_id}/occupancy_summary")
    assert response.status_code == 200

    data = response.json()

    assert data["run_id"] == run_id
    assert data["route_id"] == route_id
    assert data["run_type"] == "AM"
    assert data["total_assigned_students"] == 0
    assert data["total_picked_up"] == 0
    assert data["total_dropped_off"] == 0
    assert data["total_currently_onboard"] == 0
    assert data["total_not_yet_boarded"] == 0

def test_get_occupancy_summary_run_not_found(client):
    """
    Verify endpoint returns 404 when run does not exist.
    """

    response = client.get("/runs/9999/occupancy_summary")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_get_run_state_snapshot(client):
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "State Driver",
            "email": "state@driver.com",
            "phone": "55555",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "State School",
            "address": "789 State St",
        },
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "STATE-1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    # -------------------------------------------------------------------------
    # Create stops
    # -------------------------------------------------------------------------
    stop1 = client.post(
        "/stops/",
        json={
            "name": "State Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop1.status_code in (200, 201)
    stop1_id = stop1.json()["id"]

    stop2 = client.post(
        "/stops/",
        json={
            "name": "State Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "dropoff",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    assert stop2.status_code in (200, 201)
    stop2_id = stop2.json()["id"]

    # -------------------------------------------------------------------------
    # Create student and runtime assignment
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop1_id}/students",
        json={
            "name": "State Student",
            "grade": "4",
            "school_id": school_id,
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Read initial state before any actions
    # -------------------------------------------------------------------------
    initial_state = client.get(f"/runs/{run_id}/state")
    assert initial_state.status_code == 200

    initial_data = initial_state.json()
    assert initial_data["run_id"] == run_id
    assert initial_data["route_id"] == route_id
    assert initial_data["driver_id"] == driver_id
    assert initial_data["run_type"] == "AM"
    assert initial_data["current_stop_id"] is None
    assert initial_data["current_stop_sequence"] is None
    assert initial_data["current_stop_name"] is None
    assert initial_data["total_stops"] == 2
    assert initial_data["completed_stops"] == 0
    assert initial_data["remaining_stops"] == 2
    assert initial_data["progress_percent"] == 0.0
    assert initial_data["total_assigned_students"] == 1
    assert initial_data["picked_up_students"] == 0
    assert initial_data["dropped_off_students"] == 0
    assert initial_data["students_onboard"] == 0
    assert initial_data["remaining_pickups"] == 1
    assert initial_data["remaining_dropoffs"] == 0

    # -------------------------------------------------------------------------
    # Arrive at stop 1 and pick up student
    # -------------------------------------------------------------------------
    arrive_stop_1 = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")
    assert arrive_stop_1.status_code == 200

    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert pickup.status_code == 200

    pickup_state = client.get(f"/runs/{run_id}/state")
    assert pickup_state.status_code == 200

    pickup_data = pickup_state.json()
    assert pickup_data["current_stop_id"] == stop1_id
    assert pickup_data["current_stop_sequence"] == 1
    assert pickup_data["current_stop_name"] == "State Stop 1"
    assert pickup_data["completed_stops"] == 1
    assert pickup_data["remaining_stops"] == 1
    assert pickup_data["progress_percent"] == 50.0
    assert pickup_data["total_assigned_students"] == 1
    assert pickup_data["picked_up_students"] == 1
    assert pickup_data["dropped_off_students"] == 0
    assert pickup_data["students_onboard"] == 1
    assert pickup_data["remaining_pickups"] == 0
    assert pickup_data["remaining_dropoffs"] == 1

    # -------------------------------------------------------------------------
    # Arrive at stop 2 and drop off student
    # -------------------------------------------------------------------------
    arrive_stop_2 = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive_stop_2.status_code == 200

    dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )
    assert dropoff.status_code == 200

    dropoff_state = client.get(f"/runs/{run_id}/state")
    assert dropoff_state.status_code == 200

    dropoff_data = dropoff_state.json()
    assert dropoff_data["current_stop_id"] == stop2_id
    assert dropoff_data["current_stop_sequence"] == 2
    assert dropoff_data["current_stop_name"] == "State Stop 2"
    assert dropoff_data["total_stops"] == 2
    assert dropoff_data["completed_stops"] == 2
    assert dropoff_data["remaining_stops"] == 0
    assert dropoff_data["progress_percent"] == 100.0
    assert dropoff_data["total_assigned_students"] == 1
    assert dropoff_data["picked_up_students"] == 1
    assert dropoff_data["dropped_off_students"] == 1
    assert dropoff_data["students_onboard"] == 0
    assert dropoff_data["remaining_pickups"] == 0
    assert dropoff_data["remaining_dropoffs"] == 0


def test_arrive_stop_allows_backward_movement(client):
    driver = client.post("/drivers/", json={"name": "Driver Move", "email": "move@test.com", "phone": "33333"})  # Create driver
    driver_id = driver.json()["id"]  # Extract driver ID from API response
    route = client.post("/routes/", json={"route_number": "R3", "driver_id": driver_id})  # Create route
    route_id = route.json()["id"]  # Extract route ID from API response
    run = _create_planned_run(client, route_id, "AM")  # Create planned run
    run_id = run.json()["id"]  # Extract run ID from API response
    stop1 = client.post("/stops/", json={"name": "Stop 1", "latitude": 53.5461, "longitude": -113.4938, "type": "pickup", "run_id": run_id, "sequence": 1})  # Create first stop
    stop1_id = stop1.json()["id"]  # Extract first stop ID from API response
    stop2 = client.post("/stops/", json={"name": "Stop 2", "latitude": 53.5561, "longitude": -113.4838, "type": "pickup", "run_id": run_id, "sequence": 2})  # Create second stop
    stop2_id = stop2.json()["id"]  # Extract second stop ID from API response

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    forward_arrival = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")  # Move the bus forward to stop 2
    assert forward_arrival.status_code == 200  # Confirm forward arrival succeeded
    assert forward_arrival.json()["current_stop_id"] == stop2_id  # Confirm current stop ID matches stop 2
    assert forward_arrival.json()["current_stop_sequence"] == 2  # Confirm current stop sequence matches stop 2

    backward_arrival = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")  # Move the bus backward to stop 1
    assert backward_arrival.status_code == 200  # Confirm backward arrival succeeded
    assert backward_arrival.json()["current_stop_id"] == stop1_id  # Confirm current stop ID matches stop 1
    assert backward_arrival.json()["current_stop_sequence"] == 1  # Confirm current stop sequence matches stop 1


def test_flexible_pickup_dropoff_records_actual_stops_and_keeps_occupancy_correct(client, db_engine):
    driver = client.post("/drivers/", json={"name": "Driver Flex", "email": "flex@test.com", "phone": "44444"})  # Create driver
    driver_id = driver.json()["id"]  # Extract driver ID from API response
    school = client.post("/schools/", json={"name": "Flex School", "address": "456 Flex Ave"})  # Create school
    school_id = school.json()["id"]  # Extract school ID from API response
    route = client.post("/routes/", json={"route_number": "R4", "driver_id": driver_id, "school_ids": [school_id]})  # Create route
    route_id = route.json()["id"]  # Extract route ID from API response
    run = _create_planned_run(client, route_id, "AM")  # Create planned run
    run_id = run.json()["id"]  # Extract run ID from API response
    stop1 = client.post("/stops/", json={"name": "Corner Pickup", "latitude": 53.5461, "longitude": -113.4938, "type": "pickup", "run_id": run_id, "sequence": 1})  # Create alternate pickup stop
    stop1_id = stop1.json()["id"]  # Extract alternate pickup stop ID
    stop2 = client.post("/stops/", json={"name": "Assigned Pickup", "latitude": 53.5561, "longitude": -113.4838, "type": "pickup", "run_id": run_id, "sequence": 2})  # Create assigned pickup stop
    stop2_id = stop2.json()["id"]  # Extract assigned pickup stop ID
    stop3 = client.post("/stops/", json={"name": "School Dropoff", "latitude": 53.5661, "longitude": -113.4738, "type": "dropoff", "run_id": run_id, "sequence": 3})  # Create alternate dropoff stop
    stop3_id = stop3.json()["id"]  # Extract alternate dropoff stop ID
    student = client.post(f"/runs/{run_id}/stops/{stop2_id}/students", json={"name": "Flexible Rider", "grade": "5", "school_id": school_id})  # Create student assigned to stop 2 through canonical stop context
    student_id = student.json()["id"]  # Extract student ID from API response

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    pickup_arrival = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")  # Move the bus to a different pickup stop
    assert pickup_arrival.status_code == 200  # Confirm alternate pickup arrival succeeded
    pickup = client.post(f"/runs/{run_id}/pickup_student", json={"student_id": student_id})  # Pick the student up at stop 1 instead of stop 2
    assert pickup.status_code == 200  # Confirm flexible pickup succeeded

    dropoff_arrival = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=3")  # Move the bus to a different dropoff stop
    assert dropoff_arrival.status_code == 200  # Confirm alternate dropoff arrival succeeded
    dropoff = client.post(f"/runs/{run_id}/dropoff_student", json={"student_id": student_id})  # Drop the student off at stop 3
    assert dropoff.status_code == 200  # Confirm flexible dropoff succeeded

    summary = client.get(f"/runs/{run_id}/occupancy_summary")  # Read the final occupancy summary
    assert summary.status_code == 200  # Confirm occupancy summary request succeeded
    assert summary.json()["total_assigned_students"] == 1  # Confirm one student was assigned
    assert summary.json()["total_picked_up"] == 1  # Confirm the student was picked up
    assert summary.json()["total_dropped_off"] == 1  # Confirm the student was dropped off
    assert summary.json()["total_currently_onboard"] == 0  # Confirm nobody remains onboard
    assert summary.json()["total_not_yet_boarded"] == 0  # Confirm nobody remains unboarded

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)  # Build a direct DB session for verification
    db = TestingSessionLocal()  # Open a direct DB session for verification
    try:
        stored_assignment = db.query(StudentRunAssignment).filter(StudentRunAssignment.run_id == run_id, StudentRunAssignment.student_id == student_id).first()  # Load the stored assignment row
        assert stored_assignment is not None  # Confirm the assignment row exists
        assert stored_assignment.stop_id == stop2_id  # Confirm the planned assigned stop stayed unchanged
        assert stored_assignment.actual_pickup_stop_id == stop1_id  # Confirm the actual pickup stop was recorded
        assert stored_assignment.actual_dropoff_stop_id == stop3_id  # Confirm the actual dropoff stop was recorded
    finally:
        db.close()  # Close the direct DB session

# ============================================================
# Test Run Timeline
# - verifies ARRIVE, PICKUP, DROPOFF events are recorded
# ============================================================

def test_run_timeline(client):

    # -------------------------------------------------------
    # Create driver
    # -------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Timeline Driver",
            "email": "timeline@driver.com",
            "phone": "1112223333",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]  # Save driver ID

    # -------------------------------------------------------
    # Create school
    # -------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Timeline School",
            "address": "123 Timeline St",
        },
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]  # Save school ID

    # -------------------------------------------------------
    # Create route
    # -------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "TL-1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------
    # Create run
    # -------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]  # Save run ID

    # -------------------------------------------------------
    # Add stops to run
    # -------------------------------------------------------
    stop1 = client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop1.status_code in (200, 201)
    stop1_id = stop1.json()["id"]  # Save first stop ID

    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    assert stop2.status_code in (200, 201)
    stop2_id = stop2.json()["id"]  # Save second stop ID

    # -------------------------------------------------------
    # Create student
    # -------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop1_id}/students",
        json={
            "name": "Timeline Student",
            "grade": "5",
            "school_id": school_id,
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]  # Save student ID

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------
    # ARRIVE stop 1
    # -------------------------------------------------------
    arrive1 = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")
    assert arrive1.status_code == 200

    # -------------------------------------------------------
    # PICKUP student
    # -------------------------------------------------------
    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert pickup.status_code == 200

    # -------------------------------------------------------
    # ARRIVE stop 2
    # -------------------------------------------------------
    arrive2 = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive2.status_code == 200

    # -------------------------------------------------------
    # DROPOFF student
    # -------------------------------------------------------
    dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )
    assert dropoff.status_code == 200

    # -------------------------------------------------------
    # Get timeline
    # -------------------------------------------------------
    timeline = client.get(f"/runs/{run_id}/timeline")
    assert timeline.status_code == 200

    data = timeline.json()

    assert len(data["events"]) == 4
    assert data["events"][0]["event_type"] == "ARRIVE"
    assert data["events"][1]["event_type"] == "PICKUP"
    assert data["events"][2]["event_type"] == "ARRIVE"
    assert data["events"][3]["event_type"] == "DROPOFF"

    # ============================================================
# Test Run Replay
# - verifies replay output includes readable messages and summary
# ============================================================

def test_run_replay(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Replay Driver",
            "email": "replay@driver.com",
            "phone": "2223334444",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]  # Save driver ID

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Replay School",
            "address": "456 Replay Ave",
        },
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]  # Save school ID

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "RP-1",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]  # Save run ID

    # -------------------------------------------------------------------------
    # Add stops to run
    # -------------------------------------------------------------------------
    stop1 = client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop1.status_code in (200, 201)
    stop1_id = stop1.json()["id"]  # Save first stop ID

    stop2 = client.post(
        "/stops/",
        json={
            "name": "Stop 2",
            "latitude": 53.5561,
            "longitude": -113.4838,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 2,
        },
    )
    assert stop2.status_code in (200, 201)
    stop2_id = stop2.json()["id"]  # Save second stop ID

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop1_id}/students",
        json={
            "name": "Replay Student",
            "grade": "6",
            "school_id": school_id,
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]  # Save student ID

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # ARRIVE stop 1
    # -------------------------------------------------------------------------
    arrive1 = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")
    assert arrive1.status_code == 200

    # -------------------------------------------------------------------------
    # PICKUP student
    # -------------------------------------------------------------------------
    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert pickup.status_code == 200

    # -------------------------------------------------------------------------
    # ARRIVE stop 2
    # -------------------------------------------------------------------------
    arrive2 = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive2.status_code == 200

    # -------------------------------------------------------------------------
    # DROPOFF student
    # -------------------------------------------------------------------------
    dropoff = client.post(
        f"/runs/{run_id}/dropoff_student",
        json={"student_id": student_id},
    )
    assert dropoff.status_code == 200

    # -------------------------------------------------------------------------
    # Get replay
    # -------------------------------------------------------------------------
    replay = client.get(f"/runs/{run_id}/replay")
    assert replay.status_code == 200

    data = replay.json()

    # -------------------------------------------------------------------------
    # Validate top-level structure
    # -------------------------------------------------------------------------
    assert data["run_id"] == run_id
    assert data["summary"]["total_events"] == 4
    assert data["summary"]["total_arrivals"] == 2
    assert data["summary"]["total_pickups"] == 1
    assert data["summary"]["total_dropoffs"] == 1

    # -------------------------------------------------------------------------
    # Validate replay event order
    # -------------------------------------------------------------------------
    assert len(data["events"]) == 4
    assert data["events"][0]["event_type"] == "ARRIVE"
    assert data["events"][1]["event_type"] == "PICKUP"
    assert data["events"][2]["event_type"] == "ARRIVE"
    assert data["events"][3]["event_type"] == "DROPOFF"

    # -------------------------------------------------------------------------
    # Validate readable replay messages
    # -------------------------------------------------------------------------
    assert "Bus arrived at Stop 1" == data["events"][0]["message"]
    assert "Replay Student picked up at Stop 1" == data["events"][1]["message"]
    assert "Bus arrived at Stop 2" == data["events"][2]["message"]
    assert "Replay Student dropped off at Stop 2" == data["events"][3]["message"]

    # -------------------------------------------------------------------------
    # Validate onboard counts
    # -------------------------------------------------------------------------
    assert data["events"][0]["onboard_count"] == 0
    assert data["events"][1]["onboard_count"] == 1
    assert data["events"][2]["onboard_count"] == 1
    assert data["events"][3]["onboard_count"] == 0

# ============================================================
# Test Run Completion
# - verifies run can be completed and actions are locked
# ============================================================

def test_run_complete(client):

    # -------------------------------------------------------
    # Create driver
    # -------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Complete Driver",
            "email": "complete@driver.com",
            "phone": "5556667777",
        },
    )
    driver_id = driver.json()["id"]

    # -------------------------------------------------------
    # Create route
    # -------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "COMP-1",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------
    # Create run
    # -------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    run_id = run.json()["id"]

    stop = client.post(
        "/stops/",
        json={
            "name": "Completion Stop",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------
    # Complete run
    # -------------------------------------------------------
    response = client.post(f"/runs/{run_id}/complete")

    assert response.status_code == 200

    data = response.json()

    assert data["is_completed"] is True
    assert data["completed_at"] is not None
    assert data["message"] == "Run completed successfully"

    # -------------------------------------------------------
    # Attempt mutation after completion
    # -------------------------------------------------------
    blocked = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")

    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "Run is already completed"


    # =============================================================================
# Test school attendance report returns data for one school
# =============================================================================
def test_get_school_attendance_report(client):

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Attendance School",
            "address": "123 Attendance St",
        },
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    # -------------------------------------------------------------------------
    # Request school attendance report
    # -------------------------------------------------------------------------
    response = client.get(f"/reports/school/{school_id}")
    assert response.status_code == 200

    body = response.json()

           # -------------------------------------------------------------------------
    # Validate school attendance report shape
    # -------------------------------------------------------------------------
    assert isinstance(body, dict)
    assert body["school_id"] == school_id
    assert body["school_name"] == "Attendance School"
    assert "total_routes" in body
    assert "routes" in body
    assert isinstance(body["routes"], list)

    if body["routes"]:
        first_route = body["routes"][0]                                       # First grouped route
        assert "route_number" in first_route
        assert "total_runs" in first_route
        assert "runs" in first_route
        assert isinstance(first_route["runs"], list)

        if first_route["runs"]:
            first_run = first_route["runs"][0]                                # First grouped run
            assert "run_type" in first_run
            assert "date" in first_run
            assert "students" in first_run
            assert isinstance(first_run["students"], list)

            if first_run["students"]:
                first_student = first_run["students"][0]                      # First school-facing student row
                assert set(first_student.keys()) == {"student_name", "status"}
                assert first_student["status"] in {"present", "absent"}
                assert "student_id" not in first_student                                   # School view must not expose internal IDs


# =============================================================================
# Test school mobile attendance report renders printable school layout
# =============================================================================
def test_get_school_mobile_attendance_report(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "School Report Driver",
            "email": "school.report.driver@test.com",
            "phone": "3035551212",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]  # Save driver ID

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Rendered Attendance School",
            "address": "456 Rendered St",
        },
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]  # Save school ID

    # -------------------------------------------------------------------------
    # Create route assigned to the school
    # -------------------------------------------------------------------------
    route = _create_route_with_assignment_flow(
        client,
        "R-MOBILE",
        "Bus-HTML",
        driver_id=driver_id,
        school_ids=[school_id],
    )
    route_id = route["id"]  # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = _create_planned_run(client, route_id, "AM")
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]  # Save run ID

    # -------------------------------------------------------------------------
    # Add stop to run
    # -------------------------------------------------------------------------
    stop = client.post(
        "/stops/",
        json={
            "name": "School Stop",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]  # Save stop ID

    # -------------------------------------------------------------------------
    # Create first student
    # -------------------------------------------------------------------------
    first_student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={
            "name": "Present Student",
            "grade": "4",
            "school_id": school_id,
        },
    )
    assert first_student.status_code in (200, 201)
    first_student_id = first_student.json()["id"]  # Save first student ID

    # -------------------------------------------------------------------------
    # Create second student
    # -------------------------------------------------------------------------
    second_student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={
            "name": "Absent Student",
            "grade": "5",
            "school_id": school_id,
        },
    )
    assert second_student.status_code in (200, 201)
    second_student_id = second_student.json()["id"]  # Save second student ID

    started_run = _start_run_by_id(client, run_id)
    run_id = started_run.json()["id"]

    # -------------------------------------------------------------------------
    # Mark one student present
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")
    assert arrive.status_code == 200

    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": first_student_id},
    )
    assert pickup.status_code == 200

    # -------------------------------------------------------------------------
    # Request rendered mobile report
    # -------------------------------------------------------------------------
    response = client.get(f"/reports/school/{school_id}/mobile")
    assert response.status_code == 200

    body = response.text  # Rendered HTML

    assert "Rendered Attendance School" in body                           # School name appears
    assert "R-MOBILE" in body                                             # Route appears on landing page
# =============================================================================
# School confirmation persistence test
# -----------------------------------------------------------------------------
# Verifies:
# - school can confirm one run
# - confirmation is saved in DB
# - GET school attendance still returns confirmed state after refresh
# =============================================================================
def test_school_confirmation_persists_after_refresh(client):
    # -------------------------------------------------------------------------
    # Create driver                                                     # driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]                                     # save id

    # -------------------------------------------------------------------------
    # Create school                                                     # school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]                                     # save id

    # -------------------------------------------------------------------------
    # Create route linked to school                                     # route
    # -------------------------------------------------------------------------
    route = _create_route_with_assignment_flow(
        client,
        "R1",
        "Bus-01",
        driver_id=driver_id,
        school_ids=[school_id],
    )
    route_id = route["id"]                                              # save id

    # -------------------------------------------------------------------------
    # Create run                                                        # run
    # -------------------------------------------------------------------------
    run = client.post("/runs/", json={"route_id": route_id, "run_type": "AM"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]                                           # save id

        # -------------------------------------------------------------------------
    # Confirm school attendance                                         # POST confirm
    # -------------------------------------------------------------------------
    confirm = client.post(
        f"/reports/school/{school_id}/confirm/{run_id}",
        json={"confirmed_by": "Front Desk"},
    )
    assert confirm.status_code == 200
    confirm_body = confirm.json()

    assert confirm_body["message"] == "School attendance confirmed"
    assert confirm_body["school_id"] == school_id
    assert confirm_body["run_id"] == run_id
    assert confirm_body["confirmed_by"] == "Front Desk"
    assert confirm_body["confirmed_at"] is not None

    # -------------------------------------------------------------------------
    # Reload school attendance report                                   # GET after refresh
    # -------------------------------------------------------------------------
    report = client.get(f"/reports/school/{school_id}")
    assert report.status_code == 200
    body = report.json()

## =============================================================================
# Test school status update endpoint
# -----------------------------------------------------------------------------
# Verifies:
# - school-side status can be saved for one student on one run
# - value is persisted to StudentRunAssignment
# =============================================================================
def test_update_school_status(client, db_engine):                              # Use pytest temp DB engine
    
    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": "Test School",
            "address": "123 Test St",
        },
    )
    assert school.status_code in (200, 201)                                    # Confirm school created
    school_id = school.json()["id"]                                            # Save school ID

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": "Driver One",
            "email": "driver1@test.com",
            "phone": "11111",
        },
    )
    assert driver.status_code in (200, 201)                                    # Confirm driver created
    driver_id = driver.json()["id"]                                            # Save driver ID

    # -------------------------------------------------------------------------
    # Create route linked to school
    # -------------------------------------------------------------------------
    route = _create_route_with_assignment_flow(
        client,
        "R1",
        "Bus-01",
        driver_id=driver_id,
        school_ids=[school_id],
    )
    route_id = route["id"]                                                     # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post("/runs/", json={"route_id": route_id, "run_type": "AM"})
    assert run.status_code in (200, 201)                                       # Confirm run created
    run_id = run.json()["id"]                                                  # Save run ID

    # -------------------------------------------------------------------------
    # Add stop to run
    # -------------------------------------------------------------------------
    stop = client.post(
        "/stops/",
        json={
            "name": "Stop 1",
            "latitude": 53.5461,
            "longitude": -113.4938,
            "type": "pickup",
            "run_id": run_id,
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)                                      # Confirm stop created
    stop_id = stop.json()["id"]                                                # Save stop ID

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={
            "name": "Student One",
            "grade": "5",
            "school_id": school_id,
        },
    )
    assert student.status_code in (200, 201)                                   # Confirm student created
    student_id = student.json()["id"]                                          # Save student ID

    # -------------------------------------------------------------------------
    # Call school status update endpoint
    # -------------------------------------------------------------------------
    response = client.post(
        "/reports/school/student-status",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "status": "present",
        },
    )

    assert response.status_code == 200                                         # Confirm endpoint succeeded
    body = response.json()                                                     # Parse response body

    assert body["message"] == "Status updated"                                 # Confirm message
    assert body["student_id"] == student_id                                    # Confirm student echoed
    assert body["run_id"] == run_id                                            # Confirm run echoed
    assert body["school_status"] == "present"                                  # Confirm saved value

    # -------------------------------------------------------------------------
    # Verify DB persistence
    # -------------------------------------------------------------------------
    with Session(db_engine) as db:                                             # Open session on pytest temp DB
        stored_assignment = db.query(StudentRunAssignment).filter(
        StudentRunAssignment.student_id == student_id,
        StudentRunAssignment.run_id == run_id,
    ).first()
            
# -----------------------------------------------------------
# - School attendance test fixture
# - Create minimal school / route / run / assignment setup
# -----------------------------------------------------------
def _build_school_attendance_fixture(client):
    unique = uuid.uuid4().hex[:8]  # Unique suffix for test isolation
    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post(
        "/drivers/",
        json={
            "name": f"School Driver-{unique}",                               # Driver display name
            "email": f"school-driver-{unique}@test.com",                     # Unique driver email
            "phone": f"11111-{unique}",                                      # Driver phone
        },
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]                                # Save driver ID
    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post(
        "/schools/",
        json={
            "name": f"Elementary School 1-{unique}",                         # School display name
            "address": f"123 Test St-{unique}",                              # School address
        },
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]                                # Save school ID

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1-",                                  # Route number
            "driver_id": driver_id,                                # Assigned driver
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]                                  # Save route ID

    # -------------------------------------------------------------------------
    # Assign route to school
    # -------------------------------------------------------------------------
    route_assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert route_assign.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create run 1
    # -------------------------------------------------------------------------
    run_1 = _create_planned_run(client, route_id, "AM")
    assert run_1.status_code in (200, 201)
    run_1_id = run_1.json()["id"]                                  # Save run 1 ID

    # -------------------------------------------------------------------------
    # Create run 2
    # -------------------------------------------------------------------------
    run_2 = _create_planned_run(client, route_id, "PM")
    assert run_2.status_code in (200, 201)
    run_2_id = run_2.json()["id"]                                  # Save run 2 ID

    # -------------------------------------------------------------------------
    # Add stop to run 1
    # -------------------------------------------------------------------------
    stop_1 = client.post(
        "/stops/",
        json={
            "name": f"Stop 1-{unique}",                                      # Stop display name
            "latitude": 53.5461,                                   # Test latitude
            "longitude": -113.4938,                                # Test longitude
            "type": "pickup",                                      # Pickup stop
            "run_id": run_1_id,                                    # Parent run
            "sequence": 1,                                         # Stop order
        },
    )
    assert stop_1.status_code in (200, 201)
    stop_1_id = stop_1.json()["id"]                                # Save stop 1 ID

    # -------------------------------------------------------------------------
    # Add stop to run 2
    # -------------------------------------------------------------------------
    stop_2 = client.post(
        "/stops/",
        json={
            "name": f"Stop 2-{unique}",                                      # Stop display name
            "latitude": 53.5561,                                   # Test latitude
            "longitude": -113.4838,                                # Test longitude
            "type": "pickup",                                      # Pickup stop
            "run_id": run_2_id,                                    # Parent run
            "sequence": 1,                                         # Stop order
        },
    )
    assert stop_2.status_code in (200, 201)
    stop_2_id = stop_2.json()["id"]                                # Save stop 2 ID

    # -------------------------------------------------------------------------
    # Create student in run 1 stop context before start
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_1_id}/stops/{stop_1_id}/students",
        json={
            "name": f"Kass-{unique}",                              # Student name
            "grade": "5",                                          # Student grade
            "school_id": school_id,                                # Parent school
        },
    )
    assert student.status_code == 201
    student_id = student.json()["id"]                              # Save student ID

    started_run_1 = _start_run_by_id(client, run_1_id)
    run_1_id = started_run_1.json()["id"]                          # Start prepared run 1 only after stops and student exist

    # -------------------------------------------------------------------------
    # Complete run 1 so the same route driver can create run 2
    # -------------------------------------------------------------------------
    complete_run_1 = client.post(f"/runs/{run_1_id}/complete")
    assert complete_run_1.status_code == 200

    return {
        "school_id": school_id,                                    # Test school
        "route_id": route_id,                                      # Test route
        "run_1_id": run_1_id,                                      # Run with student
        "run_2_id": run_2_id,                                      # Empty run
        "student_id": student_id,                                  # Assigned student
        "stop_1_id": stop_1_id,                                    # Run 1 stop
        "stop_2_id": stop_2_id,                                    # Run 2 stop
    }


# -----------------------------------------------------------
# - School attendance report by school
# - Returns only students assigned to each run
# -----------------------------------------------------------
def test_school_attendance_report_shows_only_assigned_students_per_run(client):
    ids = _build_school_attendance_fixture(client)                  # Build minimal attendance setup

    response = client.get(f"/reports/school/{ids['school_id']}")
    assert response.status_code == 200

    body = response.json()
    assert body["school_id"] == ids["school_id"]                   # Correct school returned
    assert body["total_routes"] == 1                               # One assigned route
    assert len(body["routes"]) == 1                                # One route payload

    route = body["routes"][0]
    assert route["route_id"] == ids["route_id"]                    # Correct route returned
    assert route["total_runs"] == 2                                # Both runs included

    runs_by_id = {run["run_id"]: run for run in route["runs"]}     # Index by run ID

    run_1 = runs_by_id[ids["run_1_id"]]
    assert run_1["total_students"] == 1                            # One assigned student
    assert len(run_1["students"]) == 1                             # One visible row
    assert run_1["students"][0]["student_id"] == ids["student_id"] # Correct student shown
    assert run_1["students"][0]["student_name"].startswith("Kass-")  # Unique student name preserved
    run_2 = runs_by_id[ids["run_2_id"]]
    assert run_2["students"] == []                                 # No cross-run leakage
    assert run_2["total_students"] == 0                            # Empty run stays empty
    assert run_2["total_present"] == 0                             # No present students
    assert run_2["total_absent"] == 0                              # No absent students


# -----------------------------------------------------------
# - School-side status update persistence
# - Saved present/absent status returns in school report
# -----------------------------------------------------------
def test_school_status_update_persists_into_school_report(client):
    ids = _build_school_attendance_fixture(client)                  # Build minimal attendance setup

    update = client.post(
        "/reports/school/student-status",
        json={
            "student_id": ids["student_id"],                        # Target student
            "run_id": ids["run_1_id"],                              # Target run
            "status": "present",                                    # School-side override
        },
    )
    assert update.status_code == 200
    assert update.json()["school_status"] == "present"             # Confirm saved override

    response = client.get(f"/reports/school/{ids['school_id']}")
    assert response.status_code == 200

    body = response.json()
    route = body["routes"][0]
    runs_by_id = {run["run_id"]: run for run in route["runs"]}

    run_1 = runs_by_id[ids["run_1_id"]]
    assert run_1["total_students"] == 1                            # Still one student
    assert run_1["total_present"] == 1                             # Totals reflect saved status
    assert run_1["total_absent"] == 0                              # Totals reflect saved status
    assert run_1["students"][0]["status"] == "present"            # Persisted status returned


# -----------------------------------------------------------
# - School attendance confirmation persistence
# - Confirmed run returns confirmation in school report
# -----------------------------------------------------------
def test_school_confirmation_persists_into_school_report(client):
    ids = _build_school_attendance_fixture(client)                  # Build minimal attendance setup

    confirm = client.post(
        f"/reports/school/{ids['school_id']}/confirm/{ids['run_1_id']}",
        json={
            "confirmed_by": "frd",                                  # School confirmer
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["school_id"] == ids["school_id"]         # Correct school confirmed
    assert confirm.json()["run_id"] == ids["run_1_id"]             # Correct run confirmed
    assert confirm.json()["confirmed_by"] == "frd"                 # Confirmer persisted
    assert confirm.json()["confirmed_at"] is not None              # Timestamp persisted

    response = client.get(f"/reports/school/{ids['school_id']}")
    assert response.status_code == 200

    body = response.json()
    route = body["routes"][0]
    runs_by_id = {run["run_id"]: run for run in route["runs"]}

    run_1 = runs_by_id[ids["run_1_id"]]
    assert run_1["confirmation"]["is_confirmed"] is True           # Report shows confirmed state
    assert run_1["confirmation"]["confirmed_by"] == "frd"         # Report shows confirmer
    assert run_1["confirmation"]["confirmed_at"] is not None      # Report shows timestamp   


# -----------------------------------------------------------
# - Generic stop update compatibility
# - Preserve legacy /stops/{stop_id} updates while the run-context flow is preferred
# -----------------------------------------------------------
def test_generic_stop_update_endpoint_remains_compatible(client):
    driver = client.post(
        "/drivers/",
        json={
            "name": "Compatibility Driver",
            "email": "compatibility.driver@test.com",
            "phone": "10101",
        },
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        "COMPAT-ROUTE",
        "BUS-COMPAT",
        driver_id=driver.json()["id"],
    )
    run = client.post(f"/routes/{route['id']}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    first_stop = client.post("/stops/", json={"run_id": run_id, "sequence": 1, "type": "pickup", "name": "First"})
    second_stop = client.post("/stops/", json={"run_id": run_id, "sequence": 2, "type": "pickup", "name": "Second"})
    assert first_stop.status_code in (200, 201)
    assert second_stop.status_code in (200, 201)

    update = client.put(
        f"/stops/{second_stop.json()['id']}",
        json={"sequence": 1, "name": "Second Updated"},
    )
    assert update.status_code == 200
    assert update.json()["sequence"] == 1
    assert update.json()["name"] == "Second Updated"

    stops = client.get(f"/runs/{run_id}/stops")
    assert stops.status_code == 200
    assert [(stop["name"], stop["sequence"]) for stop in stops.json()] == [
        ("Second Updated", 1),
        ("First", 2),
    ]


# -----------------------------------------------------------
# - Context student drift repair
# - Repair same-run stop drift while preserving invalid-context guards
# -----------------------------------------------------------
def test_context_student_update_repairs_same_run_assignment_drift(client, db_engine):
    school = client.post(
        "/schools/",
        json={
            "name": "Drift Repair School",
            "address": "103 Drift Repair Way",
        },
    )
    assert school.status_code in (200, 201)

    driver = client.post(
        "/drivers/",
        json={
            "name": "Drift Repair Driver",
            "email": "drift.repair.driver@test.com",
            "phone": "10103",
        },
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        "DRIFT-REPAIR-ROUTE",
        "BUS-DRIFT-REPAIR",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )

    run = client.post(f"/routes/{route['id']}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop_a = client.post(
        f"/runs/{run_id}/stops",
        json={
            "sequence": 1,
            "type": "pickup",
            "name": "Authoritative Stop",
        },
    )
    stop_b = client.post(
        f"/runs/{run_id}/stops",
        json={
            "sequence": 2,
            "type": "pickup",
            "name": "Drifted Stop",
        },
    )
    assert stop_a.status_code in (200, 201)
    assert stop_b.status_code in (200, 201)

    student = client.post(
        f"/runs/{run_id}/stops/{stop_a.json()['id']}/students",
        json={
            "name": "Drift Repair Student",
            "grade": "4",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    with Session(db_engine) as db:
        stored_student = db.get(Student, student_id)
        stored_assignment = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.run_id == run_id)
            .filter(StudentRunAssignment.student_id == student_id)
            .first()
        )
        assert stored_student is not None
        assert stored_assignment is not None

        stored_student.stop_id = stop_b.json()["id"]             # Drift student pointer within same valid run
        stored_assignment.stop_id = stop_b.json()["id"]          # Drift runtime assignment within same valid run
        db.commit()

    updated = client.put(
        f"/runs/{run_id}/stops/{stop_a.json()['id']}/students/{student_id}",
        json={"name": "Drift Repair Student Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["stop_id"] == stop_a.json()["id"]
    assert updated.json()["route_id"] == route["id"]

    with Session(db_engine) as db:
        stored_student = db.get(Student, student_id)
        stored_assignment = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.run_id == run_id)
            .filter(StudentRunAssignment.student_id == student_id)
            .first()
        )
        assert stored_student is not None
        assert stored_assignment is not None
        assert stored_student.stop_id == stop_a.json()["id"]
        assert stored_student.route_id == route["id"]
        assert stored_assignment.stop_id == stop_a.json()["id"]


# -----------------------------------------------------------
# - Stop-context student delete
# - Remove only the selected run-stop assignment and keep student record
# -----------------------------------------------------------
def test_delete_student_inside_run_stop_context_removes_assignment_but_keeps_student(client, db_engine):
    school = client.post(
        "/schools/",
        json={"name": "Context Delete School", "address": "105 Delete Way"},
    )
    assert school.status_code in (200, 201)

    driver = client.post(
        "/drivers/",
        json={"name": "Context Delete Driver", "email": "context.delete@test.com", "phone": "10105"},
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        "CTX-DELETE-1",
        "BUS-CTX-DELETE-1",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )

    run = client.post(f"/routes/{route['id']}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Context Delete Stop"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Context Delete Student", "grade": "4", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    removed = client.delete(f"/runs/{run_id}/stops/{stop_id}/students/{student_id}")
    assert removed.status_code == 204

    student_response = client.get(f"/students/{student_id}")
    assert student_response.status_code == 200
    assert student_response.json()["route_id"] is None
    assert student_response.json()["stop_id"] is None

    assignments = client.get(f"/student-run-assignments/{run_id}")
    assert assignments.status_code == 200
    assert assignments.json() == []

    with Session(db_engine) as db:
        stored_student = db.get(Student, student_id)
        stored_assignment = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.run_id == run_id)
            .filter(StudentRunAssignment.student_id == student_id)
            .first()
        )
        assert stored_student is not None
        assert stored_student.route_id is None
        assert stored_student.stop_id is None
        assert stored_assignment is None


# -----------------------------------------------------------
# - Stop-context delete mismatch guard
# - Reject remove when stop does not belong to the selected run
# -----------------------------------------------------------
def test_delete_student_inside_run_stop_context_rejects_wrong_stop_run_pairing(client):
    school = client.post("/schools/", json={"name": "Delete Mismatch School", "address": "106 Delete Way"})
    assert school.status_code in (200, 201)

    driver = client.post(
        "/drivers/",
        json={"name": "Delete Mismatch Driver", "email": "delete.mismatch@test.com", "phone": "10106"},
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        "CTX-DELETE-MISMATCH",
        "BUS-CTX-DELETE-MISMATCH",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )

    run_one = client.post(f"/routes/{route['id']}/runs", json={"run_type": "AM"})
    run_two = client.post(f"/routes/{route['id']}/runs", json={"run_type": "PM"})
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)

    stop_one = client.post(
        f"/runs/{run_one.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Delete Match Stop"},
    )
    stop_two = client.post(
        f"/runs/{run_two.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Delete Wrong Stop"},
    )
    assert stop_one.status_code in (200, 201)
    assert stop_two.status_code in (200, 201)

    student = client.post(
        f"/runs/{run_one.json()['id']}/stops/{stop_one.json()['id']}/students",
        json={"name": "Delete Mismatch Student", "grade": "5", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201

    response = client.delete(
        f"/runs/{run_one.json()['id']}/stops/{stop_two.json()['id']}/students/{student.json()['id']}",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Stop does not belong to run"


# -----------------------------------------------------------
# - Stop-context delete missing assignment guard
# - Reject remove when the student is not assigned to the selected run
# -----------------------------------------------------------
def test_delete_student_inside_run_stop_context_rejects_missing_assignment(client):
    school = client.post("/schools/", json={"name": "Delete Missing School", "address": "107 Delete Way"})
    assert school.status_code in (200, 201)

    driver = client.post(
        "/drivers/",
        json={"name": "Delete Missing Driver", "email": "delete.missing@test.com", "phone": "10107"},
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        "CTX-DELETE-MISSING",
        "BUS-CTX-DELETE-MISSING",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )

    run = client.post(f"/routes/{route['id']}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Delete Missing Stop"},
    )
    assert stop.status_code in (200, 201)

    student = client.post(
        "/students/",
        json={
            "name": "Delete Missing Student",
            "grade": "3",
            "school_id": school.json()["id"],
            "route_id": route["id"],
            "stop_id": stop.json()["id"],
        },
    )
    assert student.status_code in (200, 201)

    response = client.delete(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Student is not assigned to run"


# -----------------------------------------------------------
# - Stop-context delete planned-only guard
# - Block contextual remove once the run has started
# -----------------------------------------------------------
def test_delete_student_inside_run_stop_context_is_blocked_after_start(client):
    context = _create_started_run_context(
        client,
        route_number="LOCK-STUDENT-DELETE",
        unit_number="BUS-LOCK-STUDENT-DELETE",
        run_type="AM",
    )

    response = client.delete(
        f"/runs/{context['run_id']}/stops/{context['stop_id']}/students/{context['student_id']}",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


# -----------------------------------------------------------
# - Full student delete compatibility
# - Keep full system-wide delete separate from contextual remove
# -----------------------------------------------------------
def test_delete_student_entirely_removes_student_record(client):
    school = client.post(
        "/schools/",
        json={"name": "Full Delete School", "address": "108 Delete Way"},
    )
    assert school.status_code in (200, 201)

    student = client.post(
        "/students/",
        json={"name": "Full Delete Student", "grade": "6", "school_id": school.json()["id"]},
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    deleted = client.delete(f"/students/{student_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/students/{student_id}")
    assert missing.status_code == 404


# -----------------------------------------------------------
# - Dedicated student assignment movement
# - Keep broader route/stop reassignment separate from in-run context repair
# -----------------------------------------------------------
def test_student_assignment_update_endpoint_is_blocked_when_target_run_is_started(client):
    school = client.post(
        "/schools/",
        json={"name": "Assignment Planned Lock School", "address": "109 Lock Way"},
    )
    assert school.status_code in (200, 201)

    driver = client.post(
        "/drivers/",
        json={"name": "Assignment Planned Lock Driver", "email": "assignment.planned.lock@test.com", "phone": "10109"},
    )
    assert driver.status_code in (200, 201)

    route = _create_route_with_assignment_flow(
        client,
        "ASSIGN-LOCK-ROUTE",
        "BUS-ASSIGN-LOCK-ROUTE",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )

    source_run = client.post(f"/routes/{route['id']}/runs", json={"run_type": "AM"})
    target_run = client.post(f"/routes/{route['id']}/runs", json={"run_type": "PM"})
    assert source_run.status_code in (200, 201)
    assert target_run.status_code in (200, 201)

    source_stop = client.post(
        "/stops/",
        json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Assignment Lock Source Stop"},
    )
    target_stop = client.post(
        "/stops/",
        json={"run_id": target_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Assignment Lock Target Stop"},
    )
    assert source_stop.status_code in (200, 201)
    assert target_stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{source_run.json()['id']}/stops/{source_stop.json()['id']}/students",
        json={
            "name": "Assignment Lock Student",
            "grade": "4",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code == 201

    prep_student = client.post(
        f"/runs/{target_run.json()['id']}/stops/{target_stop.json()['id']}/students",
        json={
            "name": "Assignment Lock Prep Student",
            "grade": "4",
            "school_id": school.json()["id"],
        },
    )
    assert prep_student.status_code == 201

    started_target_run = client.post(f"/runs/start?run_id={target_run.json()['id']}")
    assert started_target_run.status_code in (200, 201)

    moved = client.put(
        f"/students/{student.json()['id']}/assignment",
        json={
            "route_id": route["id"],
            "run_id": target_run.json()["id"],
            "stop_id": target_stop.json()["id"],
        },
    )

    assert moved.status_code == 400
    assert moved.json()["detail"] == "Only planned runs can be modified"


def test_student_assignment_update_endpoint_moves_planning_state_safely(client, db_engine):
    school = client.post(
        "/schools/",
        json={
            "name": "Dedicated Assignment School",
            "address": "104 Dedicated Way",
        },
    )
    assert school.status_code in (200, 201)

    driver = client.post(
        "/drivers/",
        json={
            "name": "Dedicated Assignment Driver",
            "email": "dedicated.assignment.driver@test.com",
            "phone": "10104",
        },
    )
    assert driver.status_code in (200, 201)

    source_route = _create_route_with_assignment_flow(
        client,
        "DEDICATED-SRC",
        "BUS-DEDICATED-SRC",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )
    target_route = _create_route_with_assignment_flow(
        client,
        "DEDICATED-TGT",
        "BUS-DEDICATED-TGT",
        driver_id=driver.json()["id"],
        school_ids=[school.json()["id"]],
    )

    source_run = client.post(f"/routes/{source_route['id']}/runs", json={"run_type": "AM"})
    target_run = client.post(f"/routes/{target_route['id']}/runs", json={"run_type": "AM"})
    completed_run = client.post(f"/routes/{source_route['id']}/runs", json={"run_type": "PM"})
    assert source_run.status_code in (200, 201)
    assert target_run.status_code in (200, 201)
    assert completed_run.status_code in (200, 201)

    source_stop = client.post(
        "/stops/",
        json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Dedicated Source Stop"},
    )
    target_stop = client.post(
        "/stops/",
        json={"run_id": target_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Dedicated Target Stop"},
    )
    completed_stop = client.post(
        "/stops/",
        json={"run_id": completed_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Completed Source Stop"},
    )
    assert source_stop.status_code in (200, 201)
    assert target_stop.status_code in (200, 201)
    assert completed_stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{source_run.json()['id']}/stops/{source_stop.json()['id']}/students",
         json={
            "name": "Dedicated Assignment Student",
            "grade": "4",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    completed_assignment = client.put(
        f"/students/{student_id}/assignment",
        json={
            "route_id": source_route["id"],
            "run_id": completed_run.json()["id"],
            "stop_id": completed_stop.json()["id"],
        },
    )
    assert completed_assignment.status_code == 200

    with Session(db_engine) as db:
        completed_run_row = db.get(run_model.Run, completed_run.json()["id"])
        assert completed_run_row is not None
        completed_run_row.end_time = datetime.now(timezone.utc)
        completed_run_row.is_completed = True                    # Preserve completed run history during reassignment
        db.commit()

    moved = client.put(
        f"/students/{student_id}/assignment",
        json={
            "route_id": target_route["id"],
            "run_id": target_run.json()["id"],
            "stop_id": target_stop.json()["id"],
        },
    )
    assert moved.status_code == 200
    assert moved.json()["route_id"] == target_route["id"]
    assert moved.json()["stop_id"] == target_stop.json()["id"]

    with Session(db_engine) as db:
        stored_student = db.get(Student, student_id)
        assert stored_student is not None
        assert stored_student.route_id == target_route["id"]
        assert stored_student.stop_id == target_stop.json()["id"]

        assignments = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.student_id == student_id)
            .all()
        )
        assignments_by_run = {assignment.run_id: assignment for assignment in assignments}

        assert source_run.json()["id"] not in assignments_by_run
        assert assignments_by_run[target_run.json()["id"]].stop_id == target_stop.json()["id"]
        assert assignments_by_run[completed_run.json()["id"]].stop_id == completed_stop.json()["id"]
     

