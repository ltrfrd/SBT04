# =============================================================================
# tests/test_running_board.py
# -----------------------------------------------------------------------------
# Purpose:
#   Verify the Run Running Board endpoint works correctly.
#
# Endpoint tested:
#   GET /runs/{run_id}/running_board
#
# What this test verifies:
#   - endpoint returns HTTP 200
#   - correct stop count
#   - correct student assignments
#   - cumulative load logic
# =============================================================================

def test_running_board_basic(client):  # Test the running board endpoint

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post("/drivers/", json={  # Create a driver
        "name": "Test Driver",
        "email": "driver@test.com",
        "phone": "7801110000"
    }).json()  # Convert response to JSON

    # -------------------------------------------------------------------------
    # Create school
    # -------------------------------------------------------------------------
    school = client.post("/schools/", json={  # Create a school
        "name": "Test School",
        "address": "100 School Rd",
        "phone": "7801110001"
    }).json()

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post("/routes/", json={  # Create route
        "route_number": "99",
        "unit_number": "BUS99",
        "school_ids": [school["id"]]
    }).json()

    assign = client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")  # Assign driver separately
    assert assign.status_code in (200, 201)

    # -------------------------------------------------------------------------
    # Create run
    # -------------------------------------------------------------------------
    run = client.post("/runs/", json={  # Create run
        "route_id": route["id"],
        "run_type": "AM"
    }).json()

    # -------------------------------------------------------------------------
    # Create stops
    # -------------------------------------------------------------------------
    stop1 = client.post("/stops/", json={  # First stop
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 1,
        "name": "Stop 1",
        "address": "Street 1",
        "planned_time": "07:10:00",
        "latitude": 53.1,
        "longitude": -113.1
    }).json()

    stop2 = client.post("/stops/", json={  # Second stop
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 2,
        "name": "Stop 2",
        "address": "Street 2",
        "planned_time": "07:20:00",
        "latitude": 53.2,
        "longitude": -113.2
    }).json()

    stop3 = client.post("/stops/", json={  # School stop
        "run_id": run["id"],
        "type": "school_arrive",
        "sequence": 3,
        "school_id": school["id"],
        "planned_time": "07:35:00",
    }).json()

    stop4 = client.post("/stops/", json={  # Unnamed regular stop for fallback display
        "run_id": run["id"],
        "type": "pickup",
        "sequence": 4,
        "latitude": 53.4,
        "longitude": -113.4,
    }).json()

    # -------------------------------------------------------------------------
    # Create students
    # -------------------------------------------------------------------------
    student1 = client.post("/students/", json={  # Student at stop 1
        "name": "Student One",
        "grade": "5",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop1["id"]
    }).json()

    student2 = client.post("/students/", json={  # Student at stop 2
        "name": "Student Two",
        "grade": "5",
        "school_id": school["id"],
        "route_id": route["id"],
        "stop_id": stop2["id"]
    }).json()

    # -------------------------------------------------------------------------
    # Create runtime assignments
    # -------------------------------------------------------------------------
    client.post("/student-run-assignments/", json={  # Assignment for student 1
        "student_id": student1["id"],
        "run_id": run["id"],
        "stop_id": stop1["id"]
    })

    client.post("/student-run-assignments/", json={  # Assignment for student 2
        "student_id": student2["id"],
        "run_id": run["id"],
        "stop_id": stop2["id"]
    })

    # -------------------------------------------------------------------------
    # Call running board endpoint
    # -------------------------------------------------------------------------
    response = client.get(f"/runs/{run['id']}/running_board")  # Request running board

    assert response.status_code == 200  # Endpoint should succeed

    data = response.json()  # Parse JSON response

    # -------------------------------------------------------------------------
    # Verify overall structure
    # -------------------------------------------------------------------------
    assert data["total_stops"] == 4  # Should have four stops
    assert data["total_assigned_students"] == 2  # Two students assigned

    # -------------------------------------------------------------------------
    # Verify cumulative load logic
    # -------------------------------------------------------------------------
    assert data["stops"][0]["cumulative_load"] == 1  # First stop boards 1 student
    assert data["stops"][1]["cumulative_load"] == 2  # Second stop increases load
    assert data["stops"][2]["cumulative_load"] == 2  # School stop with no riders preserves load
    assert data["stops"][3]["cumulative_load"] == 2  # Empty regular stop preserves load

    # -------------------------------------------------------------------------
    # Verify display naming rules
    # -------------------------------------------------------------------------
    assert data["stops"][0]["display_name"] == "Stop 1"
    assert data["stops"][0]["is_school_stop"] is False
    assert data["stops"][2]["stop_id"] == stop3["id"]
    assert data["stops"][2]["display_name"] == "Test School"
    assert data["stops"][2]["is_school_stop"] is True
    assert data["stops"][3]["stop_id"] == stop4["id"]
    assert data["stops"][3]["display_name"] == "STOP 4"
    assert data["stops"][3]["is_school_stop"] is False
