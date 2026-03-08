# =============================================================================
# tests/test_run_progress.py
# -----------------------------------------------------------------------------
# Purpose:
#   Verify that starting a new run copies stops from the latest route run
#   that already has stops.
#
# Endpoint flow tested:
#   - POST /runs/
#   - POST /stops/
#   - POST /runs/end
#   - POST /runs/start
#   - GET /runs/{run_id}/stops
# =============================================================================


# =============================================================================
# Test: starting a new run copies stops from the latest route run with stops
# =============================================================================
def test_start_run_copies_stops_from_latest_route_run(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_response = client.post(
        "/drivers/",
        json={
            "name": "John Driver",
            "email": "john.driver@example.com",
            "phone": "111-222-3333",
        },
    )
    assert driver_response.status_code in (200, 201)
    driver_id = driver_response.json()["id"]  # Created driver ID

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route_response = client.post(
        "/routes/",
        json={
            "route_number": "12",
            "unit_number": "BUS-12",
            "driver_id": driver_id,
        },
    )
    assert route_response.status_code in (200, 201)
    route_id = route_response.json()["id"]  # Created route ID

    # -------------------------------------------------------------------------
    # Create source run directly
    # This run will hold the original stops that should be copied later
    # -------------------------------------------------------------------------
    source_run_response = client.post(
        "/runs/",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
    assert source_run_response.status_code in (200, 201)
    source_run_id = source_run_response.json()["id"]  # Original run ID

    # -------------------------------------------------------------------------
    # Add stops to the source run
    # -------------------------------------------------------------------------
    stop_1_response = client.post(
        "/stops/",
        json={
            "run_id": source_run_id,
            "sequence": 1,
            "type": "pickup",
            "name": "Stop 1",
            "address": "123 First Street",
            "planned_time": "07:10:00",
            "latitude": 53.5461,
            "longitude": -113.4938,
        },
    )
    assert stop_1_response.status_code in (200, 201)

    stop_2_response = client.post(
        "/stops/",
        json={
            "run_id": source_run_id,
            "sequence": 2,
            "type": "pickup",
            "name": "Stop 2",
            "address": "456 Second Avenue",
            "planned_time": "07:20:00",
            "latitude": 53.5561,
            "longitude": -113.5038,
        },
    )
    assert stop_2_response.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # End the source run so the same driver can start a new active run
    # -------------------------------------------------------------------------
    end_response = client.post(f"/runs/end?run_id={source_run_id}")
    assert end_response.status_code == 200

    # -------------------------------------------------------------------------
    # Start a fresh run on the same route
    # Expected behavior: stops are copied from the latest route run with stops
    # -------------------------------------------------------------------------
    new_run_response = client.post(
        "/runs/start",
        json={
            "driver_id": driver_id,
            "route_id": route_id,
            "run_type": "AM",
        },
    )
    assert new_run_response.status_code in (200, 201)
    new_run_id = new_run_response.json()["id"]  # New active run ID

    assert new_run_id != source_run_id  # Ensure this is a different run

    # -------------------------------------------------------------------------
    # Load copied stops from the new run
    # -------------------------------------------------------------------------
    new_stops_response = client.get(f"/runs/{new_run_id}/stops")
    assert new_stops_response.status_code == 200

    new_stops = new_stops_response.json()
    assert len(new_stops) == 2  # Two stops should be copied

    # -------------------------------------------------------------------------
    # Validate copied stop 1
    # -------------------------------------------------------------------------
    assert new_stops[0]["run_id"] == new_run_id
    assert new_stops[0]["sequence"] == 1
    assert new_stops[0]["name"] == "Stop 1"
    assert new_stops[0]["address"] == "123 First Street"
    assert new_stops[0]["planned_time"] == "07:10:00"
    assert new_stops[0]["latitude"] == 53.5461
    assert new_stops[0]["longitude"] == -113.4938

    # -------------------------------------------------------------------------
    # Validate copied stop 2
    # -------------------------------------------------------------------------
    assert new_stops[1]["run_id"] == new_run_id
    assert new_stops[1]["sequence"] == 2
    assert new_stops[1]["name"] == "Stop 2"
    assert new_stops[1]["address"] == "456 Second Avenue"
    assert new_stops[1]["planned_time"] == "07:20:00"
    assert new_stops[1]["latitude"] == 53.5561
    assert new_stops[1]["longitude"] == -113.5038