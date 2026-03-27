from tests.conftest import client

def _create_route_with_assignment(client, route_number: str, unit_number: str, driver_id: int):
    r = client.post("/routes/", json={"route_number": route_number, "unit_number": unit_number})
    assert r.status_code in (200, 201)
    route_id = r.json()["id"]

    r = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert r.status_code in (200, 201)
    return route_id


def test_schools_crud(client):
    r = client.post("/schools/", json={"name": "S1", "address": "1 Main St"})
    assert r.status_code in (200, 201)
    school_id = r.json()["id"]

    r = client.get("/schools/")
    assert r.status_code == 200
    assert any(s["id"] == school_id for s in r.json())

    r = client.get(f"/schools/{school_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "S1"

    r = client.put(
        f"/schools/{school_id}",
        json={"name": "S1-updated", "address": "1 Main St"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "S1-updated"

    r = client.delete(f"/schools/{school_id}")
    assert r.status_code in (200, 204)
    r = client.get(f"/schools/{school_id}")
    assert r.status_code == 404


def test_routes_crud(client):
    r = client.post("/drivers/", json={"name": "D1", "email": "d1@x.com", "phone": "1"})
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    route_id = _create_route_with_assignment(client, "R100", "Bus-100", driver_id)

    r = client.get("/routes/")
    assert r.status_code == 200
    assert any(rt["id"] == route_id for rt in r.json())

    r = client.get(f"/routes/{route_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == route_id
    assert "unit_number" in data

    r = client.put(
        f"/routes/{route_id}",
        json={"route_number": "R100", "unit_number": "Bus-101"},
    )
    assert r.status_code == 200
    assert r.json()["unit_number"] == "Bus-101"

    r = client.delete(f"/routes/{route_id}")
    assert r.status_code in (200, 204)
    r = client.get(f"/routes/{route_id}")
    assert r.status_code == 404


def test_students_crud(client):
    r = client.post("/schools/", json={"name": "S1", "address": "1 Main St"})
    assert r.status_code in (200, 201)
    school_id = r.json()["id"]

    r = client.post("/drivers/", json={"name": "D1", "email": "d1@x.com", "phone": "1"})
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    route_id = _create_route_with_assignment(client, "R1", "Bus-01", driver_id)

    r = client.post("/runs/start", json={"route_id": route_id, "run_type": "AM"})
    assert r.status_code in (200, 201)
    run_id = r.json()["id"]

    r = client.post("/stops/", json={"run_id": run_id, "name": "Stop1", "latitude": 1, "longitude": 1, "type": "pickup"})
    assert r.status_code in (200, 201)
    stop_id = r.json()["id"]

    r = client.post("/students/", json={"name": "Kid1", "school_id": school_id, "stop_id": stop_id})
    assert r.status_code in (200, 201)
    student_id = r.json()["id"]

    r = client.get("/students/")
    assert r.status_code == 200
    assert any(s["id"] == student_id for s in r.json())

    r = client.get(f"/students/{student_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Kid1"

    r = client.put(
        f"/students/{student_id}",
        json={"name": "Kid1-updated", "school_id": school_id, "stop_id": stop_id},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Kid1-updated"

    r = client.delete(f"/students/{student_id}")
    assert r.status_code in (200, 204)
    r = client.get(f"/students/{student_id}")
    assert r.status_code == 404

# -----------------------------------------------------------
# - Reject duplicate route_number during route update
# - Keep current route excluded from duplicate detection
# -----------------------------------------------------------
def test_route_update_rejects_duplicate_route_number(client):
    first_route = client.post(                                                       # Create first route
        "/routes/",
        json={"route_number": "R200", "unit_number": "Bus-200"},
    )
    assert first_route.status_code in (200, 201)

    second_route = client.post(                                                      # Create second route
        "/routes/",
        json={"route_number": "R201", "unit_number": "Bus-201"},
    )
    assert second_route.status_code in (200, 201)

    second_route_id = second_route.json()["id"]                                      # Target route to update

    response = client.put(                                                           # Try changing to duplicate number
        f"/routes/{second_route_id}",
        json={"route_number": "R200", "unit_number": "Bus-201"},
    )

    assert response.status_code == 409                                               # Duplicate route number blocked
    assert response.json()["detail"] == "Route number already exists"                # Match API error message