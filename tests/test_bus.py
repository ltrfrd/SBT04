from tests.conftest import client, ensure_prepared_run_student


def test_create_bus(client):
    response = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-101",
            "license_plate": "ABC-101",
            "capacity": 48,
            "size": "full",
        },
    )

    assert response.status_code in (200, 201)
    assert response.json() == {
        "id": response.json()["id"],
        "bus_number": "BUS-101",
        "license_plate": "ABC-101",
        "capacity": 48,
        "size": "full",
    }


def test_list_buses(client):
    first = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-201",
            "license_plate": "ABC-201",
            "capacity": 40,
            "size": "mid",
        },
    )
    second = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-202",
            "license_plate": "ABC-202",
            "capacity": 52,
            "size": "full",
        },
    )

    assert first.status_code in (200, 201)
    assert second.status_code in (200, 201)

    response = client.get("/buses/")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": first.json()["id"],
            "bus_number": "BUS-201",
            "license_plate": "ABC-201",
            "capacity": 40,
            "size": "mid",
        },
        {
            "id": second.json()["id"],
            "bus_number": "BUS-202",
            "license_plate": "ABC-202",
            "capacity": 52,
            "size": "full",
        },
    ]


def test_get_bus(client):
    created = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-301",
            "license_plate": "ABC-301",
            "capacity": 36,
            "size": "small",
        },
    )
    assert created.status_code in (200, 201)

    response = client.get(f"/buses/{created.json()['id']}")
    assert response.status_code == 200
    assert response.json() == {
        "id": created.json()["id"],
        "bus_number": "BUS-301",
        "license_plate": "ABC-301",
        "capacity": 36,
        "size": "small",
        "assigned_routes": [],
    }


def test_update_bus(client):
    created = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-401",
            "license_plate": "ABC-401",
            "capacity": 30,
            "size": "mini",
        },
    )
    assert created.status_code in (200, 201)

    response = client.put(
        f"/buses/{created.json()['id']}",
        json={
            "bus_number": "BUS-401A",
            "license_plate": "ABC-401A",
            "capacity": 32,
            "size": "small",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": created.json()["id"],
        "bus_number": "BUS-401A",
        "license_plate": "ABC-401A",
        "capacity": 32,
        "size": "small",
    }


def test_delete_bus(client):
    created = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-501",
            "license_plate": "ABC-501",
            "capacity": 44,
            "size": "full",
        },
    )
    assert created.status_code in (200, 201)

    deleted = client.delete(f"/buses/{created.json()['id']}")
    assert deleted.status_code in (200, 204)

    response = client.get(f"/buses/{created.json()['id']}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Bus not found"


def test_create_bus_rejects_duplicate_bus_number(client):
    first = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-601",
            "license_plate": "ABC-601",
            "capacity": 50,
            "size": "full",
        },
    )
    assert first.status_code in (200, 201)

    duplicate = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-601",
            "license_plate": "ABC-602",
            "capacity": 50,
            "size": "full",
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Bus number already exists"


def test_create_bus_rejects_duplicate_license_plate(client):
    first = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-701",
            "license_plate": "ABC-701",
            "capacity": 24,
            "size": "mini",
        },
    )
    assert first.status_code in (200, 201)

    duplicate = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-702",
            "license_plate": "ABC-701",
            "capacity": 24,
            "size": "mini",
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Bus license plate already exists"


def test_assign_bus_to_route(client):
    route = client.post(
        "/routes/",
        json={"route_number": "BUS-LINK-1"},
    )
    bus = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-801",
            "license_plate": "ABC-801",
            "capacity": 42,
            "size": "full",
        },
    )

    assert route.status_code in (200, 201)
    assert bus.status_code in (200, 201)

    assigned = client.post(f"/routes/{route.json()['id']}/assign_bus/{bus.json()['id']}")
    assert assigned.status_code == 200
    assert assigned.json()["bus_id"] == bus.json()["id"]
    assert "unit_number" not in assigned.json()


def test_unassign_bus_from_route(client):
    route = client.post(
        "/routes/",
        json={"route_number": "BUS-LINK-2"},
    )
    bus = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-802",
            "license_plate": "ABC-802",
            "capacity": 36,
            "size": "mid",
        },
    )

    assert route.status_code in (200, 201)
    assert bus.status_code in (200, 201)

    assigned = client.post(f"/routes/{route.json()['id']}/assign_bus/{bus.json()['id']}")
    assert assigned.status_code == 200

    unassigned = client.delete(f"/routes/{route.json()['id']}/unassign_bus")
    assert unassigned.status_code == 200
    assert unassigned.json()["bus_id"] is None
    assert "unit_number" not in unassigned.json()


def test_route_detail_and_list_show_bus_id_when_assigned(client):
    route = client.post(
        "/routes/",
        json={"route_number": "BUS-LINK-3"},
    )
    bus = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-803",
            "license_plate": "ABC-803",
            "capacity": 54,
            "size": "full",
        },
    )

    assert route.status_code in (200, 201)
    assert bus.status_code in (200, 201)

    assigned = client.post(f"/routes/{route.json()['id']}/assign_bus/{bus.json()['id']}")
    assert assigned.status_code == 200

    detail = client.get(f"/routes/{route.json()['id']}")
    listing = client.get("/routes/")

    assert detail.status_code == 200
    assert listing.status_code == 200
    assert detail.json()["bus_id"] == bus.json()["id"]

    route_summary = next(item for item in listing.json() if item["id"] == route.json()["id"])
    assert route_summary["bus_id"] == bus.json()["id"]


def test_assign_bus_to_route_rejects_missing_route_or_bus(client):
    bus = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-804",
            "license_plate": "ABC-804",
            "capacity": 28,
            "size": "mini",
        },
    )
    route = client.post(
        "/routes/",
        json={"route_number": "BUS-LINK-4"},
    )

    assert bus.status_code in (200, 201)
    assert route.status_code in (200, 201)

    missing_route = client.post(f"/routes/999999/assign_bus/{bus.json()['id']}")
    missing_bus = client.post(f"/routes/{route.json()['id']}/assign_bus/999999")

    assert missing_route.status_code == 404
    assert missing_route.json()["detail"] == "Route not found"
    assert missing_bus.status_code == 404
    assert missing_bus.json()["detail"] == "Bus not found"


def test_unassign_bus_from_route_rejects_missing_route(client):
    response = client.delete("/routes/999999/unassign_bus")

    assert response.status_code == 404
    assert response.json()["detail"] == "Route not found"


def test_bus_detail_returns_empty_assigned_routes_when_unassigned(client):
    created = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-901",
            "license_plate": "ABC-901",
            "capacity": 44,
            "size": "full",
        },
    )
    assert created.status_code in (200, 201)

    response = client.get(f"/buses/{created.json()['id']}")
    assert response.status_code == 200
    assert response.json()["assigned_routes"] == []


def test_bus_detail_returns_assigned_route_with_nested_context(client):
    school = client.post(
        "/schools/",
        json={"name": "Bus Detail School", "address": "901 Bus Detail Rd"},
    )
    driver = client.post(
        "/drivers/",
        json={"name": "Bus Detail Driver", "email": "bus.detail.driver@test.com", "phone": "901"},
    )
    route = client.post(
        "/routes/",
        json={"route_number": "BUS-DETAIL-ROUTE", "school_ids": [school.json()["id"]]},
    )
    bus = client.post(
        "/buses/",
        json={
            "bus_number": "BUS-902",
            "license_plate": "ABC-902",
            "capacity": 48,
            "size": "full",
        },
    )

    assert school.status_code in (200, 201)
    assert driver.status_code in (200, 201)
    assert route.status_code in (200, 201)
    assert bus.status_code in (200, 201)

    assign_driver = client.post(f"/routes/{route.json()['id']}/assign_driver/{driver.json()['id']}")
    assign_bus = client.post(f"/routes/{route.json()['id']}/assign_bus/{bus.json()['id']}")
    assert assign_driver.status_code in (200, 201)
    assert assign_bus.status_code == 200

    run = client.post(f"/routes/{route.json()['id']}/runs", json={"run_type": "Morning"})
    assert run.status_code in (200, 201)

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={
            "name": "Bus Detail Stop",
            "address": "902 Bus Detail Rd",
            "planned_time": "07:15:00",
            "latitude": 39.1,
            "longitude": -104.9,
            "type": "pickup",
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)

    student = ensure_prepared_run_student(client, run.json()["id"])
    start = client.post(f"/runs/start?run_id={run.json()['id']}")
    assert start.status_code in (200, 201)

    response = client.get(f"/buses/{bus.json()['id']}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == bus.json()["id"]
    assert data["bus_number"] == "BUS-902"
    assert len(data["assigned_routes"]) == 1

    assigned_route = data["assigned_routes"][0]
    assert assigned_route["id"] == route.json()["id"]
    assert assigned_route["route_number"] == "BUS-DETAIL-ROUTE"
    assert assigned_route["bus_id"] == bus.json()["id"]
    assert assigned_route["schools"] == [
        {"school_id": school.json()["id"], "school_name": "Bus Detail School"}
    ]
    assert assigned_route["active_driver_id"] == driver.json()["id"]
    assert assigned_route["active_driver_name"] == "Bus Detail Driver"
    assert len(assigned_route["driver_assignments"]) == 1
    assert assigned_route["driver_assignments"][0]["driver_id"] == driver.json()["id"]
    assert len(assigned_route["runs"]) == 1

    run_detail = assigned_route["runs"][0]
    assert run_detail["run_id"] == run.json()["id"]
    assert run_detail["run_type"] == "MORNING"
    assert run_detail["driver_id"] == driver.json()["id"]
    assert run_detail["driver_name"] == "Bus Detail Driver"
    assert run_detail["stops"] == [
        {
            "stop_id": stop.json()["id"],
            "sequence": 1,
            "type": "PICKUP",
            "name": "Bus Detail Stop",
            "school_id": None,
            "address": "902 Bus Detail Rd",
            "planned_time": "07:15:00",
            "student_count": 1,
        }
    ]
    assert run_detail["students"] == [
        {
            "student_id": student["id"],
            "student_name": student["name"],
            "school_id": school.json()["id"],
            "school_name": "Bus Detail School",
            "stop_id": stop.json()["id"],
            "stop_sequence": 1,
            "stop_name": "Bus Detail Stop",
        }
    ]


def test_bus_detail_missing_bus_returns_404(client):
    response = client.get("/buses/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Bus not found"
