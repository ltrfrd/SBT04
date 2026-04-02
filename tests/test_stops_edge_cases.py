import pytest


def _setup_run(client):
    r = client.post("/drivers/", json={"name": "D", "email": "d@d.com", "phone": "1"})
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    r = client.post("/routes/", json={"route_number": "R1", "unit_number": "Bus-01"})
    assert r.status_code in (200, 201)
    route_id = r.json()["id"]

    r = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert r.status_code in (200, 201)

    r = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert r.status_code in (200, 201)
    return r.json()["id"]


def test_stop_insert_same_sequence_shifts_and_remains_unique(client):
    run_id = _setup_run(client)

    r = client.post("/stops/", json={
        "run_id": run_id, "name": "A", "latitude": 1, "longitude": 1, "type": "pickup", "sequence": 1
    })
    assert r.status_code in (200, 201)

    r = client.post("/stops/", json={
        "run_id": run_id, "name": "B", "latitude": 2, "longitude": 2, "type": "pickup", "sequence": 1
    })
    assert r.status_code in (200, 201)

    r = client.get("/stops/", params={"run_id": run_id})
    assert r.status_code == 200
    stops = r.json()

    seqs = [s["sequence"] for s in stops]
    names = [s["name"] for s in stops]

    assert seqs == [1, 2]
    assert names == ["B", "A"]
    assert len(seqs) == len(set(seqs))


def test_stop_insert_clamps_sequence(client):
    run_id = _setup_run(client)

    client.post("/stops/", json={"run_id": run_id, "name": "A", "latitude": 1, "longitude": 1, "type": "pickup"})
    client.post("/stops/", json={"run_id": run_id, "name": "B", "latitude": 2, "longitude": 2, "type": "pickup"})

    r = client.post("/stops/", json={"run_id": run_id, "name": "X", "latitude": 3, "longitude": 3, "type": "pickup", "sequence": -50})
    assert r.status_code in (200, 201)

    r = client.get("/stops/", params={"run_id": run_id})
    assert r.status_code == 200
    seqs = [s["sequence"] for s in r.json()]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1


def test_admin_endpoints_require_token(client):
    run_id = _setup_run(client)

    r = client.get(f"/stops/validate/{run_id}")
    assert r.status_code == 403

    r = client.post(f"/stops/normalize/{run_id}")
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("stop_type", "expected_type"),
    [
        ("pickup", "PICKUP"),
        ("PICKUP", "PICKUP"),
        ("PickUp", "PICKUP"),
        ("pick up", "PICKUP"),
        ("pick-up", "PICKUP"),
        ("dropoff", "DROPOFF"),
        ("DROPOFF", "DROPOFF"),
        ("DropOff", "DROPOFF"),
        ("drop off", "DROPOFF"),
        ("drop-off", "DROPOFF"),
        ("school arrive", "SCHOOL_ARRIVE"),
        ("school-depart", "SCHOOL_DEPART"),
    ],
)
def test_stop_create_normalizes_flexible_type_values(client, stop_type, expected_type):
    run_id = _setup_run(client)
    school_id = None

    if "school" in stop_type:
        school = client.post("/schools/", json={"name": "Normalize School", "address": "1 School Way"})
        assert school.status_code in (200, 201)
        school_id = school.json()["id"]

    response = client.post(
        "/stops/",
        json={
            "run_id": run_id,
            "name": f"{stop_type} stop",
            "latitude": 1,
            "longitude": 1,
            "type": stop_type,
            "school_id": school_id,
        },
    )

    assert response.status_code in (200, 201)
    assert response.json()["type"] == expected_type


def test_stop_update_normalizes_flexible_type_values(client):
    run_id = _setup_run(client)

    created = client.post(
        "/stops/",
        json={
            "run_id": run_id,
            "name": "Original Stop",
            "latitude": 1,
            "longitude": 1,
            "type": "pickup",
        },
    )
    assert created.status_code in (200, 201)
    stop_id = created.json()["id"]

    updated = client.put(
        f"/stops/{stop_id}",
        json={"type": "Drop-Off"},
    )

    assert updated.status_code == 200
    assert updated.json()["type"] == "DROPOFF"


def test_run_context_stop_update_works_without_run_id_in_body(client):
    run_id = _setup_run(client)

    created = client.post(
        f"/runs/{run_id}/stops",
        json={
            "type": "pickup",
            "name": "Original Context Stop",
            "address": "100 Old St",
            "planned_time": "07:10:00",
            "latitude": 1,
            "longitude": 1,
        },
    )
    assert created.status_code in (200, 201)
    stop_id = created.json()["id"]

    updated = client.put(
        f"/runs/{run_id}/stops/{stop_id}",
        json={
            "sequence": 1,
            "type": "drop-off",
            "name": "Updated Context Stop",
            "address": "200 New St",
            "planned_time": "07:25:00",
            "latitude": 2,
            "longitude": 2,
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["run_id"] == run_id
    assert body["type"] == "DROPOFF"
    assert body["name"] == "Updated Context Stop"
    assert body["address"] == "200 New St"
    assert body["planned_time"] == "07:25:00"
    assert body["latitude"] == 2
    assert body["longitude"] == 2


def test_run_context_stop_update_rejects_wrong_run_stop_pairing(client):
    run_a_id = _setup_run(client)
    run_a = client.get(f"/runs/{run_a_id}")
    assert run_a.status_code == 200
    route_id = run_a.json()["route"]["route_id"]

    created_run = client.post(
        "/runs/",
        json={"route_id": route_id, "run_type": "PM"},
    )
    assert created_run.status_code in (200, 201)
    run_b_id = created_run.json()["id"]

    created = client.post(
        f"/runs/{run_a_id}/stops",
        json={"type": "pickup", "name": "Run A Stop"},
    )
    assert created.status_code in (200, 201)
    stop_id = created.json()["id"]

    response = client.put(
        f"/runs/{run_b_id}/stops/{stop_id}",
        json={"name": "Wrong Pairing"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Stop does not belong to run"


def test_stop_rejects_invalid_type_value(client):
    run_id = _setup_run(client)

    response = client.post(
        "/stops/",
        json={
            "run_id": run_id,
            "name": "Invalid Stop",
            "latitude": 1,
            "longitude": 1,
            "type": "bus stop",
        },
    )

    assert response.status_code == 422


def test_school_stop_requires_school_id(client):
    run_id = _setup_run(client)

    response = client.post(
        "/runs/{}/stops".format(run_id),
        json={"type": "SCHOOL_ARRIVE"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "school_id is required for school stops"


def test_run_context_school_stop_update_requires_school_id_and_sets_school_name(client):
    run_id = _setup_run(client)

    first_school = client.post("/schools/", json={"name": "First School", "address": "1 School Way"})
    second_school = client.post("/schools/", json={"name": "Second School", "address": "2 School Way"})
    assert first_school.status_code in (200, 201)
    assert second_school.status_code in (200, 201)

    created = client.post(
        f"/runs/{run_id}/stops",
        json={"type": "pickup", "name": "Neighborhood Stop"},
    )
    assert created.status_code in (200, 201)
    stop_id = created.json()["id"]

    missing_school = client.put(
        f"/runs/{run_id}/stops/{stop_id}",
        json={"type": "SCHOOL_ARRIVE"},
    )
    assert missing_school.status_code == 400
    assert missing_school.json()["detail"] == "school_id is required for school stops"

    updated = client.put(
        f"/runs/{run_id}/stops/{stop_id}",
        json={"type": "school_depart", "school_id": second_school.json()["id"]},
    )
    assert updated.status_code == 200
    assert updated.json()["type"] == "SCHOOL_DEPART"
    assert updated.json()["school_id"] == second_school.json()["id"]
    assert updated.json()["name"] == "Second School"
