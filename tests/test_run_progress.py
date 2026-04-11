# =============================================================================
# tests/test_run_progress.py
# -----------------------------------------------------------------------------
# Purpose:
#   Verify that start only works for prepared runs that already have stops
#   and at least one runtime student assignment.
#
# Endpoint flow tested:
#   - POST /routes/{route_id}/runs
#   - POST /stops/
#   - POST /runs/{run_id}/stops/{stop_id}/students
#   - POST /runs/start
# =============================================================================
from tests.conftest import ensure_prepared_run_student


# =============================================================================
# Test: starting an unprepared run fails without stops
# =============================================================================
def test_start_run_requires_prepared_stops(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_response = client.post(
        "/drivers/",
        json={
            "name": "John Driver",
            "email": "john.driver@example.com",
            "phone": "111-222-3333",
            "pin": "1234",
        },
    )
    assert driver_response.status_code in (200, 201)
    driver_id = driver_response.json()["id"]  # Created driver ID

    school_response = client.post(
        "/schools/",
        json={
            "name": "Copy School",
            "address": "10 Copy Way",
        },
    )
    assert school_response.status_code in (200, 201)
    school_id = school_response.json()["id"]  # Created school ID

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route_response = client.post(
        "/routes/",
        json={
            "route_number": "12",
            "school_ids": [school_id],
        },
    )
    assert route_response.status_code in (200, 201)
    route_id = route_response.json()["id"]  # Created route ID

    assign_response = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_response.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create planned run directly
    # -------------------------------------------------------------------------
    source_run_response = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert source_run_response.status_code in (200, 201)
    source_run_id = source_run_response.json()["id"]  # Planned run ID

    # -------------------------------------------------------------------------
    # Starting without prepared stops should now fail
    # -------------------------------------------------------------------------
    start_response = client.post(f"/runs/start?run_id={source_run_id}")
    assert start_response.status_code == 400
    assert start_response.json()["detail"] == "Run has no stops. Prepare stops before starting the run."


# =============================================================================
# Test: starting a run with stops but no students fails
# =============================================================================
def test_start_run_requires_prepared_students(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_response = client.post(
        "/drivers/",
        json={
            "name": "Student Guard Driver",
            "email": "student.guard@example.com",
            "phone": "111-222-4444",
            "pin": "1234",
        },
    )
    assert driver_response.status_code in (200, 201)
    driver_id = driver_response.json()["id"]

    school_response = client.post(
        "/schools/",
        json={
            "name": "Student Guard School",
            "address": "11 Guard Way",
        },
    )
    assert school_response.status_code in (200, 201)
    school_id = school_response.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route_response = client.post(
        "/routes/",
        json={
            "route_number": "13",
            "school_ids": [school_id],
        },
    )
    assert route_response.status_code in (200, 201)
    route_id = route_response.json()["id"]

    assign_response = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_response.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create planned run with stops only
    # -------------------------------------------------------------------------
    source_run_response = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert source_run_response.status_code in (200, 201)
    source_run_id = source_run_response.json()["id"]

    stop_response = client.post(
        f"/runs/{source_run_id}/stops",
        json={
            "sequence": 1,
            "type": "pickup",
            "name": "Prepared Stop Without Student",
            "address": "100 Guard Stop",
        },
    )
    assert stop_response.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Starting without runtime students should now fail
    # -------------------------------------------------------------------------
    start_response = client.post(f"/runs/start?run_id={source_run_id}")
    assert start_response.status_code == 400
    assert start_response.json()["detail"] == "Run has no students. Assign students before starting the run."


# =============================================================================
# Test: state reflects stored current stop after arrive_stop
# =============================================================================
def test_run_state_uses_stored_current_stop_sequence(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_res = client.post(
        "/drivers/",
        json={
            "name": "Driver State Stored",
            "email": "driver_state_stored@example.com",
            "phone": "780-555-1101",
            "pin": "1234",
        },
    )
    assert driver_res.status_code in (200, 201)
    driver_id = driver_res.json()["id"]  # Created driver ID

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route_res = client.post(
        "/routes/",
        json={
            "route_number": "R-STATE-STORED",
        },
    )
    assert route_res.status_code in (200, 201)
    route_id = route_res.json()["id"]  # Created route ID

    assign_res = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create planned run with ordered stops
    # -------------------------------------------------------------------------
    seed_run_res = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert seed_run_res.status_code in (200, 201)
    seed_run_id = seed_run_res.json()["id"]  # Seed run ID

    stop_1_res = client.post(
        "/stops/",
        json={
            "run_id": seed_run_id,
            "sequence": 1,
            "type": "pickup",
            "name": "Stop 1",
            "address": "100 First St",
            "planned_time": "07:10:00",
            "latitude": 53.5461,
            "longitude": -113.4938,
        },
    )
    assert stop_1_res.status_code in (200, 201)

    stop_2_res = client.post(
        "/stops/",
        json={
            "run_id": seed_run_id,
            "sequence": 2,
            "type": "pickup",
            "name": "Stop 2",
            "address": "200 Second St",
            "planned_time": "07:20:00",
            "latitude": 53.5561,
            "longitude": -113.4838,
        },
    )
    assert stop_2_res.status_code in (200, 201)

    stop_3_res = client.post(
        "/stops/",
        json={
            "run_id": seed_run_id,
            "sequence": 3,
            "type": "pickup",
            "name": "Stop 3",
            "address": "300 Third St",
            "planned_time": "07:30:00",
            "latitude": 53.5661,
            "longitude": -113.4738,
        },
    )
    assert stop_3_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Start the prepared run
    # -------------------------------------------------------------------------
    ensure_prepared_run_student(client, seed_run_id)
    active_run_res = client.post(f"/runs/start?run_id={seed_run_id}")
    assert active_run_res.status_code in (200, 201)
    active_run_id = active_run_res.json()["id"]  # Started run ID
    active_stop_2_id = stop_2_res.json()["id"]   # Existing stop 2 ID for the started run

    # -------------------------------------------------------------------------
    # Store live location at stop sequence 2
    # -------------------------------------------------------------------------
    arrive_res = client.post(f"/runs/{active_run_id}/arrive_stop?stop_sequence=2")
    assert arrive_res.status_code == 200

    # -------------------------------------------------------------------------
    # Read the current run snapshot
    # -------------------------------------------------------------------------
    state_res = client.get(f"/runs/{active_run_id}/state")
    assert state_res.status_code == 200

    data = state_res.json()

    # -------------------------------------------------------------------------
    # Verify current run snapshot reflects stored location
    # -------------------------------------------------------------------------
    assert data["current_stop_id"] == active_stop_2_id
    assert data["current_stop_sequence"] == 2
    assert data["current_stop_name"] == "Stop 2"
    assert data["total_stops"] == 3
    assert data["completed_stops"] == 1
    assert data["remaining_stops"] == 2
    assert data["progress_percent"] == 33.3
