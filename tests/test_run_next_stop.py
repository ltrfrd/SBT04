# =============================================================================
# tests/test_run_next_stop.py
# -----------------------------------------------------------------------------
# Purpose:
#   Verify that POST /runs/{run_id}/next_stop advances run progress correctly.
#
# Behavior verified:
#   - If current_stop_sequence is None → next_stop sets it to 1
#   - Calling next_stop again increments to the next sequence
#   - Stop must exist in the run
# =============================================================================


def test_next_stop_advances_progress(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_res = client.post(
        "/drivers/",
        json={
            "name": "Driver Next Stop",
            "email": "driver_next_stop@example.com",
            "phone": "555-000-1111",
        },
    )
    assert driver_res.status_code in (200, 201)
    driver_id = driver_res.json()["id"]

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route_res = client.post(
        "/routes/",
        json={
            "route_number": "NEXT-STOP-01",
            "unit_number": "BUS-NEXT-01",
        },
    )
    assert route_res.status_code in (200, 201)
    route_id = route_res.json()["id"]

    assign_res = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run_res = client.post(
        "/runs/start",
        json={
            "route_id": route_id,
            "run_type": "AM",
        },
    )
    assert run_res.status_code in (200, 201)
    run_id = run_res.json()["id"]

    # -------------------------------------------------------------------------
    # Add stops
    # -------------------------------------------------------------------------
    client.post("/stops/", json={
        "run_id": run_id,
        "sequence": 1,
        "type": "pickup",
        "name": "Stop 1",
        "address": "A",
        "planned_time": "07:00:00",
        "latitude": 1,
        "longitude": 1,
    })

    client.post("/stops/", json={
        "run_id": run_id,
        "sequence": 2,
        "type": "pickup",
        "name": "Stop 2",
        "address": "B",
        "planned_time": "07:10:00",
        "latitude": 2,
        "longitude": 2,
    })

    # -------------------------------------------------------------------------
    # First next_stop → should set progress to 1
    # -------------------------------------------------------------------------
    res1 = client.post(f"/runs/{run_id}/next_stop")
    assert res1.status_code in (200, 201)

    data1 = res1.json()
    assert data1["current_stop_sequence"] == 1

    # -------------------------------------------------------------------------
    # Second next_stop → should advance to 2
    # -------------------------------------------------------------------------
    res2 = client.post(f"/runs/{run_id}/next_stop")
    assert res2.status_code in (200, 201)

    data2 = res2.json()
    assert data2["current_stop_sequence"] == 2
