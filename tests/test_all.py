import pytest

from tests.conftest import client


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
# Onboard Students Tests
# -----------------------------------------------------------------------------
# These tests verify the onboard-students endpoint for active runs.
#
# Coverage:
#   - success with one onboard student
#   - success with no onboard students
#   - run not found
# =============================================================================


# =============================================================================
# Test onboard_students returns one onboard student
# =============================================================================
def test_get_onboard_students_success(client):
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
    # Add stop 1 and stop 2
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
    # Move run to stop 2 and pick up student
    # -------------------------------------------------------------------------
    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive.status_code == 200

    pickup = client.post(
        f"/runs/{run_id}/pickup_student",
        json={"student_id": student_id},
    )
    assert pickup.status_code == 200

    # -------------------------------------------------------------------------
    # Get onboard students
    # -------------------------------------------------------------------------
    response = client.get(f"/runs/{run_id}/onboard_students")

    assert response.status_code == 200
    body = response.json()

    assert body["run_id"] == run_id
    assert body["total_onboard_students"] == 1
    assert len(body["students"]) == 1
    assert body["students"][0]["student_id"] == student_id
    assert body["students"][0]["student_name"] == "Student Two"
    assert body["students"][0]["stop_id"] == stop2_id
    assert body["students"][0]["stop_sequence"] == 2
    assert body["students"][0]["picked_up_at"] is not None


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