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
from database import engine                                        # DB engine
import uuid

from tests.conftest import client
# =============================================================================
# Project Models (used directly in tests)
# =============================================================================

def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "BST01 backend is running"


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


def test_websocket_gps(client):
    client.post("/drivers/", json={"name": "D", "email": "d@d.com", "phone": "000"})
    client.post("/login", json={"driver_id": 1})

    r = client.post("/routes/", json={"route_number": "R1", "unit_number": "Test", "driver_id": 1})
    assert r.status_code in (200, 201)
    route_id = r.json()["id"]

    r = client.post("/runs/start", json={"driver_id": 1, "route_id": route_id, "run_type": "AM"})
    assert r.status_code in (200, 201)
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

    r = client.post("/routes/", json={"route_number": "R1", "unit_number": "Bus-01", "driver_id": driver_id})
    assert r.status_code in (200, 201)
    route_id = r.json()["id"]

    r = client.post("/runs/start", json={"driver_id": driver_id, "route_id": route_id, "run_type": "AM"})
    assert r.status_code in (200, 201)
    run_id = r.json()["id"]

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

    with client.websocket_connect(f"/ws/gps/{run_id}") as ws:
        ws.send_json({"lat": 40.7580, "lng": -73.9855})
        data = ws.receive_json()
        assert "progress" in data


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
            "unit_number": "Bus-01",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
        "/students/",
        json={
            "name": "Student Two",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop2_id,
        },
    )
    student_id = student.json()["id"]  # Save student ID

    # -------------------------------------------------------------------------
    # Create runtime assignment for this run
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop2_id,
        },
    )
    assert assignment.status_code == 201

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
            "unit_number": "Bus-01",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
            "unit_number": "Bus-01",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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

    # -------------------------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop2_id,
        },
    )
    assert assignment.status_code == 201

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
            "unit_number": "Bus-01",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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

    # -------------------------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop2_id,
        },
    )
    assert assignment.status_code == 201

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
            "unit_number": "Bus-01",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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

    # -------------------------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop2_id,
        },
    )
    assert assignment.status_code == 201

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
    assert dropoff.json()["detail"] == "Student is not currently onboard"


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
            "unit_number": "Bus-01",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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

    # -------------------------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop2_id,
        },
    )
    assert assignment.status_code == 201

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
    assert second_dropoff.json()["detail"] == "Student is not currently onboard"



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
            "unit_number": "Bus-01",
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
            "unit_number": "Bus-01",
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
            "unit_number": "Bus-02",
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
            "unit_number": "Bus-State",
            "driver_id": driver_id,
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
        "/students/",
        json={
            "name": "State Student",
            "grade": "4",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop1_id,
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop1_id,
        },
    )
    assert assignment.status_code == 201

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
    route = client.post("/routes/", json={"route_number": "R3", "unit_number": "Bus-03", "driver_id": driver_id})  # Create route
    route_id = route.json()["id"]  # Extract route ID from API response
    run = client.post("/runs/", json={"driver_id": driver_id, "route_id": route_id, "run_type": "AM"})  # Create active run
    run_id = run.json()["id"]  # Extract run ID from API response
    stop1 = client.post("/stops/", json={"name": "Stop 1", "latitude": 53.5461, "longitude": -113.4938, "type": "pickup", "run_id": run_id, "sequence": 1})  # Create first stop
    stop1_id = stop1.json()["id"]  # Extract first stop ID from API response
    stop2 = client.post("/stops/", json={"name": "Stop 2", "latitude": 53.5561, "longitude": -113.4838, "type": "pickup", "run_id": run_id, "sequence": 2})  # Create second stop
    stop2_id = stop2.json()["id"]  # Extract second stop ID from API response

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
    route = client.post("/routes/", json={"route_number": "R4", "unit_number": "Bus-04", "driver_id": driver_id})  # Create route
    route_id = route.json()["id"]  # Extract route ID from API response
    run = client.post("/runs/", json={"driver_id": driver_id, "route_id": route_id, "run_type": "AM"})  # Create run
    run_id = run.json()["id"]  # Extract run ID from API response
    stop1 = client.post("/stops/", json={"name": "Corner Pickup", "latitude": 53.5461, "longitude": -113.4938, "type": "pickup", "run_id": run_id, "sequence": 1})  # Create alternate pickup stop
    stop1_id = stop1.json()["id"]  # Extract alternate pickup stop ID
    stop2 = client.post("/stops/", json={"name": "Assigned Pickup", "latitude": 53.5561, "longitude": -113.4838, "type": "pickup", "run_id": run_id, "sequence": 2})  # Create assigned pickup stop
    stop2_id = stop2.json()["id"]  # Extract assigned pickup stop ID
    stop3 = client.post("/stops/", json={"name": "School Dropoff", "latitude": 53.5661, "longitude": -113.4738, "type": "dropoff", "run_id": run_id, "sequence": 3})  # Create alternate dropoff stop
    stop3_id = stop3.json()["id"]  # Extract alternate dropoff stop ID
    student = client.post("/students/", json={"name": "Flexible Rider", "grade": "5", "school_id": school_id, "route_id": route_id, "stop_id": stop2_id})  # Create student assigned to stop 2
    student_id = student.json()["id"]  # Extract student ID from API response
    assignment = client.post("/student-run-assignments/", json={"student_id": student_id, "run_id": run_id, "stop_id": stop2_id})  # Create runtime assignment at planned stop 2
    assert assignment.status_code == 201  # Confirm assignment creation succeeded

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
            "unit_number": "Bus-TL",
            "driver_id": driver_id,
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------
    # Create run
    # -------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
        "/students/",
        json={
            "name": "Timeline Student",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop1_id,
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]  # Save student ID

    # -------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop1_id,
        },
    )
    assert assignment.status_code == 201

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
            "unit_number": "Bus-RP",
            "driver_id": driver_id,
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
        "/students/",
        json={
            "name": "Replay Student",
            "grade": "6",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop1_id,
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]  # Save student ID

    # -------------------------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop1_id,
        },
    )
    assert assignment.status_code == 201

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
            "unit_number": "Bus-COMP",
            "driver_id": driver_id,
        },
    )
    route_id = route.json()["id"]

    # -------------------------------------------------------
    # Create run
    # -------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
    run_id = run.json()["id"]

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
    route = client.post(
        "/routes/",
        json={
            "route_number": "R-MOBILE",
            "unit_number": "Bus-HTML",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]  # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
        "/students/",
        json={
            "name": "Present Student",
            "grade": "4",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop_id,
        },
    )
    assert first_student.status_code in (200, 201)
    first_student_id = first_student.json()["id"]  # Save first student ID

    # -------------------------------------------------------------------------
    # Create second student
    # -------------------------------------------------------------------------
    second_student = client.post(
        "/students/",
        json={
            "name": "Absent Student",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop_id,
        },
    )
    assert second_student.status_code in (200, 201)
    second_student_id = second_student.json()["id"]  # Save second student ID

    # -------------------------------------------------------------------------
    # Create runtime assignments
    # -------------------------------------------------------------------------
    first_assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": first_student_id,
            "run_id": run_id,
            "stop_id": stop_id,
        },
    )
    assert first_assignment.status_code == 201

    second_assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": second_student_id,
            "run_id": run_id,
            "stop_id": stop_id,
        },
    )
    assert second_assignment.status_code == 201

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
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "unit_number": "Bus-01",
            "driver_id": driver_id,
            "school_ids": [school_id],                                  # attach school
        },
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]                                       # save id

    # -------------------------------------------------------------------------
    # Create run                                                        # run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
    route = client.post(
        "/routes/",
        json={
            "route_number": "R1",
            "unit_number": "Bus-01",
            "driver_id": driver_id,
            "school_ids": [school_id],
        },
    )
    assert route.status_code in (200, 201)                                     # Confirm route created
    route_id = route.json()["id"]                                              # Save route ID

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
        "/students/",
        json={
            "name": "Student One",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_id,
            "stop_id": stop_id,
        },
    )
    assert student.status_code in (200, 201)                                   # Confirm student created
    student_id = student.json()["id"]                                          # Save student ID

    # -------------------------------------------------------------------------
    # Create runtime assignment
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop_id,
        },
    )
    assert assignment.status_code == 201                                       # Confirm assignment created

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
    # Create second driver for second run
    # -------------------------------------------------------------------------
    driver_2 = client.post(
        "/drivers/",
        json={
            "name": f"School Driver Two-{unique}",                         # Second driver display name
            "email": f"school-driver-two-{unique}@test.com",              # Unique second driver email
            "phone": f"22222-{unique}",                                   # Second driver phone
        },
    )
    assert driver_2.status_code in (200, 201)
    driver_2_id = driver_2.json()["id"]                                   # Save second driver ID
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
            "unit_number": "Bus-01",                               # Bus/unit number
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
    run_1 = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,                                # Assigned driver
            "route_id": route_id,                                  # Parent route
            "run_type": "AM",                                      # Morning run
        },
    )
    assert run_1.status_code in (200, 201)
    run_1_id = run_1.json()["id"]                                  # Save run 1 ID

    # -------------------------------------------------------------------------
    # Create run 2
    # -------------------------------------------------------------------------
    run_2 = client.post(
        "/runs/",
        json={
            "driver_id": driver_2_id,                                      # Use second driver to avoid active-run conflict
            "route_id": route_id,
            "run_type": "AM",
        },
    )
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
    # Create student on route / school roster
    # -------------------------------------------------------------------------
    student = client.post(
        "/students/",
        json={
            "name": f"Kass-{unique}",                                        # Student name
            "grade": "5",                                          # Student grade
            "school_id": school_id,                                # Parent school
            "route_id": route_id,                                  # Parent route
            "stop_id": stop_1_id,                                  # Default stop
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]                              # Save student ID

    # -------------------------------------------------------------------------
    # Assign student to run 1 only
    # -------------------------------------------------------------------------
    assignment = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student_id,                              # Assigned student
            "run_id": run_1_id,                                    # Assigned run
            "stop_id": stop_1_id,                                  # Assigned stop
        },
    )
    assert assignment.status_code == 201

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
     