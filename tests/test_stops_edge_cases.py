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
