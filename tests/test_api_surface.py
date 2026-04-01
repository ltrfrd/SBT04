from tests.conftest import client
from sqlalchemy.orm import Session
from backend.models.associations import StudentRunAssignment
from backend.models.run import Run
from backend.models.student import Student


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


# -----------------------------------------------------------
# - Route list summary fields
# - Return useful route navigation data without full nesting
# -----------------------------------------------------------
def test_routes_list_returns_summary_fields(client):
    school = client.post(
        "/schools/",
        json={"name": "Summary School", "address": "10 Summary Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Summary Driver", "email": "summary@x.com", "phone": "1"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "RSUM-1", "unit_number": "BUS-SUM-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign.status_code in (200, 201)

    run = client.post("/runs/start", json={"route_id": route_id, "run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"name": "Summary Stop", "latitude": 1, "longitude": 1, "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Summary Student", "school_id": school_id},
    )
    assert student.status_code in (200, 201)

    response = client.get("/routes/")
    assert response.status_code == 200

    route_summary = next(item for item in response.json() if item["id"] == route_id)

    assert route_summary["route_number"] == "RSUM-1"
    assert route_summary["unit_number"] == "BUS-SUM-1"
    assert route_summary["school_ids"] == [school_id]
    assert route_summary["school_names"] == ["Summary School"]
    assert route_summary["schools_count"] == 1
    assert route_summary["active_driver_id"] == driver_id
    assert route_summary["active_driver_name"] == "Summary Driver"
    assert route_summary["runs_count"] == 1
    assert route_summary["active_runs_count"] == 1
    assert route_summary["total_stops_count"] == 1
    assert route_summary["total_students_count"] == 1


# -----------------------------------------------------------
# - Route detail nesting
# - Return schools, runs, stops, and students in one route view
# -----------------------------------------------------------
def test_route_detail_returns_nested_route_data(client):
    school = client.post(
        "/schools/",
        json={"name": "Detail School", "address": "20 Detail Ave"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Detail Driver", "email": "detail@x.com", "phone": "2"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "RDET-1", "unit_number": "BUS-DET-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign.status_code in (200, 201)

    run = client.post("/runs/start", json={"route_id": route_id, "run_type": "Afternoon"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={
            "name": "Detail Stop",
            "address": "30 Detail St",
            "planned_time": "14:10:00",
            "latitude": 2,
            "longitude": 2,
            "type": "dropoff",
            "sequence": 1,
        },
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Detail Student", "school_id": school_id},
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    response = client.get(f"/routes/{route_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == route_id
    assert data["route_number"] == "RDET-1"
    assert data["unit_number"] == "BUS-DET-1"
    assert data["active_driver_id"] == driver_id
    assert data["active_driver_name"] == "Detail Driver"
    assert data["schools"] == [{"school_id": school_id, "school_name": "Detail School"}]
    assert len(data["driver_assignments"]) == 1
    assert data["driver_assignments"][0]["driver_id"] == driver_id
    assert len(data["runs"]) == 1

    run_detail = data["runs"][0]
    assert run_detail["run_id"] == run_id
    assert run_detail["run_type"] == "AFTERNOON"
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
    route = client.post("/routes/", json={"route_number": "REMPTY-1", "unit_number": "BUS-EMPTY-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    response = client.get(f"/routes/{route_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["schools"] == []
    assert data["driver_assignments"] == []
    assert data["runs"] == []


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

    r = client.post(f"/runs/{run_id}/stops", json={"name": "Stop1", "latitude": 1, "longitude": 1, "type": "pickup"})
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

    r = client.delete(f"/students/{student_id}")
    assert r.status_code in (200, 204)
    r = client.get(f"/students/{student_id}")
    assert r.status_code == 404


# -----------------------------------------------------------
# - Stop-context student create
# - Create student and internal runtime assignment in one call
# -----------------------------------------------------------
def test_create_student_inside_run_stop_context_creates_assignment(client):
    school = client.post("/schools/", json={"name": "Context School", "address": "70 Context Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Context Driver", "email": "context@x.com", "phone": "5"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "CTX-1", "BUS-CTX-1", driver_id)
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "CTX-1", "unit_number": "BUS-CTX-1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
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
    primary_school = client.post("/schools/", json={"name": "Primary Context School", "address": "72 Context Way"})
    secondary_school = client.post("/schools/", json={"name": "Secondary Context School", "address": "73 Context Way"})
    assert primary_school.status_code in (200, 201)
    assert secondary_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Context Update Driver", "email": "context.update@x.com", "phone": "5a"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "CTX-UP-1", "BUS-CTX-UP-1", driver_id)
    route_update = client.put(
        f"/routes/{route_id}",
        json={
            "route_number": "CTX-UP-1",
            "unit_number": "BUS-CTX-UP-1",
            "school_ids": [primary_school.json()["id"], secondary_school.json()["id"]],
        },
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
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
    school = client.post("/schools/", json={"name": "Bulk School", "address": "80 Bulk Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Bulk Driver", "email": "bulk@x.com", "phone": "6"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "BULK-1", "BUS-BULK-1", driver_id)
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "BULK-1", "unit_number": "BUS-BULK-1", "school_ids": [school_id]},
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Afternoon"})
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
    school = client.post("/schools/", json={"name": "Mismatch School", "address": "90 Mismatch Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Mismatch Driver", "email": "mismatch@x.com", "phone": "7"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_id = _create_route_with_assignment(client, "MM-1", "BUS-MM-1", driver_id)

    run_one = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
    run_two = client.post(f"/routes/{route_id}/runs", json={"run_type": "Afternoon"})
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


def test_update_student_inside_run_stop_context_rejects_wrong_run_or_stop_pairing(client):
    school = client.post("/schools/", json={"name": "Mismatch Update School", "address": "91 Mismatch Way"})
    assert school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Mismatch Update Driver", "email": "mismatch.update@x.com", "phone": "7a"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "MM-UP-1", "BUS-MM-UP-1", driver.json()["id"])
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "MM-UP-1", "unit_number": "BUS-MM-UP-1", "school_ids": [school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run_one = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
    run_two = client.post(f"/routes/{route_id}/runs", json={"run_type": "Afternoon"})
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


def test_update_student_inside_run_stop_context_rejects_missing_assignment_for_run(client):
    school = client.post("/schools/", json={"name": "Missing Assignment School", "address": "95 Missing Way"})
    assert school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Missing Assignment Driver", "email": "missing.assignment@x.com", "phone": "8a"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "MISS-ASN-1", "BUS-MISS-ASN-1", driver.json()["id"])
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "MISS-ASN-1", "unit_number": "BUS-MISS-ASN-1", "school_ids": [school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(f"/runs/{run_id}/stops", json={"sequence": 1, "type": "pickup", "name": "Missing Assignment Stop"})
    assert stop.status_code in (200, 201)

    student = client.post(
        "/students/",
        json={
            "name": "Missing Assignment Student",
            "grade": "6",
            "school_id": school.json()["id"],
            "route_id": route_id,
            "stop_id": stop.json()["id"],
        },
    )
    assert student.status_code in (200, 201)

    response = client.put(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
        json={"name": "Should Fail"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Student is not assigned to run"


def test_update_student_inside_run_stop_context_rejects_student_from_different_route(client):
    school = client.post("/schools/", json={"name": "Different Route School", "address": "96 Different Way"})
    assert school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Different Route Driver", "email": "different.route@x.com", "phone": "8b"})
    assert driver.status_code in (200, 201)

    route_one_id = _create_route_with_assignment(client, "DIFF-ROUTE-1", "BUS-DIFF-1", driver.json()["id"])
    route_two_id = _create_route_with_assignment(client, "DIFF-ROUTE-2", "BUS-DIFF-2", driver.json()["id"])

    route_one_update = client.put(
        f"/routes/{route_one_id}",
        json={"route_number": "DIFF-ROUTE-1", "unit_number": "BUS-DIFF-1", "school_ids": [school.json()["id"]]},
    )
    route_two_update = client.put(
        f"/routes/{route_two_id}",
        json={"route_number": "DIFF-ROUTE-2", "unit_number": "BUS-DIFF-2", "school_ids": [school.json()["id"]]},
    )
    assert route_one_update.status_code == 200
    assert route_two_update.status_code == 200

    run = client.post(f"/routes/{route_one_id}/runs", json={"run_type": "AM"})
    other_run = client.post(f"/routes/{route_two_id}/runs", json={"run_type": "AM"})
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
        "/students/",
        json={
            "name": "Different Route Student",
            "grade": "7",
            "school_id": school.json()["id"],
            "route_id": route_two_id,
            "stop_id": other_stop.json()["id"],
        },
    )
    assert student.status_code in (200, 201)

    response = client.put(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students/{student.json()['id']}",
        json={"name": "Should Also Fail"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Student does not belong to run route"


def test_create_student_compatibility_rejects_route_stop_mismatch(client):
    school = client.post("/schools/", json={"name": "Compatibility School", "address": "101 Compatibility Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]
    driver = client.post(
        "/drivers/",
        json={
            "name": "Compatibility Driver",
            "email": "compatibility.driver@test.com",
            "phone": "8c1",
        },
    )
    assert driver.status_code in (200, 201)

    route_one_id = _create_route_with_assignment(client, "COMP-STU-1", "BUS-COMP-STU-1", driver.json()["id"])
    route_two_id = _create_route_with_assignment(client, "COMP-STU-2", "BUS-COMP-STU-2", driver.json()["id"])

    route_one_update = client.put(
        f"/routes/{route_one_id}",
        json={"route_number": "COMP-STU-1", "unit_number": "BUS-COMP-STU-1", "school_ids": [school_id]},
    )
    route_two_update = client.put(
        f"/routes/{route_two_id}",
        json={"route_number": "COMP-STU-2", "unit_number": "BUS-COMP-STU-2", "school_ids": [school_id]},
    )
    assert route_one_update.status_code == 200
    assert route_two_update.status_code == 200

    run_one = client.post(f"/routes/{route_one_id}/runs", json={"run_type": "AM"})
    run_two = client.post(f"/routes/{route_two_id}/runs", json={"run_type": "AM"})
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)

    stop_one = client.post(
        f"/runs/{run_one.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Matched Stop"},
    )
    stop_two = client.post(
        f"/runs/{run_two.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Mismatched Stop"},
    )
    assert stop_one.status_code in (200, 201)
    assert stop_two.status_code in (200, 201)

    valid_response = client.post(
        "/students/",
        json={
            "name": "Matched Compatibility Student",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_one_id,
            "stop_id": stop_one.json()["id"],
        },
    )
    print(valid_response.status_code, valid_response.json())
    assert valid_response.status_code in (200, 201)
    response = client.post(
        "/students/",
        json={
            "name": "Mismatched Compatibility Student",
            "grade": "5",
            "school_id": school_id,
            "route_id": route_one_id,
            "stop_id": stop_two.json()["id"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Stop does not belong to route"


def test_create_student_compatibility_allows_school_not_assigned_to_provided_route(client):
    assigned_school = client.post("/schools/", json={"name": "Assigned Compatibility School", "address": "102 Assigned Way"})
    other_school = client.post("/schools/", json={"name": "Other Compatibility School", "address": "103 Other Way"})
    assert assigned_school.status_code in (200, 201)
    assert other_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Compatibility Route Driver", "email": "compat.route@test.com", "phone": "8c2"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "COMP-SCH-1", "BUS-COMP-SCH-1", driver.json()["id"])
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "COMP-SCH-1", "unit_number": "BUS-COMP-SCH-1", "school_ids": [assigned_school.json()["id"]]},
    )
    assert route_update.status_code == 200

    response = client.post(
        "/students/",
        json={
            "name": "Wrong Route School Student",
            "grade": "4",
            "school_id": other_school.json()["id"],
            "route_id": route_id,
        },
    )
    assert response.status_code == 201
    assert response.json()["school_id"] == other_school.json()["id"]
    assert response.json()["route_id"] == route_id


def test_create_student_compatibility_allows_school_not_assigned_to_stop_route(client):
    assigned_school = client.post("/schools/", json={"name": "Stop Assigned School", "address": "104 Stop Assigned Way"})
    other_school = client.post("/schools/", json={"name": "Stop Other School", "address": "105 Stop Other Way"})
    assert assigned_school.status_code in (200, 201)
    assert other_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Compatibility Stop Driver", "email": "compat.stop@test.com", "phone": "8c3"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "COMP-STOP-1", "BUS-COMP-STOP-1", driver.json()["id"])
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "COMP-STOP-1", "unit_number": "BUS-COMP-STOP-1", "school_ids": [assigned_school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Compatibility Stop"},
    )
    assert stop.status_code in (200, 201)

    response = client.post(
        "/students/",
        json={
            "name": "Wrong Stop School Student",
            "grade": "4",
            "school_id": other_school.json()["id"],
            "stop_id": stop.json()["id"],
        },
    )
    assert response.status_code == 201
    assert response.json()["school_id"] == other_school.json()["id"]
    assert response.json()["stop_id"] == stop.json()["id"]


def test_create_student_compatibility_allows_safe_combinations(client):
    standalone_school = client.post("/schools/", json={"name": "Standalone School", "address": "106 Standalone Way"})
    route_school = client.post("/schools/", json={"name": "Route School", "address": "107 Route Way"})
    assert standalone_school.status_code in (200, 201)
    assert route_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Compatibility Safe Driver", "email": "compat.safe@test.com", "phone": "8c4"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "COMP-SAFE-1", "BUS-COMP-SAFE-1", driver.json()["id"])
    route_update = client.put(
        f"/routes/{route_id}",
        json={"route_number": "COMP-SAFE-1", "unit_number": "BUS-COMP-SAFE-1", "school_ids": [route_school.json()["id"]]},
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code in (200, 201)

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Compatibility Safe Stop"},
    )
    assert stop.status_code in (200, 201)

    school_only = client.post(
        "/students/",
        json={"name": "School Only Student", "grade": "3", "school_id": standalone_school.json()["id"]},
    )
    route_only = client.post(
        "/students/",
        json={
            "name": "Route Only Student",
            "grade": "4",
            "school_id": route_school.json()["id"],
            "route_id": route_id,
        },
    )
    stop_only = client.post(
        "/students/",
        json={
            "name": "Stop Only Student",
            "grade": "5",
            "school_id": route_school.json()["id"],
            "stop_id": stop.json()["id"],
        },
    )
    aligned = client.post(
        "/students/",
        json={
            "name": "Aligned Student",
            "grade": "6",
            "school_id": route_school.json()["id"],
            "route_id": route_id,
            "stop_id": stop.json()["id"],
        },
    )

    assert school_only.status_code == 201
    assert route_only.status_code == 201
    assert stop_only.status_code == 201
    assert aligned.status_code == 201

    assert school_only.json()["route_id"] is None
    assert school_only.json()["stop_id"] is None
    assert route_only.json()["route_id"] == route_id
    assert route_only.json()["stop_id"] is None
    assert stop_only.json()["route_id"] is None
    assert stop_only.json()["stop_id"] == stop.json()["id"]
    assert aligned.json()["route_id"] == route_id
    assert aligned.json()["stop_id"] == stop.json()["id"]


def test_update_student_inside_run_stop_context_validates_route_school_membership(client):
    assigned_school = client.post("/schools/", json={"name": "Assigned Update School", "address": "92 Assigned Way"})
    also_assigned_school = client.post("/schools/", json={"name": "Also Assigned Update School", "address": "93 Assigned Way"})
    unassigned_school = client.post("/schools/", json={"name": "Unassigned Update School", "address": "94 Other Way"})
    assert assigned_school.status_code in (200, 201)
    assert also_assigned_school.status_code in (200, 201)
    assert unassigned_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "School Update Driver", "email": "school.update@x.com", "phone": "8"})
    assert driver.status_code in (200, 201)

    route_id = _create_route_with_assignment(client, "SCH-UP-1", "BUS-SCH-UP-1", driver.json()["id"])
    route_update = client.put(
        f"/routes/{route_id}",
        json={
            "route_number": "SCH-UP-1",
            "unit_number": "BUS-SCH-UP-1",
            "school_ids": [assigned_school.json()["id"], also_assigned_school.json()["id"]],
        },
    )
    assert route_update.status_code == 200

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
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
    assert invalid_update.status_code == 400
    assert invalid_update.json()["detail"] == "School is not assigned to the run route"

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
    school = client.post("/schools/", json={"name": "Assignment Move School", "address": "97 Assignment Way"})
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Assignment Move Driver", "email": "assignment.move@x.com", "phone": "8c"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    source_route_id = _create_route_with_assignment(client, "ASN-SRC-1", "BUS-ASN-SRC-1", driver_id)
    target_route_id = _create_route_with_assignment(client, "ASN-TGT-1", "BUS-ASN-TGT-1", driver_id)

    source_route_update = client.put(
        f"/routes/{source_route_id}",
        json={"route_number": "ASN-SRC-1", "unit_number": "BUS-ASN-SRC-1", "school_ids": [school_id]},
    )
    target_route_update = client.put(
        f"/routes/{target_route_id}",
        json={"route_number": "ASN-TGT-1", "unit_number": "BUS-ASN-TGT-1", "school_ids": [school_id]},
    )
    assert source_route_update.status_code == 200
    assert target_route_update.status_code == 200

    source_run = client.post(f"/routes/{source_route_id}/runs", json={"run_type": "AM"})
    target_run = client.post(f"/routes/{target_route_id}/runs", json={"run_type": "AM"})
    historical_run = client.post(f"/routes/{source_route_id}/runs", json={"run_type": "PM"})
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
        "/students/",
        json={
            "name": "Assignment Move Student",
            "grade": "5",
            "school_id": school_id,
            "route_id": source_route_id,
            "stop_id": source_stop.json()["id"],
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    current_assignment = client.post(
        "/student-run-assignments/",
        json={"student_id": student_id, "run_id": source_run.json()["id"], "stop_id": source_stop.json()["id"]},
    )
    historical_assignment = client.post(
        "/student-run-assignments/",
        json={"student_id": student_id, "run_id": historical_run.json()["id"], "stop_id": historical_stop.json()["id"]},
    )
    assert current_assignment.status_code == 201
    assert historical_assignment.status_code == 201

    with Session(db_engine) as db:
        historical_run_row = db.get(Run, historical_run.json()["id"])
        assert historical_run_row is not None
        historical_run_row.end_time = historical_run_row.end_time or historical_run_row.start_time
        historical_run_row.is_completed = True                   # Mark one source-route assignment as historical
        db.commit()

    moved = client.put(
        f"/students/{student_id}/assignment",
        json={
            "route_id": target_route_id,
            "run_id": target_run.json()["id"],
            "stop_id": target_stop.json()["id"],
        },
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
    school = client.post("/schools/", json={"name": "Invalid Combo School", "address": "98 Combo Way"})
    assert school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Invalid Combo Driver", "email": "invalid.combo@x.com", "phone": "8d"})
    assert driver.status_code in (200, 201)

    route_one_id = _create_route_with_assignment(client, "ASN-COMB-1", "BUS-ASN-COMB-1", driver.json()["id"])
    route_two_id = _create_route_with_assignment(client, "ASN-COMB-2", "BUS-ASN-COMB-2", driver.json()["id"])

    route_one_update = client.put(
        f"/routes/{route_one_id}",
        json={"route_number": "ASN-COMB-1", "unit_number": "BUS-ASN-COMB-1", "school_ids": [school.json()["id"]]},
    )
    route_two_update = client.put(
        f"/routes/{route_two_id}",
        json={"route_number": "ASN-COMB-2", "unit_number": "BUS-ASN-COMB-2", "school_ids": [school.json()["id"]]},
    )
    assert route_one_update.status_code == 200
    assert route_two_update.status_code == 200

    source_run = client.post(f"/routes/{route_one_id}/runs", json={"run_type": "AM"})
    other_run = client.post(f"/routes/{route_two_id}/runs", json={"run_type": "AM"})
    assert source_run.status_code in (200, 201)
    assert other_run.status_code in (200, 201)

    source_stop = client.post("/stops/", json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Source Stop"})
    other_stop = client.post("/stops/", json={"run_id": other_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Other Stop"})
    assert source_stop.status_code in (200, 201)
    assert other_stop.status_code in (200, 201)
    student = client.post(
        "/students/",
        json={
            "name": "Invalid Combo Student",
            "grade": "4",
            "school_id": school.json()["id"],
            "route_id": route_one_id,
            "stop_id": source_stop.json()["id"],
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    moved = client.put(
        f"/students/{student_id}/assignment",
        json={
            "route_id": route_one_id,
            "run_id": source_run.json()["id"],   # correct run
            "stop_id": other_stop.json()["id"],  # ❗ wrong stop (from other route)
        },
    )
    assert moved.status_code == 400
    assert moved.json()["detail"] == "Stop does not belong to run"


def test_update_student_assignment_validates_target_route_school_membership(client):
    school = client.post("/schools/", json={"name": "Compatible Assignment School", "address": "99 School Way"})
    other_school = client.post("/schools/", json={"name": "Other Assignment School", "address": "100 School Way"})
    assert school.status_code in (200, 201)
    assert other_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Assignment School Driver", "email": "assignment.school@x.com", "phone": "8e"})
    assert driver.status_code in (200, 201)

    source_route_id = _create_route_with_assignment(client, "ASN-SCH-1", "BUS-ASN-SCH-1", driver.json()["id"])
    target_route_id = _create_route_with_assignment(client, "ASN-SCH-2", "BUS-ASN-SCH-2", driver.json()["id"])

    source_route_update = client.put(
        f"/routes/{source_route_id}",
        json={"route_number": "ASN-SCH-1", "unit_number": "BUS-ASN-SCH-1", "school_ids": [school.json()["id"]]},
    )
    target_route_update = client.put(
        f"/routes/{target_route_id}",
        json={"route_number": "ASN-SCH-2", "unit_number": "BUS-ASN-SCH-2", "school_ids": [other_school.json()["id"]]},
    )
    assert source_route_update.status_code == 200
    assert target_route_update.status_code == 200

    source_run = client.post(f"/routes/{source_route_id}/runs", json={"run_type": "AM"})
    target_run = client.post(f"/routes/{target_route_id}/runs", json={"run_type": "AM"})
    assert source_run.status_code in (200, 201)
    assert target_run.status_code in (200, 201)

    source_stop = client.post("/stops/", json={"run_id": source_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Source Stop"})
    target_stop = client.post("/stops/", json={"run_id": target_run.json()["id"], "sequence": 1, "type": "pickup", "name": "Target Stop"})
    assert source_stop.status_code in (200, 201)
    assert target_stop.status_code in (200, 201)
    student = client.post(
        "/students/",
        json={
            "name": "Assignment School Student",
            "grade": "5",
            "school_id": school.json()["id"],      # belongs to source route
            "route_id": source_route_id,
            "stop_id": source_stop.json()["id"],
        },
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]
    moved = client.put(
    f"/students/{student_id}/assignment",
    json={
        "route_id": target_route_id,                 # target route
        "run_id": target_run.json()["id"],           # target run
        "stop_id": target_stop.json()["id"],         # valid stop
    },
)
    assert moved.status_code == 400
    assert moved.json()["detail"] == "School is not assigned to the run route"

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


# -----------------------------------------------------------
# - Run detail endpoint
# - Return nested route, stop, and student data for one run
# -----------------------------------------------------------
def test_run_detail_returns_nested_run_data(client):
    school = client.post(
        "/schools/",
        json={"name": "Run Detail School", "address": "50 Run Detail Rd"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    driver = client.post("/drivers/", json={"name": "Run Detail Driver", "email": "run.detail@x.com", "phone": "3"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "RUN-DETAIL-1", "unit_number": "BUS-RUN-DETAIL-1", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/routes/{route_id}/assign_driver/{driver_id}")
    assert assign.status_code in (200, 201)

    run = client.post("/runs/start", json={"route_id": route_id, "run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Run Detail Stop", "address": "51 Run Detail Rd", "planned_time": "07:05:00", "latitude": 1, "longitude": 1},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Run Detail Student", "school_id": school_id},
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == run_id
    assert data["route"]["route_id"] == route_id
    assert data["route"]["route_number"] == "RUN-DETAIL-1"
    assert data["route"]["unit_number"] == "BUS-RUN-DETAIL-1"
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
    driver = client.post("/drivers/", json={"name": "Run List Driver", "email": "run.list@x.com", "phone": "4"})
    assert driver.status_code in (200, 201)
    driver_id = driver.json()["id"]

    route_one_id = _create_route_with_assignment(client, "RUN-LIST-1", "BUS-RUN-LIST-1", driver_id)
    route_two_id = _create_route_with_assignment(client, "RUN-LIST-2", "BUS-RUN-LIST-2", driver_id)

    run_one = client.post(f"/routes/{route_one_id}/runs", json={"run_type": "Morning"})
    run_two = client.post(f"/routes/{route_two_id}/runs", json={"run_type": "Afternoon"})
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)

    missing_route = client.get("/runs/")
    assert missing_route.status_code == 400
    assert missing_route.json()["detail"] == "route_id is required"

    route_one_runs = client.get(f"/runs/?route_id={route_one_id}")
    assert route_one_runs.status_code == 200
    assert route_one_runs.json() == [
        {
            "run_id": run_one.json()["id"],
            "run_type": "MORNING",
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
    create = client.post("/schools/", json={"name": "North Ridge"})
    assert create.status_code in (200, 201)
    school = create.json()
    assert school["name"] == "North Ridge"
    assert school["address"] is None
    assert "school_code" not in school

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
    driver = client.post("/drivers/", json={"name": "Context Run Driver", "email": "ctx.run@test.com", "phone": "9"})
    assert driver.status_code in (200, 201)
    route_id = _create_route_with_assignment(client, "  5305  ", "BUS-5305", driver.json()["id"])

    created = client.post(f"/routes/{route_id}/runs", json={"run_type": " pm "})
    assert created.status_code == 201
    assert created.json()["route_id"] == route_id
    assert created.json()["run_type"] == "PM"

    duplicate = client.post(f"/routes/{route_id}/runs", json={"run_type": "Pm"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Run label already exists for this route"


def test_run_context_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/routes/{route_id}/runs"]["post"]
    assert path_item["summary"] == "Create run inside route"
    assert "Primary workflow-first run creation path." in path_item["description"]
    assert "without sending route_id in the body" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/RouteRunCreate")

    properties = response.json()["components"]["schemas"]["RouteRunCreate"]["properties"]
    assert "route_id" not in properties


def test_generic_run_create_endpoint_is_legacy_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/runs/"]["post"]
    assert path_item["summary"] == "Create run (legacy compatibility)"
    assert "Preferred workflow-first creation is POST /routes/{route_id}/runs" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/RunStart")

    properties = response.json()["components"]["schemas"]["RunStart"]["properties"]
    assert "route_id" in properties


def test_stop_context_student_create_rejects_school_not_on_route(client):
    valid_school = client.post("/schools/", json={"name": "Assigned School", "address": "1 Assigned Way"})
    other_school = client.post("/schools/", json={"name": "Other School", "address": "2 Other Way"})
    assert valid_school.status_code in (200, 201)
    assert other_school.status_code in (200, 201)

    driver = client.post("/drivers/", json={"name": "Route School Driver", "email": "route.school@test.com", "phone": "10"})
    assert driver.status_code in (200, 201)
    route = client.post(
        "/routes/",
        json={"route_number": "ROUTE-SCHOOL-1", "unit_number": "BUS-RS-1", "school_ids": [valid_school.json()["id"]]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    assign = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assign.status_code in (200, 201)

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code == 201
    run_id = run.json()["id"]

    stop = client.post(f"/runs/{run_id}/stops", json={"type": "pickup"})
    assert stop.status_code == 201

    response = client.post(
        f"/runs/{run_id}/stops/{stop.json()['id']}/students",
        json={"name": "Mismatched School Student", "school_id": other_school.json()["id"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "School is not assigned to the run route"


def test_run_context_stop_update_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/runs/{run_id}/stops/{stop_id}"]["put"]
    assert path_item["summary"] == "Update stop inside run"
    assert "without sending run_id again" in path_item["description"]


def test_run_context_stop_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/runs/{run_id}/stops"]["post"]
    assert path_item["summary"] == "Create stop inside run"
    assert "without sending run_id in the body" in path_item["description"]
    assert "preferred workflow-first stop creation path" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/RunStopCreate")

    properties = response.json()["components"]["schemas"]["RunStopCreate"]["properties"]
    assert "run_id" not in properties


def test_generic_stop_create_endpoint_is_legacy_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/stops/"]["post"]
    assert path_item["summary"] == "Create stop (legacy compatibility)"
    assert "Preferred workflow-first creation is POST /runs/{run_id}/stops." in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/StopCreate")

    properties = response.json()["components"]["schemas"]["StopCreate"]["properties"]
    assert "run_id" in properties


def test_run_context_student_create_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/runs/{run_id}/stops/{stop_id}/students"]["post"]
    assert path_item["summary"] == "Add student to run stop"
    assert "without repeating route_id, run_id, or stop_id in the body" in path_item["description"]
    assert "inherited automatically" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/StopStudentCreate")

    properties = response.json()["components"]["schemas"]["StopStudentCreate"]["properties"]
    assert "route_id" not in properties
    assert "run_id" not in properties
    assert "stop_id" not in properties


def test_generic_student_create_endpoint_is_secondary_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/students/"]["post"]
    assert path_item["summary"] == "Create student (secondary compatibility)"
    assert "Preferred layered workflow is POST /runs/{run_id}/stops/{stop_id}/students" in path_item["description"]
    assert "Optional route_id and stop_id fields are legacy planning pointers" in path_item["description"]

    schema_ref = path_item["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/StudentCompatibilityCreate")

    properties = response.json()["components"]["schemas"]["StudentCompatibilityCreate"]["properties"]
    assert "route_id" in properties
    assert "stop_id" in properties


def test_run_context_student_update_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    path_item = response.json()["paths"]["/runs/{run_id}/stops/{stop_id}/students/{student_id}"]["put"]
    assert path_item["summary"] == "Update student inside run stop"
    assert "without repeating run_id, stop_id, or student_id in the body" in path_item["description"]


def test_student_assignment_update_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]
    operation = paths["/students/{student_id}/assignment"]["put"]

    assert operation["summary"] == "Update student assignment (maintenance)"
    assert "Maintenance endpoint" in operation["description"]
    assert "not the normal creation workflow" in operation["description"]
    assert "POST /runs/{run_id}/stops/{stop_id}/students" in operation["description"]


def test_driver_routes_endpoint_appears_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    operation = response.json()["paths"]["/drivers/{driver_id}/routes"]["get"]
    assert operation["summary"] == "List driver routes"
    assert "entry point for the real operator workflow" in operation["description"]
    assert "selects an assigned route" in operation["description"]
    
def test_generic_student_update_endpoint_is_not_in_openapi(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    student_path = response.json()["paths"]["/students/{student_id}"]
    assert "put" not in student_path
