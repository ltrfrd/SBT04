# -----------------------------------------------------------
# Run Absence Integration Tests
# - Verify planned absences exclude students from run assignments and board data
# -----------------------------------------------------------
from datetime import date, timedelta  # Date helpers for matching and mismatch cases


def _build_run_with_students(client):
    driver = client.post("/drivers/", json={"name": "Absence Driver", "email": "absence_driver@test.com", "phone": "7805557001"}).json()  # Create driver dependency
    school = client.post("/schools/", json={"name": "Absence School", "address": "700 School Street", "phone": "7805557002"}).json()  # Create school dependency
    route = client.post("/routes/", json={"route_number": "700", "unit_number": "BUS-700", "school_ids": [school["id"]]}).json()  # Create route dependency
    client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")  # Assign driver separately
    run = client.post("/runs/", json={"route_id": route["id"], "run_type": "AM"}).json()  # Create target run
    stop = client.post("/stops/", json={"run_id": run["id"], "type": "pickup", "sequence": 1, "name": "Absence Stop", "address": "700 Stop Street", "planned_time": "07:10:00", "latitude": 53.7, "longitude": -113.7}).json()  # Create shared stop
    student = client.post("/students/", json={"name": "Boarded Student", "grade": "5", "school_id": school["id"], "route_id": route["id"], "stop_id": stop["id"]}).json()  # Create target student
    return run, stop, student  # Return shared setup objects


def _create_bus_absence(client, student_id: int, date: str, run_type: str):
    response = client.post(f"/students/{student_id}/bus_absence", json={"date": date, "run_type": run_type})  # Create planned absence for the student
    assert response.status_code == 201  # Confirm planned absence creation succeeded


def _create_assignment(client, student_id: int, run_id: int, stop_id: int):
    return client.post("/student-run-assignments/", json={"student_id": student_id, "run_id": run_id, "stop_id": stop_id})  # Create runtime assignment for the run


def test_student_without_planned_absence_still_appears_in_run_assignment_and_board(client):
    run, stop, student = _build_run_with_students(client)  # Create run, stop, and student without absence

    assignment_response = _create_assignment(client, student["id"], run["id"], stop["id"])  # Create assignment for non-absent student
    assert assignment_response.status_code == 201  # Confirm assignment creation succeeded

    assignments_response = client.get(f"/runs/{run['id']}/assignments")  # Read effective run assignments
    board_response = client.get(f"/runs/{run['id']}/running_board")  # Read effective running board

    assert assignments_response.status_code == 200  # Confirm assignment listing succeeded
    assert board_response.status_code == 200  # Confirm running board request succeeded
    assert [item["student_id"] for item in assignments_response.json()] == [student["id"]]  # Confirm student remains assigned
    assert board_response.json()["total_assigned_students"] == 1  # Confirm board counts the student
    assert [item["student_id"] for item in board_response.json()["stops"][0]["students"]] == [student["id"]]  # Confirm student appears on the stop board


def test_student_with_same_date_and_run_type_absence_is_excluded(client):
    run, stop, student = _build_run_with_students(client)  # Create run, stop, and student for exclusion case
    run_date = run["start_time"].split("T", 1)[0]  # Derive run date directly from created run payload
    _create_bus_absence(client, student["id"], run_date, "AM")  # Create matching planned absence

    assignment_response = _create_assignment(client, student["id"], run["id"], stop["id"])  # Attempt assignment for absent student
    assignments_response = client.get(f"/runs/{run['id']}/assignments")  # Read effective run assignments after rejection
    board_response = client.get(f"/runs/{run['id']}/running_board")  # Read effective running board after rejection

    assert assignment_response.status_code == 409  # Confirm matching planned absence blocks assignment creation
    assert assignment_response.json()["detail"] == "Student has a planned bus absence for this run"  # Confirm matching absence error detail
    assert assignments_response.status_code == 200  # Confirm assignment listing still succeeds
    assert assignments_response.json() == []  # Confirm absent student is excluded from effective assignments
    assert board_response.status_code == 200  # Confirm running board still succeeds
    assert board_response.json()["total_assigned_students"] == 0  # Confirm board does not count absent student
    assert board_response.json()["stops"][0]["student_count_at_stop"] == 0  # Confirm stop count excludes absent student
    assert board_response.json()["stops"][0]["students"] == []  # Confirm absent student is not shown at the stop


def test_student_with_different_absence_date_is_not_excluded(client):
    run, stop, student = _build_run_with_students(client)  # Create run, stop, and student for date mismatch case
    run_date = run["start_time"].split("T", 1)[0]  # Derive run date directly from created run payload
    _create_bus_absence(client, student["id"], (date.fromisoformat(run_date) + timedelta(days=1)).isoformat(), "AM")  # Create planned absence for a different date

    assignment_response = _create_assignment(client, student["id"], run["id"], stop["id"])  # Create assignment because absence date does not match
    assignments_response = client.get(f"/runs/{run['id']}/assignments")  # Read effective run assignments
    board_response = client.get(f"/runs/{run['id']}/running_board")  # Read effective running board

    assert assignment_response.status_code == 201  # Confirm non-matching absence date does not block assignment
    assert len(assignments_response.json()) == 1  # Confirm student remains assigned
    assert board_response.json()["total_assigned_students"] == 1  # Confirm board still counts student


def test_student_with_different_absence_run_type_is_not_excluded(client):
    run, stop, student = _build_run_with_students(client)  # Create run, stop, and student for run type mismatch case
    run_date = run["start_time"].split("T", 1)[0]  # Derive run date directly from created run payload
    _create_bus_absence(client, student["id"], run_date, "PM")  # Create planned absence for a different run type

    assignment_response = _create_assignment(client, student["id"], run["id"], stop["id"])  # Create assignment because run type does not match
    assignments_response = client.get(f"/runs/{run['id']}/assignments")  # Read effective run assignments
    board_response = client.get(f"/runs/{run['id']}/running_board")  # Read effective running board

    assert assignment_response.status_code == 201  # Confirm non-matching run type does not block assignment
    assert len(assignments_response.json()) == 1  # Confirm student remains assigned
    assert board_response.json()["total_assigned_students"] == 1  # Confirm board still counts student
