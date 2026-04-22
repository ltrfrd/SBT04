from tests.conftest import ensure_route_has_execution_yard


def test_stop_append_mode_assigns_next_sequence(client):
    driver = client.post(
        "/drivers/",
        json={"yard_id": client.ensure_current_operator_yard_id(), "name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    district = client.post("/districts/", json={"name": "R1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "R1 School", "address": "1 Main St"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assigned_driver.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_id)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    s1 = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "A", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    s2 = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "B", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )

    assert s1.status_code in (200, 201)
    assert s2.status_code in (200, 201)
    assert s1.json()["sequence"] == 1
    assert s2.json()["sequence"] == 2


def test_stop_insert_mode_shifts_block(client):
    driver = client.post(
        "/drivers/",
        json={"yard_id": client.ensure_current_operator_yard_id(), "name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    district = client.post("/districts/", json={"name": "R1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "R1 School", "address": "1 Main St"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assigned_driver.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_id)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    first = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "A", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    second = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "B", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    third = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "C", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    inserted = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "X", "latitude": 40.0, "longitude": -70.0, "type": "pickup", "sequence": 2},
    )

    assert first.status_code in (200, 201)
    assert second.status_code in (200, 201)
    assert third.status_code in (200, 201)
    assert inserted.status_code in (200, 201)

    stops = client.get("/stops/", params={"run_id": run_id})
    assert stops.status_code == 200
    names = [s["name"] for s in stops.json()]
    seqs = [s["sequence"] for s in stops.json()]

    assert names == ["A", "X", "B", "C"]
    assert seqs == [1, 2, 3, 4]


def test_stop_reorder_moves_and_shifts(client):
    driver = client.post(
        "/drivers/",
        json={"yard_id": client.ensure_current_operator_yard_id(), "name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    district = client.post("/districts/", json={"name": "R1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "R1 School", "address": "1 Main St"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assigned_driver.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_id)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    first = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "A", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    second = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "B", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    third = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "C", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    d = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "D", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )

    assert first.status_code in (200, 201)
    assert second.status_code in (200, 201)
    assert third.status_code in (200, 201)
    assert d.status_code in (200, 201)

    r = client.put(f"/stops/{d.json()['id']}/reorder", json={"new_sequence": 2})
    assert r.status_code == 200

    stops = client.get("/stops/", params={"run_id": run_id})
    assert stops.status_code == 200
    names = [s["name"] for s in stops.json()]
    seqs = [s["sequence"] for s in stops.json()]

    assert names == ["A", "D", "B", "C"]
    assert seqs == [1, 2, 3, 4]


def test_stop_delete_normalizes_gap_free(client):
    driver = client.post(
        "/drivers/",
        json={"yard_id": client.ensure_current_operator_yard_id(), "name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    district = client.post("/districts/", json={"name": "R1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "R1 School", "address": "1 Main St"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assigned_driver.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_id)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    first = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "A", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    b = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "B", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )
    third = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": "C", "latitude": 40.0, "longitude": -70.0, "type": "pickup"},
    )

    assert first.status_code in (200, 201)
    assert b.status_code in (200, 201)
    assert third.status_code in (200, 201)

    r = client.delete(f"/stops/{b.json()['id']}")
    assert r.status_code in (200, 204)

    stops = client.get("/stops/", params={"run_id": run_id})
    assert stops.status_code == 200
    names = [s["name"] for s in stops.json()]
    seqs = [s["sequence"] for s in stops.json()]

    assert names == ["A", "C"]
    assert seqs == [1, 2]


def test_run_context_stop_creation_auto_assigns_sequence_and_default_name(client):
    driver = client.post(
        "/drivers/",
        json={"yard_id": client.ensure_current_operator_yard_id(), "name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    district = client.post("/districts/", json={"name": "R1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "R1 School", "address": "1 Main St"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assigned_driver.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_id)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    first = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"type": "pickup"},
    )
    second = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"type": "dropoff"},
    )

    assert first.status_code in (200, 201)
    assert second.status_code in (200, 201)
    assert first.json()["sequence"] == 1
    assert first.json()["name"] == "STOP 1"
    assert second.json()["sequence"] == 2
    assert second.json()["name"] == "STOP 2"


def test_run_context_stop_creation_supports_school_stops(client):
    driver = client.post(
        "/drivers/",
        json={"yard_id": client.ensure_current_operator_yard_id(), "name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    district = client.post("/districts/", json={"name": "R1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Central School", "address": "9 School Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assigned_driver.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_id)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    arrive = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"type": "school_arrive", "school_id": school_id},
    )
    depart = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"type": "SCHOOL_DEPART", "school_id": school_id},
    )

    assert arrive.status_code in (200, 201)
    assert depart.status_code in (200, 201)
    assert arrive.json()["type"] == "SCHOOL_ARRIVE"
    assert arrive.json()["name"] == "Central School"
    assert arrive.json()["school_id"] == school_id
    assert depart.json()["type"] == "SCHOOL_DEPART"
    assert depart.json()["name"] == "Central School"
    assert depart.json()["sequence"] == 2
