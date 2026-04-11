def _create_driver(client):
    r = client.post("/drivers/", json={"name": "T", "email": "t@t.com", "phone": "1", "pin": "1234"})
    assert r.status_code in (200, 201)
    return r.json()["id"]


def _create_route(client, driver_id: int):
    r = client.post(
        "/routes/",
        json={"route_number": "R1"},
    )
    assert r.status_code in (200, 201)
    route_id = r.json()["id"]

    r = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert r.status_code in (200, 201)
    return route_id


def _create_run(client, driver_id: int, route_id: int):
    r = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert r.status_code in (200, 201)
    return r.json()["id"]


def _create_stop(client, run_id: int, name: str, sequence=None):
    payload = {
        "run_id": run_id,
        "name": name,
        "latitude": 40.0,
        "longitude": -70.0,
        "type": "pickup",
    }
    if sequence is not None:
        payload["sequence"] = sequence

    r = client.post("/stops/", json=payload)
    assert r.status_code in (200, 201)
    return r.json()


def _list_stops(client, run_id: int):
    r = client.get("/stops/", params={"run_id": run_id})
    assert r.status_code == 200
    return r.json()


def test_stop_append_mode_assigns_next_sequence(client):
    driver_id = _create_driver(client)
    route_id = _create_route(client, driver_id)
    run_id = _create_run(client, driver_id, route_id)

    s1 = _create_stop(client, run_id, "A")
    s2 = _create_stop(client, run_id, "B")

    assert s1["sequence"] == 1
    assert s2["sequence"] == 2


def test_stop_insert_mode_shifts_block(client):
    driver_id = _create_driver(client)
    route_id = _create_route(client, driver_id)
    run_id = _create_run(client, driver_id, route_id)

    _create_stop(client, run_id, "A")
    _create_stop(client, run_id, "B")
    _create_stop(client, run_id, "C")

    _create_stop(client, run_id, "X", sequence=2)

    stops = _list_stops(client, run_id)
    names = [s["name"] for s in stops]
    seqs = [s["sequence"] for s in stops]

    assert names == ["A", "X", "B", "C"]
    assert seqs == [1, 2, 3, 4]


def test_stop_reorder_moves_and_shifts(client):
    driver_id = _create_driver(client)
    route_id = _create_route(client, driver_id)
    run_id = _create_run(client, driver_id, route_id)

    _create_stop(client, run_id, "A")
    _create_stop(client, run_id, "B")
    _create_stop(client, run_id, "C")
    d = _create_stop(client, run_id, "D")

    r = client.put(f"/stops/{d['id']}/reorder", json={"new_sequence": 2})
    assert r.status_code == 200

    stops = _list_stops(client, run_id)
    names = [s["name"] for s in stops]
    seqs = [s["sequence"] for s in stops]

    assert names == ["A", "D", "B", "C"]
    assert seqs == [1, 2, 3, 4]


def test_stop_delete_normalizes_gap_free(client):
    driver_id = _create_driver(client)
    route_id = _create_route(client, driver_id)
    run_id = _create_run(client, driver_id, route_id)

    _create_stop(client, run_id, "A")
    b = _create_stop(client, run_id, "B")
    _create_stop(client, run_id, "C")

    r = client.delete(f"/stops/{b['id']}")
    assert r.status_code in (200, 204)

    stops = _list_stops(client, run_id)
    names = [s["name"] for s in stops]
    seqs = [s["sequence"] for s in stops]

    assert names == ["A", "C"]
    assert seqs == [1, 2]


def test_run_context_stop_creation_auto_assigns_sequence_and_default_name(client):
    driver_id = _create_driver(client)
    route_id = _create_route(client, driver_id)
    run_id = _create_run(client, driver_id, route_id)

    first = client.post(f"/runs/{run_id}/stops", json={"type": "pickup"})
    second = client.post(f"/runs/{run_id}/stops", json={"type": "dropoff"})

    assert first.status_code in (200, 201)
    assert second.status_code in (200, 201)
    assert first.json()["sequence"] == 1
    assert first.json()["name"] == "STOP 1"
    assert second.json()["sequence"] == 2
    assert second.json()["name"] == "STOP 2"


def test_run_context_stop_creation_supports_school_stops(client):
    driver_id = _create_driver(client)
    route_id = _create_route(client, driver_id)
    school = client.post("/schools/", json={"name": "Central School", "address": "9 School Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]
    assign = client.put(f"/routes/{route_id}", json={"route_number": "R1", "school_ids": [school_id]})
    assert assign.status_code == 200
    run_id = _create_run(client, driver_id, route_id)

    arrive = client.post(
        f"/runs/{run_id}/stops",
        json={"type": "school_arrive", "school_id": school_id},
    )
    depart = client.post(
        f"/runs/{run_id}/stops",
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
