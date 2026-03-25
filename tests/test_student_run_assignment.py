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
