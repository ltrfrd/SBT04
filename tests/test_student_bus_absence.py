# -----------------------------------------------------------
# Student Bus Absence Tests
# - Verify planned no-ride creation and deletion behavior
# -----------------------------------------------------------
def _create_student(client):
    school_response = client.post("/schools/", json={"name": "Absence School", "address": "100 Main St"})  # Create school dependency
    assert school_response.status_code in (200, 201)  # Confirm school creation succeeded
    school_id = school_response.json()["id"]  # Extract school ID

    route_response = client.post(
        "/routes/",
        json={"route_number": "ABSENCE-STUDENT-ROUTE", "school_ids": [school_id]},
    )  # Create route context for student planning
    assert route_response.status_code in (200, 201)
    route_id = route_response.json()["id"]

    student_response = client.post(
        f"/routes/{route_id}/students",
        json={"name": "Absence Student", "grade": "4", "school_id": school_id},
    )  # Create student for absence tests
    assert student_response.status_code in (200, 201)  # Confirm student creation succeeded
    return student_response.json()["id"]  # Return created student ID


def test_create_student_bus_absence_success(client):
    student_id = _create_student(client)  # Create prerequisite student

    response = client.post(
        f"/students/{student_id}/bus_absence",
        json={"date": "2026-03-20", "run_type": "AM"},
    )  # Create planned AM absence

    assert response.status_code == 201  # Confirm absence creation succeeded
    body = response.json()  # Parse absence payload
    assert body["student_id"] == student_id  # Confirm absence belongs to the student
    assert body["date"] == "2026-03-20"  # Confirm date persisted
    assert body["run_type"] == "AM"  # Confirm run type persisted
    assert body["source"] == "parent"  # Confirm default source is parent
    assert body["created_at"] is not None  # Confirm creation timestamp exists


def test_create_student_bus_absence_rejects_duplicate(client):
    student_id = _create_student(client)  # Create prerequisite student
    payload = {"date": "2026-03-20", "run_type": "AM", "source": "school"}  # Duplicate test payload

    first_response = client.post(f"/students/{student_id}/bus_absence", json=payload)  # Create initial absence
    assert first_response.status_code == 201  # Confirm initial absence succeeded

    duplicate_response = client.post(f"/students/{student_id}/bus_absence", json=payload)  # Attempt duplicate absence

    assert duplicate_response.status_code == 409  # Confirm duplicate is blocked
    assert duplicate_response.json()["detail"] == "Student bus absence already exists for this date and run type"  # Confirm duplicate error detail


def test_delete_student_bus_absence_success(client):
    student_id = _create_student(client)  # Create prerequisite student
    create_response = client.post(
        f"/students/{student_id}/bus_absence",
        json={"date": "2026-03-20", "run_type": "PM", "source": "dispatch"},
    )  # Create planned PM absence
    assert create_response.status_code == 201  # Confirm absence creation succeeded

    delete_response = client.delete(
        f"/students/{student_id}/bus_absence",
        params={"date": "2026-03-20", "run_type": "PM"},
    )  # Delete matching planned absence

    assert delete_response.status_code == 204  # Confirm absence deletion succeeded

    missing_response = client.delete(
        f"/students/{student_id}/bus_absence",
        params={"date": "2026-03-20", "run_type": "PM"},
    )  # Confirm record is gone

    assert missing_response.status_code == 404  # Confirm deleted absence no longer exists
    assert missing_response.json()["detail"] == "Student bus absence not found"  # Confirm missing error detail


def test_delete_student_bus_absence_missing_returns_404(client):
    student_id = _create_student(client)  # Create prerequisite student

    response = client.delete(
        f"/students/{student_id}/bus_absence",
        params={"date": "2026-03-20", "run_type": "AM"},
    )  # Attempt to delete absence that does not exist

    assert response.status_code == 404  # Confirm missing absence returns not found
    assert response.json()["detail"] == "Student bus absence not found"  # Confirm missing error detail


def test_create_student_bus_absence_for_missing_student_returns_404(client):
    response = client.post(
        "/students/9999/bus_absence",
        json={"date": "2026-03-20", "run_type": "AM"},
    )  # Attempt to create absence for missing student

    assert response.status_code == 404  # Confirm missing student returns not found
    assert response.json()["detail"] == "Student not found"  # Confirm missing student detail
