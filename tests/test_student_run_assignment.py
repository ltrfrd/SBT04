# =============================================================================
# tests/test_student_run_assignment.py
# -----------------------------------------------------------------------------
# Purpose:
#   Directly test the Student Run Assignment router.
#
# Endpoint tested:
#   POST /student-run-assignments/
#
# What this file verifies:
#   - valid assignment creation
#   - duplicate assignment returns 409
# =============================================================================

def test_create_student_run_assignment_success(client):  # Test valid assignment creation

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post("/drivers/", json={  # Create a driver
        "name": "Assign Driver",
        "email": "assign_driver@test.com",
        "phone": "7805553001"
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post("/schools/", json={  # Create a school
        "name": "Assign School",
        "address": "300 School Street",
        "phone": "7805553002"
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post("/routes/", json={  # Create a route
        "route_number": "300",
        "unit_number": "BUS-300",
        "school_ids": [school["id"]]
    }).json()  # Parse JSON response

    client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")  # Assign driver separately

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post("/runs/", json={  # Create a run
        "route_id": route["id"],
        "run_type": "AM"
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create stop
    # -------------------------------------------------------------------------
    stop = client.post("/stops/", json={  # Create one stop for the run
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 1,
        "name": "Assign Stop",
        "address": "300 Stop Street",
        "planned_time": "07:30:00",
        "latitude": 53.3,
        "longitude": -113.3
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create student
    # -------------------------------------------------------------------------
    student = client.post("/students/", json={  # Create one student
        "name": "Assigned Student",
        "grade": "6",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop["id"]
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create assignment
    # -------------------------------------------------------------------------
    response = client.post("/student-run-assignments/", json={  # Create runtime assignment
        "student_id": student["id"],
        "run_id": run["id"],
        "stop_id": stop["id"]
    })  # Keep full response for assertions

    data = response.json()  # Parse JSON response

    assert response.status_code == 201  # Assignment should be created successfully
    assert data["student_id"] == student["id"]  # Response should contain correct student ID
    assert data["run_id"] == run["id"]  # Response should contain correct run ID
    assert data["stop_id"] == stop["id"]  # Response should contain correct stop ID


def test_create_student_run_assignment_duplicate_returns_409(client):  # Test duplicate assignment conflict

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post("/drivers/", json={  # Create a driver
        "name": "Dup Driver",
        "email": "dup_driver@test.com",
        "phone": "7805554001"
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post("/schools/", json={  # Create a school
        "name": "Dup School",
        "address": "400 School Street",
        "phone": "7805554002"
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post("/routes/", json={  # Create a route
        "route_number": "400",
        "unit_number": "BUS-400",
        "school_ids": [school["id"]]
    }).json()  # Parse JSON response

    client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")  # Assign driver separately

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post("/runs/", json={  # Create a run
        "route_id": route["id"],
        "run_type": "AM"
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create two stops
    # -------------------------------------------------------------------------
    stop1 = client.post("/stops/", json={  # Create first stop
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 1,
        "name": "Dup Stop 1",
        "address": "401 Stop Street",
        "planned_time": "07:10:00",
        "latitude": 53.4,
        "longitude": -113.4
    }).json()  # Parse JSON response

    stop2 = client.post("/stops/", json={  # Create second stop
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 2,
        "name": "Dup Stop 2",
        "address": "402 Stop Street",
        "planned_time": "07:20:00",
        "latitude": 53.5,
        "longitude": -113.5
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create one student
    # -------------------------------------------------------------------------
    student = client.post("/students/", json={  # Create one student
        "name": "Duplicate Student",
        "grade": "7",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop1["id"]
    }).json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Create first assignment
    # -------------------------------------------------------------------------
    first_response = client.post("/student-run-assignments/", json={  # First assignment should succeed
        "student_id": student["id"],
        "run_id": run["id"],
        "stop_id": stop1["id"]
    })  # Keep response for assertion

    assert first_response.status_code == 201  # First assignment should be created

    # -------------------------------------------------------------------------
    # Attempt duplicate assignment for same student and same run
    # -------------------------------------------------------------------------
    second_response = client.post("/student-run-assignments/", json={  # Duplicate assignment should fail
        "student_id": student["id"],
        "run_id": run["id"],
        "stop_id": stop2["id"]
    })  # Keep response for assertion

    assert second_response.status_code == 409  # Same student cannot be assigned twice in one run


# -----------------------------------------------------------
# - Get run assignments
# - Return all student assignments for one run
# -----------------------------------------------------------
def test_get_student_run_assignments_by_run_returns_all_students(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post("/drivers/", json={
        "name": "Read Driver",
        "email": "read_driver@test.com",
        "phone": "7805555001"
    }).json()

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post("/schools/", json={
        "name": "Read School",
        "address": "500 School Street",
        "phone": "7805555002"
    }).json()

    # -------------------------------------------------------------------------
    # Create route and run
    # -------------------------------------------------------------------------
    route = client.post("/routes/", json={
        "route_number": "500",
        "unit_number": "BUS-500",
        "school_ids": [school["id"]]
    }).json()
    client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")

    run = client.post("/runs/", json={
        "route_id": route["id"],
        "run_type": "AM"
    }).json()

    # -------------------------------------------------------------------------
    # Create two stops
    # -------------------------------------------------------------------------
    stop_1 = client.post("/stops/", json={
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 1,
        "name": "Read Stop 1",
        "address": "501 Stop Street",
        "planned_time": "07:10:00",
        "latitude": 53.51,
        "longitude": -113.51
    }).json()

    stop_2 = client.post("/stops/", json={
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 2,
        "name": "Read Stop 2",
        "address": "502 Stop Street",
        "planned_time": "07:20:00",
        "latitude": 53.52,
        "longitude": -113.52
    }).json()

    # -------------------------------------------------------------------------
    # Create two students
    # -------------------------------------------------------------------------
    student_1 = client.post("/students/", json={
        "name": "Student One",
        "grade": "5",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop_1["id"]
    }).json()

    student_2 = client.post("/students/", json={
        "name": "Student Two",
        "grade": "6",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop_2["id"]
    }).json()

    # -------------------------------------------------------------------------
    # Create two assignments for the same run
    # -------------------------------------------------------------------------
    first_assignment = client.post("/student-run-assignments/", json={
        "student_id": student_1["id"],
        "run_id": run["id"],
        "stop_id": stop_1["id"]
    })
    assert first_assignment.status_code == 201

    second_assignment = client.post("/student-run-assignments/", json={
        "student_id": student_2["id"],
        "run_id": run["id"],
        "stop_id": stop_2["id"]
    })
    assert second_assignment.status_code == 201

    # -------------------------------------------------------------------------
    # Read all assignments for the run
    # -------------------------------------------------------------------------
    response = client.get(f"/student-run-assignments/{run['id']}")
    data = response.json()

    assert response.status_code == 200
    assert [item["student_id"] for item in data] == [student_1["id"], student_2["id"]]
    assert all(item["run_id"] == run["id"] for item in data)


# -----------------------------------------------------------
# - Get student assignments
# - Return assignments for one student across runs
# -----------------------------------------------------------
def test_get_student_run_assignments_by_student_lookup(client):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post("/drivers/", json={
        "name": "Lookup Driver",
        "email": "lookup_driver@test.com",
        "phone": "7805556001"
    }).json()

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post("/schools/", json={
        "name": "Lookup School",
        "address": "600 School Street",
        "phone": "7805556002"
    }).json()

    # -------------------------------------------------------------------------
    # Create route and two runs
    # -------------------------------------------------------------------------
    route = client.post("/routes/", json={
        "route_number": "600",
        "unit_number": "BUS-600",
        "school_ids": [school["id"]]
    }).json()
    client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")

    run_1 = client.post("/runs/", json={
        "route_id": route["id"],
        "run_type": "AM"
    }).json()

    run_2 = client.post("/runs/", json={
        "route_id": route["id"],
        "run_type": "PM"
    }).json()

    # -------------------------------------------------------------------------
    # Create one stop per run
    # -------------------------------------------------------------------------
    stop_1 = client.post("/stops/", json={
        "run_id": run_1["id"],
        "type": "pickup",
        "sequence": 1,
        "name": "Lookup Stop 1",
        "address": "601 Stop Street",
        "planned_time": "07:10:00",
        "latitude": 53.61,
        "longitude": -113.61
    }).json()

    stop_2 = client.post("/stops/", json={
        "run_id": run_2["id"],
        "type": "pickup",
        "sequence": 1,
        "name": "Lookup Stop 2",
        "address": "602 Stop Street",
        "planned_time": "15:10:00",
        "latitude": 53.62,
        "longitude": -113.62
    }).json()

    # -------------------------------------------------------------------------
    # Create one student
    # -------------------------------------------------------------------------
    student = client.post("/students/", json={
        "name": "Lookup Student",
        "grade": "7",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop_1["id"]
    }).json()

    # -------------------------------------------------------------------------
    # Create assignments across both runs
    # -------------------------------------------------------------------------
    first_assignment = client.post("/student-run-assignments/", json={
        "student_id": student["id"],
        "run_id": run_1["id"],
        "stop_id": stop_1["id"]
    })
    assert first_assignment.status_code == 201

    second_assignment = client.post("/student-run-assignments/", json={
        "student_id": student["id"],
        "run_id": run_2["id"],
        "stop_id": stop_2["id"]
    })
    assert second_assignment.status_code == 201

    # -------------------------------------------------------------------------
    # Read assignments for the student
    # -------------------------------------------------------------------------
    response = client.get(f"/student-run-assignments/?student_id={student['id']}")
    data = response.json()

    assert response.status_code == 200
    assert [item["run_id"] for item in data] == [run_1["id"], run_2["id"]]


# -----------------------------------------------------------
# - Require student lookup filter
# - Reject empty student assignment list requests
# -----------------------------------------------------------
def test_list_student_run_assignments_requires_student_id(client):
    response = client.get("/student-run-assignments/")

    assert response.status_code == 400
    assert response.json()["detail"] == "student_id is required"
