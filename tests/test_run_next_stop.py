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
from tests.conftest import ensure_prepared_run_student


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
        },
    )
    assert route_res.status_code in (200, 201)
    route_id = route_res.json()["id"]

    assign_res = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create planned run
    # -------------------------------------------------------------------------
    run_res = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run_res.status_code in (200, 201)
    run_id = run_res.json()["id"]

    # -------------------------------------------------------------------------
    # Add stops
    # -------------------------------------------------------------------------
    first_stop = client.post("/stops/", json={
        "run_id": run_id,
        "sequence": 1,
        "type": "pickup",
        "name": "Stop 1",
        "address": "A",
        "planned_time": "07:00:00",
        "latitude": 1,
        "longitude": 1,
    })
    assert first_stop.status_code in (200, 201)

    second_stop = client.post("/stops/", json={
        "run_id": run_id,
        "sequence": 2,
        "type": "pickup",
        "name": "Stop 2",
        "address": "B",
        "planned_time": "07:10:00",
        "latitude": 2,
        "longitude": 2,
    })
    assert second_stop.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Start prepared run
    # -------------------------------------------------------------------------
    ensure_prepared_run_student(client, run_id)
    start_res = client.post(f"/runs/start?run_id={run_id}")
    assert start_res.status_code in (200, 201)

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


def test_next_stop_uses_actual_current_stop_after_manual_jump(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_res = client.post(
        "/drivers/",
        json={
            "name": "Driver Next Stop Jump",
            "email": "driver_next_stop_jump@example.com",
            "phone": "555-000-2222",
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
            "route_number": "NEXT-STOP-02",
        },
    )
    assert route_res.status_code in (200, 201)
    route_id = route_res.json()["id"]

    assign_res = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create planned run
    # -------------------------------------------------------------------------
    run_res = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run_res.status_code in (200, 201)
    run_id = run_res.json()["id"]

    # -------------------------------------------------------------------------
    # Add three ordered stops
    # -------------------------------------------------------------------------
    for sequence in (1, 2, 3):
        stop_res = client.post(
            "/stops/",
            json={
                "run_id": run_id,
                "sequence": sequence,
                "type": "pickup",
                "name": f"Stop {sequence}",
                "address": f"{sequence} Main St",
                "planned_time": f"07:0{sequence}:00",
                "latitude": sequence,
                "longitude": sequence,
            },
        )
        assert stop_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Start prepared run
    # -------------------------------------------------------------------------
    ensure_prepared_run_student(client, run_id)
    start_res = client.post(f"/runs/start?run_id={run_id}")
    assert start_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Jump directly to stop 2 using flexible arrival
    # -------------------------------------------------------------------------
    arrive_res = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=2")
    assert arrive_res.status_code == 200
    assert arrive_res.json()["current_stop_sequence"] == 2

    # -------------------------------------------------------------------------
    # next_stop should continue from the actual current stop
    # -------------------------------------------------------------------------
    next_res = client.post(f"/runs/{run_id}/next_stop")
    assert next_res.status_code in (200, 201)
    assert next_res.json()["current_stop_sequence"] == 3


def test_arrive_stop_accepts_explicit_stop_id_for_flexible_runtime_location(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver_res = client.post(
        "/drivers/",
        json={
            "name": "Driver Stop Id",
            "email": "driver_stop_id@example.com",
            "phone": "555-000-3333",
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
            "route_number": "ARRIVE-STOP-ID-01",
        },
    )
    assert route_res.status_code in (200, 201)
    route_id = route_res.json()["id"]

    assign_res = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign_res.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create planned run with ordered stops
    # -------------------------------------------------------------------------
    run_res = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run_res.status_code in (200, 201)
    run_id = run_res.json()["id"]

    first_stop = client.post(
        "/stops/",
        json={
            "run_id": run_id,
            "sequence": 1,
            "type": "pickup",
            "name": "Stop 1",
            "address": "1 Main St",
            "planned_time": "07:01:00",
            "latitude": 1,
            "longitude": 1,
        },
    )
    second_stop = client.post(
        "/stops/",
        json={
            "run_id": run_id,
            "sequence": 2,
            "type": "pickup",
            "name": "Stop 2",
            "address": "2 Main St",
            "planned_time": "07:02:00",
            "latitude": 2,
            "longitude": 2,
        },
    )
    assert first_stop.status_code in (200, 201)
    assert second_stop.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Start prepared run and jump directly by stop_id
    # -------------------------------------------------------------------------
    ensure_prepared_run_student(client, run_id)
    start_res = client.post(f"/runs/start?run_id={run_id}")
    assert start_res.status_code in (200, 201)

    arrive_res = client.post(f"/runs/{run_id}/arrive_stop?stop_id={second_stop.json()['id']}")
    assert arrive_res.status_code == 200
    assert arrive_res.json()["current_stop_id"] == second_stop.json()["id"]
    assert arrive_res.json()["current_stop_sequence"] == 2
