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
        "/stops/",
        json={"run_id": run_id, "name": "Summary Stop", "latitude": 1, "longitude": 1, "type": "pickup", "sequence": 1},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        "/students/",
        json={"name": "Summary Student", "school_id": school_id, "route_id": route_id, "stop_id": stop_id},
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    assignment = client.post(
        "/student-run-assignments/",
        json={"student_id": student_id, "run_id": run_id, "stop_id": stop_id},
    )
    assert assignment.status_code == 201

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
        "/stops/",
        json={
            "run_id": run_id,
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
        "/students/",
        json={"name": "Detail Student", "school_id": school_id, "route_id": route_id, "stop_id": stop_id},
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    assignment = client.post(
        "/student-run-assignments/",
        json={"student_id": student_id, "run_id": run_id, "stop_id": stop_id},
    )
    assert assignment.status_code == 201

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

    run = client.post("/runs/", json={"route_id": route_id, "run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        "/stops/",
        json={"run_id": run_id, "sequence": 1, "type": "pickup", "name": "Context Stop", "address": "71 Context Way"},
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

    run = client.post("/runs/", json={"route_id": route_id, "run_type": "Afternoon"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        "/stops/",
        json={"run_id": run_id, "sequence": 1, "type": "pickup", "name": "Bulk Stop", "address": "81 Bulk Way"},
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

    run_one = client.post("/runs/", json={"route_id": route_id, "run_type": "Morning"})
    run_two = client.post("/runs/", json={"route_id": route_id, "run_type": "Afternoon"})
    assert run_one.status_code in (200, 201)
    assert run_two.status_code in (200, 201)

    stop = client.post(
        "/stops/",
        json={"run_id": run_two.json()["id"], "sequence": 1, "type": "pickup", "name": "Other Run Stop"},
    )
    assert stop.status_code in (200, 201)

    response = client.post(
        f"/runs/{run_one.json()['id']}/stops/{stop.json()['id']}/students",
        json={"name": "Mismatch Student", "grade": "6", "school_id": school_id},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Stop does not belong to run"

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

    route_id = _create_route_with_assignment(client, "RUN-DETAIL-1", "BUS-RUN-DETAIL-1", driver_id)

    run = client.post("/runs/start", json={"route_id": route_id, "run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        "/stops/",
        json={"run_id": run_id, "sequence": 1, "type": "pickup", "name": "Run Detail Stop", "address": "51 Run Detail Rd", "planned_time": "07:05:00", "latitude": 1, "longitude": 1},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        "/students/",
        json={"name": "Run Detail Student", "school_id": school_id, "route_id": route_id, "stop_id": stop_id},
    )
    assert student.status_code in (200, 201)
    student_id = student.json()["id"]

    assignment = client.post(
        "/student-run-assignments/",
        json={"student_id": student_id, "run_id": run_id, "stop_id": stop_id},
    )
    assert assignment.status_code == 201

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

    run_one = client.post("/runs/", json={"route_id": route_one_id, "run_type": "Morning"})
    run_two = client.post("/runs/", json={"route_id": route_two_id, "run_type": "Afternoon"})
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
