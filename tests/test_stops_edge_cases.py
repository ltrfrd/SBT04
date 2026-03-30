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

    r = client.post("/runs/start", json={"route_id": route_id, "run_type": "AM"})
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
