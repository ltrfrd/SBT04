from tests.conftest import client, ensure_route_has_execution_yard
from datetime import date
from sqlalchemy.orm import Session
from app import get_db
from backend.models.associations import StudentRunAssignment
from backend.models.bus import Bus
from backend.models.run import Run
from backend.models.route import Route
from backend.models.student import Student


def _get_client_db_engine(client):
    override = client._wrapped_client.app.dependency_overrides[get_db]
    for cell in override.__closure__ or ():
        candidate = cell.cell_contents
        bind = getattr(candidate, "kw", {}).get("bind")
        if bind is not None:
            return bind
    raise AssertionError("Unable to resolve test database engine from client fixture")


def _get_route_snapshot(client, route_id: int):
    db_engine = _get_client_db_engine(client)
    with Session(db_engine) as db:
        route = db.get(Route, route_id)
        assert route is not None
        return {
            "district_id": route.district_id,
            "route_number": route.route_number,
            "active_bus_id": route.active_bus_id,
            "bus_id": route.bus_id,
        }


def _ensure_route_has_active_bus(client, route_id: int, *, label: str):
    route_snapshot = _get_route_snapshot(client, route_id)
    if route_snapshot["active_bus_id"] or route_snapshot["bus_id"]:
        return

    bus = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), 
            "bus_number": f"{label}-BUS",
            "license_plate": f"{label[:8]}-PLT",
            "capacity": 48,
            "size": "full",
        },
    )
    assert bus.status_code in (200, 201)

    assign = client.post(f"/routes/{route_id}/assign_bus/{bus.json()['id']}")
    assert assign.status_code == 200


def _ensure_active_bus_pretrip(client, route_id: int, run_id: int, *, driver_name: str | None):
    route_snapshot = _get_route_snapshot(client, route_id)
    active_bus_id = route_snapshot["active_bus_id"] or route_snapshot["bus_id"]
    assert active_bus_id is not None

    pretrip = client.get(f"/pretrips/bus/{active_bus_id}/today")
    if pretrip.status_code != 404:
        assert pretrip.status_code == 200
        return

    db_engine = _get_client_db_engine(client)
    with Session(db_engine) as db:
        bus = db.get(Bus, active_bus_id)
        assert bus is not None
        bus_number = bus.bus_number
        license_plate = bus.license_plate

    created = client.post(
        "/pretrips/",
        json={
            "bus_number": bus_number,
            "license_plate": license_plate,
            "driver_name": driver_name or "Prepared Driver",
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:30:00",
            "odometer": 1000 + run_id,
            "inspection_place": "Test Yard",
            "use_type": "school_bus",
            "brakes_checked": True,
            "lights_checked": True,
            "tires_checked": True,
            "emergency_equipment_checked": True,
            "fit_for_duty": "yes",
            "no_defects": True,
            "signature": "test-signature",
            "defects": [],
        },
    )
    assert created.status_code in (200, 201)


def _prepare_run_for_start_attempt(client, route_id: int, run_id: int, *, driver_name: str | None):
    ensure_route_has_execution_yard(client, route_id)
    _ensure_route_has_active_bus(client, route_id, label=f"AUTO-{run_id}")
    _ensure_active_bus_pretrip(client, route_id, run_id, driver_name=driver_name)


def _create_route_with_assignment(client, route_number: str, unit_number: str, driver_id: int):
    district = client.post(
        "/districts/",
        json={"name": f"{route_number.strip()} District"},
    )
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]
    r = client.post(f"/districts/{district_id}/routes", json={"route_number": route_number})
    assert r.status_code in (200, 201)
    route_id = r.json()["id"]

    r = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert r.status_code in (200, 201)
    return route_id


def _create_prepared_started_run(
    client,
    route_id: int,
    run_type: str,
    stop_payload: dict,
    *,
    school_id: int,
    student_name: str,
):
    route_snapshot = _get_route_snapshot(client, route_id)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": route_snapshot["route_number"], "school_ids": [school_id]},
    )
    assert route_update.status_code == 200
    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={
            "run_type": run_type,
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs/{run_id}/stops",
        json=stop_payload,
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students",
        json={"name": student_name, "school_id": school_id},
    )
    assert student.status_code in (200, 201)

    ensure_route_has_execution_yard(client, route_id)
    _prepare_run_for_start_attempt(
        client,
        route_id,
        run_id,
        driver_name=run.json().get("driver_name"),
    )
    started = client.post(f"/runs/start?run_id={run_id}")
    assert started.status_code in (200, 201)
    return started, stop, student


def test_schools_crud(client):
    district = client.post("/districts/", json={"name": "S1 District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]
    r = client.post(f"/districts/{district_id}/schools", json={"name": "S1", "address": "1 Main St"})
    assert r.status_code in (200, 201)
    school_id = r.json()["id"]

    visible_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "S1-VISIBLE-ROUTE", "school_ids": [school_id]},
    )
    assert visible_route.status_code in (200, 201)
    ensure_route_has_execution_yard(client, visible_route.json()["id"])

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
    r = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "D1", "email": "d1@x.com", "phone": "1", "pin": "1234"})
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    route_id = _create_route_with_assignment(client, "R100", "Bus-100", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    ensure_route_has_execution_yard(client, route_id)

    r = client.get("/routes/")
    assert r.status_code == 200
    assert any(rt["id"] == route_id for rt in r.json())

    r = client.get(f"/routes/{route_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == route_id
    assert "unit_number" not in data
    assert "operator" not in data
    assert "capacity" not in data

    r = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "R100"},
    )
    assert r.status_code == 200
    assert "operator" not in r.json()
    assert "capacity" not in r.json()

    r = client.delete(f"/routes/{route_id}")
    assert r.status_code in (200, 204)
    r = client.get(f"/routes/{route_id}")
    assert r.status_code == 404


# -----------------------------------------------------------
# - Route list summary fields
# - Return useful route navigation data without full nesting
# -----------------------------------------------------------
def test_routes_list_returns_summary_fields(client):
    district = client.post("/districts/", json={"name": "Summary District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]
    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Summary School", "address": "10 Summary Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Summary Driver", "email": "summary@x.com", "phone": "1", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "RSUM-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign.status_code in (200, 201)

    run, stop, _student = _create_prepared_started_run(
        client,
        route_id,
        "Morning",
        {"name": "Summary Stop", "latitude": 1, "longitude": 1, "type": "pickup", "sequence": 1},
        school_id=school_id,
        student_name="Summary Student",
    )
    run_id = run.json()["id"]
    
    response = client.get("/routes/")
    assert response.status_code == 200

    route_summary = next(item for item in response.json() if item["id"] == route_id)

    assert route_summary["route_number"] == "RSUM-1"
    assert route_summary["school_ids"] == [school_id]
    assert route_summary["school_names"] == ["Summary School"]
    assert route_summary["schools_count"] == 1
    assert route_summary["active_driver_id"] == driver_id
    assert route_summary["active_driver_name"] == "Summary Driver"
    assert route_summary["primary_driver_id"] == driver_id
    assert route_summary["primary_driver_name"] == "Summary Driver"
    assert route_summary["runs_count"] == 1
    assert route_summary["active_runs_count"] == 1
    assert route_summary["total_stops_count"] == 1
    assert route_summary["total_students_count"] == 1


# -----------------------------------------------------------
# - Route detail nesting
# - Return schools, runs, stops, and students in one route view
# -----------------------------------------------------------
def test_route_detail_returns_nested_route_data(client):
    district = client.post("/districts/", json={"name": "Detail District"})
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]
    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Detail School", "address": "20 Detail Ave"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Detail Driver", "email": "detail@x.com", "phone": "2", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "RDET-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign.status_code in (200, 201)

    run, stop, student = _create_prepared_started_run(
        client,
        route_id,
        "Afternoon",
        {
            "name": "Detail Stop",
            "address": "30 Detail St",
            "planned_time": "14:10:00",
            "latitude": 2,
            "longitude": 2,
            "type": "dropoff",
            "sequence": 1,
        },
        school_id=school_id,
        student_name="Detail Student",
    )
    run_id = run.json()["id"]
    stop_id = stop.json()["id"]
    student_id = student.json()["id"]

    response = client.get(f"/routes/{route_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == route_id
    assert data["route_number"] == "RDET-1"
    assert data["active_driver_id"] == driver_id
    assert data["active_driver_name"] == "Detail Driver"
    assert data["primary_driver_id"] == driver_id
    assert data["primary_driver_name"] == "Detail Driver"
    assert data["schools"] == [{"school_id": school_id, "school_name": "Detail School"}]
    assert len(data["driver_assignments"]) == 1
    assert data["driver_assignments"][0]["driver_id"] == driver_id
    assert data["driver_assignments"][0]["active"] is True
    assert data["driver_assignments"][0]["is_primary"] is True
    assert len(data["runs"]) == 1

    run_detail = data["runs"][0]
    assert run_detail["run_id"] == run_id
    assert run_detail["run_type"] == "AFTERNOON"
    assert run_detail["scheduled_start_time"] == "07:00:00"
    assert run_detail["scheduled_end_time"] == "08:00:00"
    assert run_detail["driver_id"] == driver_id
    assert run_detail["driver_name"] == "Detail Driver"
    assert run_detail["is_planned"] is False
    assert run_detail["is_active"] is True
    assert run_detail["stops"] == [
        {
            "stop_id": stop_id,
            "sequence": 1,
            "type": "DROPOFF",
            "name": "Detail Stop",
            "school_id": None,
            "address": "30 Detail St",
            "planned_time": "14:10:00",
            "student_count": 1,
        }
    ]
    assert run_detail["students"] == [
        {
            "student_id": student_id,
            "student_name": "Detail Student",
            "school_id": school_id,
            "school_name": "Detail School",
            "stop_id": stop_id,
            "stop_sequence": 1,
            "stop_name": "Detail Stop",
        }
    ]


# -----------------------------------------------------------
# - Empty route detail
# - Return clean empty arrays when related data is missing
# -----------------------------------------------------------
def test_route_detail_returns_empty_arrays_for_empty_route(client):
    district = client.post("/districts/", json={"name": "REMPTY District"})
    assert district.status_code in (200, 201)
    route = client.post(f"/districts/{district.json()['id']}/routes", json={"route_number": "REMPTY-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    ensure_route_has_execution_yard(client, route_id)

    response = client.get(f"/routes/{route_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["schools"] == []
    assert data["driver_assignments"] == []
    assert data["runs"] == []


def test_students_crud(client):
    r = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "D1", "email": "d1@x.com", "phone": "1", "pin": "1234"})
    assert r.status_code in (200, 201)
    driver_id = r.json()["id"]

    route_id = _create_route_with_assignment(client, "R1", "Bus-01", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    r = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "S1", "address": "1 Main St"})
    assert r.status_code in (200, 201)
    school_id = r.json()["id"]
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "R1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    r = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert r.status_code in (200, 201)
    run_id = r.json()["id"]

    r = client.post(f"/runs/{run_id}/stops", json={"name": "Stop1", "latitude": 1, "longitude": 1, "type": "pickup"})
    assert r.status_code in (200, 201)
    stop_id = r.json()["id"]

    r = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Kid1", "school_id": school_id},
    )
    assert r.status_code in (200, 201)
    student_id = r.json()["id"]
    ensure_route_has_execution_yard(client, route_id)

    r = client.get("/students/")
    assert r.status_code == 200
    assert any(s["id"] == student_id for s in r.json())

    r = client.get(f"/students/{student_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Kid1"

    r = client.delete(f"/students/{student_id}")
    assert r.status_code in (200, 204)
    r = client.get(f"/students/{student_id}")
    assert r.status_code == 404


# -----------------------------------------------------------
# - Stop-context student create
# - Create student and internal runtime assignment in one call
# -----------------------------------------------------------
def test_create_student_inside_run_stop_context_creates_assignment(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Context Driver", "email": "context@x.com", "phone": "5", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "CTX-1", "BUS-CTX-1", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Context School", "address": "70 Context Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "CTX-1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Context Stop", "address": "71 Context Way"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    response = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Context Student", "grade": "4", "school_id": school_id},
    )
    assert response.status_code == 201

    student = response.json()
    assert student["name"] == "Context Student"
    assert student["school_id"] == school_id
    assert student["school_name"] == "Context School"
    assert student["route_id"] == route_id
    assert student["stop_id"] == stop_id

    assignments = client.get(f"/student-run-assignments/{run_id}")
    assert assignments.status_code == 200
    assert assignments.json() == [
        {
            "id": assignments.json()[0]["id"],
            "student_id": student["id"],
            "run_id": run_id,
            "stop_id": stop_id,
            "actual_pickup_stop_id": None,
            "actual_dropoff_stop_id": None,
        }
    ]


# -----------------------------------------------------------
# - Stop-context student update
# - Update student fields while keeping planning stop alignment
# -----------------------------------------------------------
def test_update_student_inside_run_stop_context_updates_fields_and_repairs_same_run_assignment_drift(client, db_engine):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Context Update Driver", "email": "context.update@x.com", "phone": "5a", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "CTX-UP-1", "BUS-CTX-UP-1", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    primary_school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Primary Context School", "address": "72 Context Way"})
    secondary_school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Secondary Context School", "address": "73 Context Way"})
    assert primary_school.status_code in (200, 201)
    assert secondary_school.status_code in (200, 201)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={
            "route_number": "CTX-UP-1",
            "school_ids": [primary_school.json()["id"], secondary_school.json()["id"]],
        },
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop_one = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Context Update Stop"},
    )
    stop_two = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 2, "type": "pickup", "name": "Drift Stop"},
    )
    assert stop_one.status_code in (200, 201)
    assert stop_two.status_code in (200, 201)

    student = client.post(
        f"/runs/{run_id}/stops/{stop_one.json()['id']}/students",
        json={"name": "Context Update Student", "grade": "4", "school_id": primary_school.json()["id"]},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    with Session(db_engine) as db:
        stored_student = db.get(Student, student_id)
        stored_assignment = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.run_id == run_id)
            .filter(StudentRunAssignment.student_id == student_id)
            .first()
        )
        assert stored_student is not None
        assert stored_assignment is not None

        stored_student.stop_id = stop_two.json()["id"]           # Drift legacy planning pointer inside same run
        stored_assignment.stop_id = stop_two.json()["id"]        # Drift runtime assignment inside same run
        db.commit()

    updated = client.put(
        f"/runs/{run_id}/stops/{stop_one.json()['id']}/students/{student_id}",
        json={"name": "Context Updated Student", "grade": "5", "school_id": secondary_school.json()["id"]},
    )
    assert updated.status_code == 200

    body = updated.json()
    assert body["name"] == "Context Updated Student"
    assert body["grade"] == "5"
    assert body["school_id"] == secondary_school.json()["id"]
    assert body["route_id"] == route_id
    assert body["stop_id"] == stop_one.json()["id"]

    assignments = client.get(f"/student-run-assignments/{run_id}")
    assert assignments.status_code == 200
    assert assignments.json() == [
        {
            "id": assignments.json()[0]["id"],
            "student_id": student_id,
            "run_id": run_id,
            "stop_id": stop_one.json()["id"],
            "actual_pickup_stop_id": None,
            "actual_dropoff_stop_id": None,
        }
    ]


# -----------------------------------------------------------
# - Stop-context bulk student create
# - Create many students and return per-row summary details
# -----------------------------------------------------------
def test_bulk_create_students_inside_run_stop_context_creates_assignments(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Bulk Driver", "email": "bulk@x.com", "phone": "6", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "BULK-1", "BUS-BULK-1", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Bulk School", "address": "80 Bulk Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "BULK-1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Afternoon", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Bulk Stop", "address": "81 Bulk Way"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    response = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students/bulk",
        json={
            "students": [
                {"name": "Bulk Student One", "grade": "3", "school_id": school_id},
                {"name": "Missing School Student", "grade": "2", "school_id": school_id + 999},
                {"name": "Bulk Student Two", "grade": "5", "school_id": school_id},
            ]
        },
    )
    assert response.status_code == 201

    body = response.json()
    assert body["created_count"] == 2
    assert body["skipped_count"] == 1
    assert [student["name"] for student in body["created_students"]] == [
        "Bulk Student One",
        "Bulk Student Two",
    ]
    assert [student["school_name"] for student in body["created_students"]] == ["Bulk School", "Bulk School"]
    assert all(student["route_id"] == route_id for student in body["created_students"])
    assert all(student["stop_id"] == stop_id for student in body["created_students"])
    assert body["errors"] == [
        {
            "index": 1,
            "name": "Missing School Student",
            "detail": "School not found",
        }
    ]

    assignments = client.get(f"/student-run-assignments/{run_id}")
    assert assignments.status_code == 200
    assert len(assignments.json()) == 2
    assert {assignment["stop_id"] for assignment in assignments.json()} == {stop_id}


# -----------------------------------------------------------
# - Stop/run mismatch protection
# - Reject stop-context student create when stop belongs to another run
# -----------------------------------------------------------
def test_create_student_inside_run_stop_context_rejects_stop_mismatch(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Mismatch Driver", "email": "mismatch@x.com", "phone": "7", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "MM-1", "BUS-MM-1", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Mismatch School", "address": "90 Mismatch Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    run_one = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    run_two = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Afternoon", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)

    stop = client.post(
        f"/runs/{run_two.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Other Run Stop"},
    )
    assert stop.status_code in (200, 201)

    response = client.post(
        f"/runs/{run_one.json()['id']}/stops/{stop.json()['id']}/students",
        json={"name": "Mismatch Student", "grade": "6", "school_id": school_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Stop does not belong to run"


def test_create_student_inside_run_stop_context_returns_404_for_missing_run(client):
    district = client.post("/districts/", json={"name": "Missing Run District"})
    assert district.status_code in (200, 201)
    school = client.post(f"/districts/{district.json()['id']}/schools", json={"name": "Missing Run School", "address": "92 Missing Way"})
    assert school.status_code in (200, 201)

    response = client.post(
        "/districts/999999/routes/999999/runs/999999/stops/1/students",
        json={"name": "Missing Run Student", "grade": "6", "school_id": school.json()["id"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] in {"Run not found", "Route not found", "District not found"}


def test_create_student_inside_run_stop_context_returns_404_for_missing_stop(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Missing Stop Driver", "email": "missing.stop@x.com", "phone": "8", "pin": "1234"})
    assert driver.status_code in (200, 201)
    route_id = _create_route_with_assignment(client, "MISS-STOP-1", "BUS-MISS-STOP-1", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Missing Stop School", "address": "93 Missing Way"})
    assert school.status_code in (200, 201)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "MISS-STOP-1", "school_ids": [school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)

    response = client.post(
        f"/runs/{run.json()['id']}/stops/999999/students",
        json={"name": "Missing Stop Student", "grade": "6", "school_id": school.json()["id"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Stop not found"


def test_create_student_inside_run_stop_context_rejects_invalid_school(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Invalid School Driver", "email": "invalid.school@x.com", "phone": "9", "pin": "1234"})
    assert driver.status_code in (200, 201)
    route_id = _create_route_with_assignment(client, "INV-SCH-1", "BUS-INV-SCH-1", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Assigned School", "address": "94 Assigned Way"})
    assert school.status_code in (200, 201)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "INV-SCH-1", "school_ids": [school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Assigned Stop"},
    )
    assert stop.status_code in (200, 201)

    response = client.post(
        f"/runs/{run.json()['id']}/stops/{stop.json()['id']}/students",
        json={"name": "Wrong School Student", "grade": "6", "school_id": school.json()["id"] + 999},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "School not found"


def test_create_student_inside_run_stop_context_rejects_started_run(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Started Run Driver", "email": "started.run@x.com", "phone": "10", "pin": "1234"})
    assert driver.status_code in (200, 201)
    route_id = _create_route_with_assignment(client, "START-CTX-1", "BUS-START-CTX-1", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(f"/districts/{route_snapshot['district_id']}/schools", json={"name": "Started Run School", "address": "95 Started Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "START-CTX-1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Started Stop"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    seed_student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Seed Student", "grade": "4", "school_id": school_id},
    )
    assert seed_student.status_code == 201

    _prepare_run_for_start_attempt(
        client,
        route_id,
        run_id,
        driver_name=run.json().get("driver_name"),
    )
    started = client.post(f"/runs/start?run_id={run_id}")
    assert started.status_code in (200, 201)

    response = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Late Student", "grade": "5", "school_id": school_id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only planned runs can be modified"


def test_update_student_inside_run_stop_context_rejects_wrong_run_or_stop_pairing(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Mismatch Update Driver", "email": "mismatch.update@x.com", "phone": "7a", "pin": "1234"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "MM-UP-1", "BUS-MM-UP-1", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(
        f"/districts/{route_snapshot['district_id']}/schools",
        json={"name": "Mismatch Update School", "address": "91 Mismatch Way"},
    )
    assert school.status_code in (200, 201)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "MM-UP-1", "school_ids": [school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run_one = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    run_two = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Afternoon", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)

    stop_one = client.post(f"/runs/{run_one.json()['id']}/stops", json={"sequence": 1, "type": "pickup", "name": "Stop One"})
    stop_two = client.post(f"/runs/{run_two.json()['id']}/stops", json={"sequence": 1, "type": "pickup", "name": "Stop Two"})
    assert stop_one.status_code in (200, 201)
    assert stop_two.status_code in (200, 201)

    student = client.post(
        f"/runs/{run_one.json()['id']}/stops/{stop_one.json()['id']}/students",
        json={"name": "Mismatch Update Student", "grade": "6", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201

    wrong_run = client.put(
        f"/runs/{run_two.json()['id']}/stops/{stop_one.json()['id']}/students/{student.json()['id']}",
        json={"name": "Wrong Run"},
    )
    assert wrong_run.status_code == 400
    assert wrong_run.json()["detail"] == "Stop does not belong to run"

    wrong_stop = client.put(
        f"/runs/{run_one.json()['id']}/stops/{stop_two.json()['id']}/students/{student.json()['id']}",
        json={"name": "Wrong Stop"},
    )
    assert wrong_stop.status_code == 400
    assert wrong_stop.json()["detail"] == "Stop does not belong to run"


def test_update_student_inside_run_stop_context_updates_existing_assignment_for_run(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Missing Assignment Driver", "email": "missing.assignment@x.com", "phone": "8a", "pin": "1234"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "MISS-ASN-1", "BUS-MISS-ASN-1", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(
        f"/districts/{route_snapshot['district_id']}/schools",
        json={"name": "Missing Assignment School", "address": "95 Missing Way"},
    )
    assert school.status_code in (200, 201)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "MISS-ASN-1", "school_ids": [school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(f"/runs/{run_id}/stops", json={"sequence": 1, "type": "pickup", "name": "Missing Assignment Stop"})
    assert stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students",
        json={
            "name": "Missing Assignment Student",
            "grade": "6",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code in (200, 201)

    response = client.put(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
        json={"name": "Should Fail"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Should Fail"


def test_update_student_inside_run_stop_context_reassigns_student_from_different_route(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Different Route Driver", "email": "different.route@x.com", "phone": "8b", "pin": "1234"})
    assert driver.status_code in (200, 201)

    route_one_id = _create_route_with_assignment(client, "DIFF-ROUTE-1", "BUS-DIFF-1", driver.json()["id"])
    route_two_id = _create_route_with_assignment(client, "DIFF-ROUTE-2", "BUS-DIFF-2", driver.json()["id"])
    route_one_snapshot = _get_route_snapshot(client, route_one_id)
    route_two_snapshot = _get_route_snapshot(client, route_two_id)
    school = client.post(
        f"/districts/{route_one_snapshot['district_id']}/schools",
        json={"name": "Different Route School", "address": "96 Different Way"},
    )
    assert school.status_code in (200, 201)

    route_one_update = client.put(
        f"/districts/{route_one_snapshot['district_id']}/routes/{route_one_id}",
        json={"route_number": "DIFF-ROUTE-1", "school_ids": [school.json()["id"]]},
    )
    route_two_update = client.put(
        f"/districts/{route_two_snapshot['district_id']}/routes/{route_two_id}",
        json={"route_number": "DIFF-ROUTE-2", "school_ids": [school.json()["id"]]},
    )
    assert route_one_update.status_code == 200
    assert route_two_update.status_code == 200

    run = client.post(
        f"/districts/{route_one_snapshot['district_id']}/routes/{route_one_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    other_run = client.post(
        f"/districts/{route_two_snapshot['district_id']}/routes/{route_two_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    assert other_run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(f"/runs/{run_id}/stops", json={"sequence": 1, "type": "pickup", "name": "Different Route Stop"})
    other_stop = client.post(
        f"/runs/{other_run.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Other Route Stop"},
    )
    assert stop.status_code in (200, 201)
    assert other_stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{other_run.json()['id']}/stops/{other_stop.json()['id']}/students",
        json={
            "name": "Different Route Student",
            "grade": "7",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code in (200, 201)

    response = client.put(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
        json={"name": "Should Also Fail"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Should Also Fail"
    assert response.json()["route_id"] == route_one_id
    assert response.json()["stop_id"] == stop.json()["id"]


def test_update_student_inside_run_stop_context_validates_route_school_membership(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "School Update Driver", "email": "school.update@x.com", "phone": "8", "pin": "1234"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "SCH-UP-1", "BUS-SCH-UP-1", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)
    assigned_school = client.post(
        f"/districts/{route_snapshot['district_id']}/schools",
        json={"name": "Assigned Update School", "address": "92 Assigned Way"},
    )
    also_assigned_school = client.post(
        f"/districts/{route_snapshot['district_id']}/schools",
        json={"name": "Also Assigned Update School", "address": "93 Assigned Way"},
    )
    unassigned_school = client.post(
        f"/districts/{route_snapshot['district_id']}/schools",
        json={"name": "Unassigned Update School", "address": "94 Other Way"},
    )
    assert assigned_school.status_code in (200, 201)
    assert also_assigned_school.status_code in (200, 201)
    assert unassigned_school.status_code in (200, 201)
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={
            "route_number": "SCH-UP-1",
            "school_ids": [assigned_school.json()["id"], also_assigned_school.json()["id"]],
        },
    )
    assert route_update.status_code == 200

    run = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(f"/runs/{run_id}/stops", json={"sequence": 1, "type": "pickup", "name": "School Update Stop"})
    assert stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students",
        json={"name": "School Update Student", "school_id": assigned_school.json()["id"]},
    )
    assert student.status_code == 201

    invalid_update = client.put(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
        json={"school_id": unassigned_school.json()["id"]},
    )
    assert invalid_update.status_code == 404
    assert invalid_update.json()["detail"] == "School not found"

    valid_update = client.put(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
        json={"school_id": also_assigned_school.json()["id"]},
    )
    assert valid_update.status_code == 200
    assert valid_update.json()["school_id"] == also_assigned_school.json()["id"]


# -----------------------------------------------------------
# - Student assignment movement
# - Move route/stop pointers through the dedicated assignment endpoint
# -----------------------------------------------------------
def test_update_student_assignment_moves_student_and_synchronizes_runtime_rows(client, db_engine):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Assignment Move Driver", "email": "assignment.move@x.com", "phone": "8c", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    source_route_id = _create_route_with_assignment(client, "ASN-SRC-1", "BUS-ASN-SRC-1", driver_id)
    target_route_id = _create_route_with_assignment(client, "ASN-TGT-1", "BUS-ASN-TGT-1", driver_id)
    source_route_snapshot = _get_route_snapshot(client, source_route_id)
    target_route_snapshot = _get_route_snapshot(client, target_route_id)
    school = client.post(
        f"/districts/{source_route_snapshot['district_id']}/schools",
        json={"name": "Assignment Move School", "address": "97 Assignment Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    source_route_update = client.put(
        f"/districts/{source_route_snapshot['district_id']}/routes/{source_route_id}",
        json={"route_number": "ASN-SRC-1", "school_ids": [school_id]},
    )
    target_route_update = client.put(
        f"/districts/{target_route_snapshot['district_id']}/routes/{target_route_id}",
        json={"route_number": "ASN-TGT-1", "school_ids": [school_id]},
    )
    assert source_route_update.status_code == 200
    assert target_route_update.status_code == 200

    source_run = client.post(
        f"/districts/{source_route_snapshot['district_id']}/routes/{source_route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    target_run = client.post(
        f"/districts/{target_route_snapshot['district_id']}/routes/{target_route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    historical_run = client.post(
        f"/districts/{source_route_snapshot['district_id']}/routes/{source_route_id}/runs",
        json={"run_type": "PM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert source_run.status_code in (200, 201)
    assert target_run.status_code in (200, 201)
    assert historical_run.status_code in (200, 201)

    source_stop = client.post("/stops/", json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Source Stop"})
    target_stop = client.post("/stops/", json={"run_id": target_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Target Stop"})
    historical_stop = client.post("/stops/", json={"run_id": historical_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Historical Stop"})
    assert source_stop.status_code in (200, 201)
    assert target_stop.status_code in (200, 201)
    assert historical_stop.status_code in (200, 201)

    student = client.post(
        f"/runs/{source_run.json()['id']}/stops/{source_stop.json()['id']}/students",
        json={
            "name": "Assignment Move Student",
            "grade": "5",
            "school_id": school_id,
        },
    )
    assert student.status_code == 201
    student_id = student.json()["id"]
    historical_assignment = client.put(
        f"/districts/{source_route_snapshot['district_id']}/routes/{source_route_id}/runs/{historical_run.json()['id']}/stops/{historical_stop.json()['id']}/students/{student_id}",
        json={},
    )
    assert historical_assignment.status_code == 200

    with Session(db_engine) as db:
        historical_run_row = db.get(Run, historical_run.json()["id"])
        assert historical_run_row is not None
        historical_run_row.end_time = historical_run_row.end_time or historical_run_row.start_time
        historical_run_row.is_completed = True                   # Mark one source-route assignment as historical
        db.commit()

    moved = client.put(
        f"/districts/{target_route_snapshot['district_id']}/routes/{target_route_id}/runs/{target_run.json()['id']}/stops/{target_stop.json()['id']}/students/{student_id}",
        json={},
    )
    assert moved.status_code == 200
    assert moved.json()["route_id"] == target_route_id
    assert moved.json()["stop_id"] == target_stop.json()["id"]

    with Session(db_engine) as db:
        stored_student = db.get(Student, student_id)
        assert stored_student is not None
        assert stored_student.route_id == target_route_id
        assert stored_student.stop_id == target_stop.json()["id"]

        assignments = (
            db.query(StudentRunAssignment)
            .filter(StudentRunAssignment.student_id == student_id)
            .all()
        )
        assignments_by_run = {assignment.run_id: assignment for assignment in assignments}

        assert source_run.json()["id"] not in assignments_by_run  # Current incompatible route assignment removed
        assert assignments_by_run[target_run.json()["id"]].stop_id == target_stop.json()["id"]  # Target run synchronized
        assert assignments_by_run[historical_run.json()["id"]].stop_id == historical_stop.json()["id"]  # Historical row preserved


def test_update_student_assignment_rejects_invalid_route_stop_combination(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Invalid Combo Driver", "email": "invalid.combo@x.com", "phone": "8d", "pin": "1234"})
    assert driver.status_code in (200, 201)

    route_one_id = _create_route_with_assignment(client, "ASN-COMB-1", "BUS-ASN-COMB-1", driver.json()["id"])
    route_two_id = _create_route_with_assignment(client, "ASN-COMB-2", "BUS-ASN-COMB-2", driver.json()["id"])
    route_one_snapshot = _get_route_snapshot(client, route_one_id)
    route_two_snapshot = _get_route_snapshot(client, route_two_id)
    school = client.post(
        f"/districts/{route_one_snapshot['district_id']}/schools",
        json={"name": "Invalid Combo School", "address": "98 Combo Way"},
    )
    assert school.status_code in (200, 201)

    route_one_update = client.put(
        f"/districts/{route_one_snapshot['district_id']}/routes/{route_one_id}",
        json={"route_number": "ASN-COMB-1", "school_ids": [school.json()["id"]]},
    )
    route_two_update = client.put(
        f"/districts/{route_two_snapshot['district_id']}/routes/{route_two_id}",
        json={"route_number": "ASN-COMB-2", "school_ids": [school.json()["id"]]},
    )
    assert route_one_update.status_code == 200
    assert route_two_update.status_code == 200

    source_run = client.post(
        f"/districts/{route_one_snapshot['district_id']}/routes/{route_one_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    other_run = client.post(
        f"/districts/{route_two_snapshot['district_id']}/routes/{route_two_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert source_run.status_code in (200, 201)
    assert other_run.status_code in (200, 201)

    source_stop = client.post("/stops/", json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Source Stop"})
    other_stop = client.post("/stops/", json={"run_id": other_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Other Stop"})
    assert source_stop.status_code in (200, 201)
    assert other_stop.status_code in (200, 201)
    student = client.post(
        f"/runs/{source_run.json()['id']}/stops/{source_stop.json()['id']}/students",
        json={
            "name": "Invalid Combo Student",
            "grade": "4",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]
    moved = client.put(
        f"/districts/{route_one_snapshot['district_id']}/routes/{route_one_id}/runs/{source_run.json()['id']}/stops/{other_stop.json()['id']}/students/{student_id}",
        json={},
    )
    assert moved.status_code == 400
    assert moved.json()["detail"] == "Stop does not belong to run"


def test_update_student_assignment_validates_target_route_school_membership(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Assignment School Driver", "email": "assignment.school@x.com", "phone": "8e", "pin": "1234"})
    assert driver.status_code in (200, 201)

    source_route_id = _create_route_with_assignment(client, "ASN-SCH-1", "BUS-ASN-SCH-1", driver.json()["id"])
    target_route_id = _create_route_with_assignment(client, "ASN-SCH-2", "BUS-ASN-SCH-2", driver.json()["id"])
    source_route_snapshot = _get_route_snapshot(client, source_route_id)
    target_route_snapshot = _get_route_snapshot(client, target_route_id)
    school = client.post(
        f"/districts/{source_route_snapshot['district_id']}/schools",
        json={"name": "Compatible Assignment School", "address": "99 School Way"},
    )
    other_school = client.post(
        f"/districts/{target_route_snapshot['district_id']}/schools",
        json={"name": "Other Assignment School", "address": "100 School Way"},
    )
    assert school.status_code in (200, 201)
    assert other_school.status_code in (200, 201)

    source_route_update = client.put(
        f"/districts/{source_route_snapshot['district_id']}/routes/{source_route_id}",
        json={"route_number": "ASN-SCH-1", "school_ids": [school.json()["id"]]},
    )
    target_route_update = client.put(
        f"/districts/{target_route_snapshot['district_id']}/routes/{target_route_id}",
        json={"route_number": "ASN-SCH-2", "school_ids": [other_school.json()["id"]]},
    )
    assert source_route_update.status_code == 200
    assert target_route_update.status_code == 200

    source_run = client.post(
        f"/districts/{source_route_snapshot['district_id']}/routes/{source_route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    target_run = client.post(
        f"/districts/{target_route_snapshot['district_id']}/routes/{target_route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert source_run.status_code in (200, 201)
    assert target_run.status_code in (200, 201)

    source_stop = client.post("/stops/", json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Source Stop"})
    target_stop = client.post("/stops/", json={"run_id": target_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Target Stop"})
    assert source_stop.status_code in (200, 201)
    assert target_stop.status_code in (200, 201)
    student = client.post(
        f"/runs/{source_run.json()['id']}/stops/{source_stop.json()['id']}/students",
        json={
            "name": "Assignment School Student",
            "grade": "5",
            "school_id": school.json()["id"],      # belongs to source route
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]
    moved = client.put(
        f"/districts/{target_route_snapshot['district_id']}/routes/{target_route_id}/runs/{target_run.json()['id']}/stops/{target_stop.json()['id']}/students/{student_id}",
        json={},
    )
    assert moved.status_code == 400
    assert moved.json()["detail"] == "School is not assigned to the run route"

# -----------------------------------------------------------
# - Reject duplicate route_number during route update
# - Keep current route excluded from duplicate detection
# -----------------------------------------------------------
def test_route_update_rejects_duplicate_route_number(client):
    first_district = client.post("/districts/", json={"name": "R200 District"})
    assert first_district.status_code in (200, 201)
    first_route = client.post(
        f"/districts/{first_district.json()['id']}/routes",
        json={"route_number": "R200"},
    )
    assert first_route.status_code in (200, 201)

    second_district = client.post("/districts/", json={"name": "R201 District"})
    assert second_district.status_code in (200, 201)
    second_route = client.post(
        f"/districts/{second_district.json()['id']}/routes",
        json={"route_number": "R201"},
    )
    assert second_route.status_code in (200, 201)

    second_route_id = second_route.json()["id"]                                      # Target route to update

    response = client.put(                                                           # Try changing to duplicate number
        f"/districts/{second_district.json()['id']}/routes/{second_route_id}",
        json={"route_number": "R200"},
    )

    assert response.status_code == 409                                               # Duplicate route number blocked
    assert response.json()["detail"] == "Route number already exists"                # Match API error message


# -----------------------------------------------------------
# - Route create OpenAPI contract
# - Keep route_number required without exposing route vehicle fields
# -----------------------------------------------------------
def test_route_create_openapi_removes_legacy_vehicle_fields(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schemas = response.json()["components"]["schemas"]
    route_create_schema = schemas["RouteCreate"]
    route_out_schema = schemas["RouteOut"]
    route_detail_schema = schemas["RouteDetailOut"]
    run_detail_route_schema = schemas["RunDetailRouteOut"]

    assert route_create_schema["required"] == ["route_number"]
    assert "unit_number" not in route_create_schema["properties"]
    assert "operator" not in route_create_schema["properties"]
    assert "capacity" not in route_create_schema["properties"]
    assert "unit_number" not in route_out_schema["properties"]
    assert "operator" not in route_out_schema["properties"]
    assert "capacity" not in route_out_schema["properties"]
    assert "unit_number" not in route_detail_schema["properties"]
    assert "operator" not in route_detail_schema["properties"]
    assert "capacity" not in route_detail_schema["properties"]
    assert "unit_number" not in run_detail_route_schema["properties"]

    paths = response.json()["paths"]
    assert "post" not in paths["/routes/"]
    assert "put" not in paths["/routes/{route_id}"]

    create_operation = paths["/districts/{district_id}/routes"]["post"]
    assert create_operation["summary"] == "Create district route"
    assert "selected district context" in create_operation["description"]

    update_operation = paths["/districts/{district_id}/routes/{route_id}"]["put"]
    assert update_operation["summary"] == "Update district route"
    assert "path district_id and route_id are authoritative" in update_operation["description"]


# -----------------------------------------------------------
# - Run detail endpoint
# - Return nested route, stop, and student data for one run
# -----------------------------------------------------------
def test_run_detail_returns_nested_run_data(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Run Detail Driver", "email": "run.detail@x.com", "phone": "3", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "RUN-DETAIL-1", "BUS-RUN-DETAIL-1", driver_id)
    route_snapshot = _get_route_snapshot(client, route_id)
    school = client.post(
        f"/districts/{route_snapshot['district_id']}/schools",
        json={"name": "Run Detail School", "address": "50 Run Detail Rd"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]
    route_update = client.put(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}",
        json={"route_number": "RUN-DETAIL-1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    run, stop, student = _create_prepared_started_run(
        client,
        route_id,
        "Morning",
        {"sequence": 1, "type": "pickup", "name": "Run Detail Stop", "address": "51 Run Detail Rd", "planned_time": "07:05:00", "latitude": 1, "longitude": 1},
        school_id=school_id,
        student_name="Run Detail Student",
    )
    run_id = run.json()["id"]
    stop_id = stop.json()["id"]
    student_id = student.json()["id"]

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == run_id
    assert data["route"]["route_id"] == route_id
    assert data["route"]["route_number"] == "RUN-DETAIL-1"
    assert data["driver"]["driver_id"] == driver_id
    assert data["driver"]["driver_name"] == "Run Detail Driver"
    assert data["stops"] == [
        {
            "stop_id": stop_id,
            "sequence": 1,
            "type": "PICKUP",
            "name": "Run Detail Stop",
            "school_id": None,
            "address": "51 Run Detail Rd",
            "planned_time": "07:05:00",
        }
    ]
    assert data["students"] == [
        {
            "student_id": student_id,
            "student_name": "Run Detail Student",
            "school_id": school_id,
            "school_name": "Run Detail School",
            "stop_id": stop_id,
            "stop_sequence": 1,
            "stop_name": "Run Detail Stop",
        }
    ]


# -----------------------------------------------------------
# - Route-scoped run list
# - Require route_id and reject legacy list modes
# -----------------------------------------------------------
def test_runs_list_requires_route_id_and_returns_route_runs_only(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Run List Driver", "email": "run.list@x.com", "phone": "4", "pin": "1234"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_one_id = _create_route_with_assignment(client, "RUN-LIST-1", "BUS-RUN-LIST-1", driver_id)
    route_two_id = _create_route_with_assignment(client, "RUN-LIST-2", "BUS-RUN-LIST-2", driver_id)
    route_one_snapshot = _get_route_snapshot(client, route_one_id)
    route_two_snapshot = _get_route_snapshot(client, route_two_id)

    run_one = client.post(
        f"/districts/{route_one_snapshot['district_id']}/routes/{route_one_id}/runs",
        json={"run_type": "Morning", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    run_two = client.post(
        f"/districts/{route_two_snapshot['district_id']}/routes/{route_two_id}/runs",
        json={"run_type": "Afternoon", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)
    ensure_route_has_execution_yard(client, route_one_id)

    missing_route = client.get("/runs/")
    assert missing_route.status_code == 400
    assert missing_route.json()["detail"] == "route_id is required"

    route_one_runs = client.get(f"/runs/?route_id={route_one_id}")
    assert route_one_runs.status_code == 200
    assert route_one_runs.json() == [
        {
            "run_id": run_one.json()["id"],
            "run_type": "MORNING",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
            "start_time": None,
            "end_time": None,
            "driver_id": driver_id,
            "driver_name": "Run List Driver",
            "is_planned": True,
            "is_active": False,
            "is_completed": False,
            "stops_count": 0,
            "students_count": 0,
        }
    ]

    no_driver_filter = client.get(f"/runs/?driver_id={driver_id}")
    assert no_driver_filter.status_code == 400
    assert no_driver_filter.json()["detail"] == "route_id is required"

    no_run_type_filter = client.get("/runs/?run_type=Morning")
    assert no_run_type_filter.status_code == 400
    assert no_run_type_filter.json()["detail"] == "route_id is required"

    no_active_filter = client.get("/runs/?active=true")
    assert no_active_filter.status_code == 400
    assert no_active_filter.json()["detail"] == "route_id is required"


def test_school_create_read_update_works_without_school_code(client):
    district = client.post("/districts/", json={"name": "North Ridge District"})
    assert district.status_code in (200, 201)
    create = client.post(f"/districts/{district.json()['id']}/schools", json={"name": "North Ridge"})
    assert create.status_code in (200, 201)
    school = create.json()
    assert school["name"] == "North Ridge"
    assert school["address"] is None
    assert "school_code" not in school

    visible_route = client.post(
        f"/districts/{district.json()['id']}/routes",
        json={"route_number": "NORTH-RIDGE-VISIBLE", "school_ids": [school["id"]]},
    )
    assert visible_route.status_code in (200, 201)
    ensure_route_has_execution_yard(client, visible_route.json()["id"])

    read = client.get(f"/schools/{school['id']}")
    assert read.status_code == 200
    assert "school_code" not in read.json()

    update = client.put(
        f"/schools/{school['id']}",
        json={"name": "North Ridge Updated", "address": "11 Ridge Rd", "phone": "555-0101"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "North Ridge Updated"
    assert update.json()["phone"] == "555-0101"
    assert "school_code" not in update.json()


def test_route_context_run_creation_normalizes_and_rejects_duplicates(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Context Run Driver", "email": "ctx.run@test.com", "phone": "9", "pin": "1234"})
    assert driver.status_code in (200, 201)
    route_id = _create_route_with_assignment(client, "  5305  ", "BUS-5305", driver.json()["id"])
    route_snapshot = _get_route_snapshot(client, route_id)

    created = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": " pm ", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert created.status_code == 201
    assert created.json()["route_id"] == route_id
    assert created.json()["run_type"] == "PM"

    duplicate = client.post(
        f"/districts/{route_snapshot['district_id']}/routes/{route_id}/runs",
        json={"run_type": "Pm", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Run label already exists for this route"


def test_run_context_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/runs"]["post"]
    assert path_item["summary"] == "Create run inside district route"
    assert "district route context" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/RouteRunCreate")

    properties = response.json()["components"]["schemas"]["RouteRunCreate"]["properties"]
    assert "route_id" not in properties


def test_legacy_run_create_endpoint_is_removed_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "post" not in response.json()["paths"]["/runs/"]


def test_start_run_endpoint_has_query_param_only_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/runs/start"]["post"]
    assert path_item["summary"] == "Start run"
    assert "Operational runtime endpoint." in path_item["description"]
    assert "existing prepared run" in path_item["description"]
    assert "single active route-driver assignment only" in path_item["description"]
    assert "Primary/default assignment" in path_item["description"]
    assert "does not create stops, students, or StudentRunAssignment rows" in path_item["description"]
    assert "requestBody" not in path_item

    parameters = path_item["parameters"]
    assert len(parameters) == 1
    assert parameters[0]["name"] == "run_id"
    assert parameters[0]["in"] == "query"
    assert parameters[0]["required"] is True


def test_runtime_stop_execution_endpoints_describe_flexible_behavior_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]

    arrive_operation = paths["/runs/{run_id}/arrive_stop"]["post"]
    assert arrive_operation["summary"] == "Arrive at stop"
    assert "Flexible stop execution is allowed" in arrive_operation["description"]
    assert "revisit earlier stops" in arrive_operation["description"]
    assert "optional stop_id may be used" in arrive_operation["description"]

    next_operation = paths["/runs/{run_id}/next_stop"]["post"]
    assert next_operation["summary"] == "Advance to next configured stop (compatibility helper)"
    assert "Compatibility convenience helper" in next_operation["description"]
    assert "does not enforce the overall execution model" in next_operation["description"]
    assert "revisit earlier stops" in next_operation["description"]


def test_stop_context_student_create_rejects_school_not_on_route(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Route School Driver", "email": "route.school@test.com", "phone": "10", "pin": "1234"})
    assert driver.status_code in (200, 201)
    district = client.post("/districts/", json={"name": "Route School District"})
    assert district.status_code in (200, 201)
    valid_school = client.post(
        f"/districts/{district.json()['id']}/schools",
        json={"name": "Assigned School", "address": "1 Assigned Way"},
    )
    other_school = client.post(
        f"/districts/{district.json()['id']}/schools",
        json={"name": "Other School", "address": "2 Other Way"},
    )
    assert valid_school.status_code in (200, 201)
    assert other_school.status_code in (200, 201)
    route = client.post(
        f"/districts/{district.json()['id']}/routes",
        json={"route_number": "ROUTE-SCHOOL-1", "school_ids": [valid_school.json()["id"]]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = client.post(
        f"/districts/{district.json()['id']}/routes/{route_id}/runs",
        json={"run_type": "AM", "scheduled_start_time": "07:00:00", "scheduled_end_time": "08:00:00"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    stop = client.post(f"/runs/{run_id}/stops", json={"type": "pickup"})
    assert stop.status_code == 201

    response = client.post(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students",
        json={"name": "Mismatched School Student", "school_id": other_school.json()["id"]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "School not found"


def test_run_context_stop_update_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/stops/{stop_id}"]["put"]
    assert path_item["summary"] == "Update stop inside district route"
    assert "selected district route context" in path_item["description"]
    assert "path district_id, route_id, and stop_id are authoritative" in path_item["description"]


def test_run_context_stop_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops"]["post"]
    assert path_item["summary"] == "Create stop inside district route run"
    assert "district route-run context" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/RunStopCreate")

    properties = response.json()["components"]["schemas"]["RunStopCreate"]["properties"]
    assert "run_id" not in properties


def test_legacy_stop_create_endpoint_is_removed_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "post" not in response.json()["paths"]["/stops/"]


def test_run_context_student_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students"]["post"]
    assert path_item["summary"] == "Add student to district route run stop"
    assert "district-route-run-stop planning context" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/StopStudentCreate")

    properties = response.json()["components"]["schemas"]["StopStudentCreate"]["properties"]
    assert "route_id" not in properties
    assert "run_id" not in properties
    assert "stop_id" not in properties
    assert "school_id" in properties


def test_legacy_student_create_endpoint_is_removed_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "post" not in response.json()["paths"]["/students/"]


def test_legacy_district_student_create_endpoint_is_removed_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "/districts/{district_id}/students" not in response.json()["paths"]


def test_legacy_route_stop_create_endpoint_is_removed_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "post" not in response.json()["paths"]["/routes/{route_id}/stops"]


def test_reports_school_status_compatibility_endpoint_is_removed_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "/reports/school/student-status" not in response.json()["paths"]


def test_run_context_student_update_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students/{student_id}"]["put"]
    assert path_item["summary"] == "Update student inside district route run stop"
    assert "district-route-run-stop planning context" in path_item["description"]


def test_run_context_student_delete_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students/{student_id}"]["delete"]
    assert path_item["summary"] == "Remove student from district route run stop"
    assert "without deleting the student record entirely" in path_item["description"]


def test_run_context_bulk_student_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students/bulk"]["post"]
    assert path_item["summary"] == "Bulk add students to district route run stop"
    assert "district-route-run-stop planning context" in path_item["description"]


def test_student_assignment_update_endpoint_is_hidden_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]
    assert "/students/{student_id}/assignment" not in paths


def test_student_run_assignment_direct_create_is_hidden_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/student-run-assignments/"]
    assert "post" not in path_item


def test_student_run_assignment_direct_delete_is_hidden_from_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    assert "/student-run-assignments/{assignment_id}" not in response.json()["paths"]


def test_student_delete_entirely_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    operation = response.json()["paths"]["/students/{student_id}"]["delete"]

    assert operation["summary"] == "Delete student entirely"
    assert "Permanently remove the student record from the system" in operation["description"]
    assert "full system-wide student deletion" in operation["description"]
    assert "not the normal run-stop workflow removal action" in operation["description"]


def test_driver_routes_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    operation = response.json()["paths"]["/drivers/{driver_id}/routes"]["get"]
    assert operation["summary"] == "List driver routes"
    assert "entry point for the real operator workflow" in operation["description"]
    assert "selects an assigned route" in operation["description"]
    assert "currently active" in operation["description"]
    assert "not full assignment history" in operation["description"]


def test_route_driver_assignment_endpoints_appear_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]

    assign_operation = paths["/routes/{route_id}/assign_driver/{driver_id}"]["post"]
    assert assign_operation["summary"] == "Assign driver to route"
    assert "primary/default and active/current semantics" in assign_operation["description"]
    assert "first route-driver assignment becomes both primary and active" in assign_operation["description"]
    assert "temporary replacement driver" in assign_operation["description"]
    assert "single active/current assignment only" in assign_operation["description"]

    list_operation = paths["/routes/{route_id}/drivers"]["get"]
    assert list_operation["summary"] == "List route driver assignments"
    assert "currently active for operations" in list_operation["description"]
    assert "primary/default route owner" in list_operation["description"]
    assert "not authoritative for live routing" in list_operation["description"]

    unassign_operation = paths["/routes/{route_id}/unassign_driver/{driver_id}"]["delete"]
    assert unassign_operation["summary"] == "Unassign driver from route"
    assert "temporary replacement" in unassign_operation["description"]
    assert "primary assignment is reactivated automatically" in unassign_operation["description"]
    assert "single active/current assignment only" in unassign_operation["description"]


def test_route_driver_assignment_schemas_expose_primary_fields_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schemas = response.json()["components"]["schemas"]

    route_driver_assignment_properties = schemas["RouteDriverAssignmentOut"]["properties"]
    assert "active" in route_driver_assignment_properties
    assert "is_primary" in route_driver_assignment_properties

    route_out_properties = schemas["RouteOut"]["properties"]
    assert "operator" not in route_out_properties
    assert "capacity" not in route_out_properties
    assert "active_driver_id" in route_out_properties
    assert "active_driver_name" in route_out_properties
    assert "primary_driver_id" in route_out_properties
    assert "primary_driver_name" in route_out_properties

    route_detail_properties = schemas["RouteDetailOut"]["properties"]
    assert "operator" not in route_detail_properties
    assert "capacity" not in route_detail_properties
    assert "active_driver_id" in route_detail_properties
    assert "active_driver_name" in route_detail_properties
    assert "primary_driver_id" in route_detail_properties
    assert "primary_driver_name" in route_detail_properties
    
def test_generic_student_update_endpoint_is_not_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    student_path = response.json()["paths"]["/students/{student_id}"]
    assert "put" not in student_path
