# =============================================================================
# tests/test_student_run_assignment.py
# -----------------------------------------------------------------------------
# Purpose:
#   Verify the Student Run Assignment compatibility router now exposes
#   read-only lookup behavior while direct raw creation is blocked.
# =============================================================================


# -----------------------------------------------------------------------------
# Shared setup helper
# -----------------------------------------------------------------------------
from sqlalchemy.orm import Session

from app import get_db
from backend.models.route import Route


def _get_client_db_engine(client):
    wrapped_client = getattr(client, "_wrapped_client", client)
    override = wrapped_client.app.dependency_overrides[get_db]
    for cell in override.__closure__ or ():
        candidate = cell.cell_contents
        bind = getattr(candidate, "kw", {}).get("bind")
        if bind is not None:
            return bind
    raise AssertionError("Unable to resolve test database engine from client fixture")


def _get_route_district_id(client, route_id: int) -> int:
    db_engine = _get_client_db_engine(client)
    with Session(db_engine) as db:
        route = db.get(Route, route_id)
        assert route is not None
        assert route.district_id is not None
        return route.district_id


def _build_assignment_context(client, route_number: str, run_types: list[str]):

    # -------------------------------------------------------------------------
    # Create driver
    # -------------------------------------------------------------------------
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), 
            "name": f"{route_number} Driver",
            "email": f"{route_number.lower()}@test.com",
            "phone": "7805553001",
            "pin": "1234",
        },
    ).json()

    # -------------------------------------------------------------------------
    # Create district and school
    # -------------------------------------------------------------------------
    district = client.post(
        "/districts/",
        json={"name": f"{route_number} District"},
    ).json()
    school = client.post(
        f"/districts/{district['id']}/schools",
        json={
            "name": f"{route_number} School",
            "address": f"{route_number} School Street",
            "phone": "7805553002",
        },
    ).json()

    # -------------------------------------------------------------------------
    # Create route
    # -------------------------------------------------------------------------
    route = client.post(
        f"/districts/{district['id']}/routes",
        json={
            "route_number": route_number,
            "school_ids": [school["id"]],
        },
    ).json()

    client.post(f"/routes/{route['id']}/assign_driver/{driver['id']}")  # Keep route workflow realistic

    runs: list[dict] = []  # Preserve created runs in request order
    stops: list[dict] = []  # Preserve created stops in request order

    # -------------------------------------------------------------------------
    # Create requested runs and one stop per run
    # -------------------------------------------------------------------------
    for index, run_type in enumerate(run_types, start=1):
        run = client.post(
            f"/districts/{district['id']}/routes/{route['id']}/runs",
            json={
                "run_type": run_type,
                "scheduled_start_time": "07:00:00",
                "scheduled_end_time": "08:00:00",
            },
        ).json()
        runs.append(run)

        stop = client.post(
            f"/districts/{district['id']}/routes/{route['id']}/runs/{run['id']}/stops",
            json={
                "type": "pickup",
                "sequence": 1,
                "name": f"{route_number} Stop {index}",
                "address": f"{route_number} Stop Street {index}",
                "planned_time": f"07:{index:02d}:00",
                "latitude": 53.3 + index,
                "longitude": -113.3 - index,
            },
        ).json()
        stops.append(stop)

    return {
        "driver": driver,
        "school": school,
        "route": route,
        "runs": runs,
        "stops": stops,
    }


def test_create_student_run_assignment_is_blocked(client):

    # -------------------------------------------------------------------------
    # Build minimal valid compatibility payload inputs
    # -------------------------------------------------------------------------
    context = _build_assignment_context(client, "SRA-BLOCK", ["AM"])
    run = context["runs"][0]
    stop = context["stops"][0]
    school = context["school"]
    student = client.post(
        f"/runs/{run['id']}/stops/{stop['id']}/students",
        json={
            "name": "Blocked Assignment Student",
            "grade": "6",
            "school_id": school["id"],
        },
    ).json()

    # -------------------------------------------------------------------------
    # Direct raw assignment creation is no longer allowed
    # -------------------------------------------------------------------------
    response = client.post(
        "/student-run-assignments/",
        json={
            "student_id": student["id"],
            "run_id": run["id"],
            "stop_id": stop["id"],
        },
    )

    assert response.status_code == 410
    assert response.json()["detail"] == (
        "Direct student run assignment creation is retired. "
        "Use POST /districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students."
    )


# -----------------------------------------------------------
# - Get run assignments
# - Return all student assignments for one run
# -----------------------------------------------------------
def test_get_student_run_assignments_by_run_returns_all_students(client):

    # -------------------------------------------------------------------------
    # Create route/run/stop workflow context
    # -------------------------------------------------------------------------
    context = _build_assignment_context(client, "SRA-RUN", ["AM"])
    run = context["runs"][0]
    stop = context["stops"][0]
    school = context["school"]

    # -------------------------------------------------------------------------
    # Create students through the canonical stop-context path
    # -------------------------------------------------------------------------
    student_1 = client.post(
        f"/runs/{run['id']}/stops/{stop['id']}/students",
        json={
            "name": "Student One",
            "grade": "5",
            "school_id": school["id"],
        },
    ).json()

    student_2 = client.post(
        f"/runs/{run['id']}/stops/{stop['id']}/students",
        json={
            "name": "Student Two",
            "grade": "6",
            "school_id": school["id"],
        },
    ).json()

    # -------------------------------------------------------------------------
    # Read all assignments for the run
    # -------------------------------------------------------------------------
    response = client.get(f"/student-run-assignments/{run['id']}")
    data = response.json()

    assert response.status_code == 200
    assert [item["student_id"] for item in data] == [student_1["id"], student_2["id"]]
    assert all(item["run_id"] == run["id"] for item in data)
    assert all(item["stop_id"] == stop["id"] for item in data)


# -----------------------------------------------------------
# - Get student assignments
# - Return assignments for one student across runs
# -----------------------------------------------------------
def test_get_student_run_assignments_by_student_lookup(client):

    # -------------------------------------------------------------------------
    # Create route with two runs
    # -------------------------------------------------------------------------
    context = _build_assignment_context(client, "SRA-STUDENT", ["AM", "PM"])
    school = context["school"]
    run_1, run_2 = context["runs"]
    stop_1, stop_2 = context["stops"]
    district_id = _get_route_district_id(client, context["route"]["id"])
    route_id = context["route"]["id"]

    # -------------------------------------------------------------------------
    # Create the canonical initial stop-context student
    # -------------------------------------------------------------------------
    student = client.post(
        f"/runs/{run_1['id']}/stops/{stop_1['id']}/students",
        json={
            "name": "Lookup Student",
            "grade": "7",
            "school_id": school["id"],
        },
    ).json()

    # -------------------------------------------------------------------------
    moved = client.put(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_2['id']}/stops/{stop_2['id']}/students/{student['id']}",
        json={},
    )

    assert moved.status_code == 200

    # -------------------------------------------------------------------------
    # Read assignments for the student
    # -------------------------------------------------------------------------
    response = client.get(f"/student-run-assignments/?student_id={student['id']}")
    data = response.json()

    assert response.status_code == 200
    assert [item["run_id"] for item in data] == [run_2["id"]]
    assert [item["stop_id"] for item in data] == [stop_2["id"]]


# -----------------------------------------------------------
# - Require student lookup filter
# - Reject empty student assignment list requests
# -----------------------------------------------------------
def test_list_student_run_assignments_requires_student_id(client):
    response = client.get("/student-run-assignments/")

    assert response.status_code == 400
    assert response.json()["detail"] == "student_id is required"


# -----------------------------------------------------------
# - Delete assignment is blocked
# - Reject direct runtime assignment deletion
# -----------------------------------------------------------
def test_delete_student_run_assignment_is_blocked(client):

    # -------------------------------------------------------------------------
    # Build assignment through canonical stop-context workflow
    # -------------------------------------------------------------------------
    context = _build_assignment_context(client, "SRA-DELETE", ["AM"])
    run = context["runs"][0]
    stop = context["stops"][0]
    school = context["school"]

    student = client.post(
        f"/runs/{run['id']}/stops/{stop['id']}/students",
        json={
            "name": "Delete Blocked Student",
            "grade": "5",
            "school_id": school["id"],
        },
    ).json()

    assignments = client.get(f"/student-run-assignments/{run['id']}")
    assert assignments.status_code == 200
    assignment_id = assignments.json()[0]["id"]
    assert assignments.json()[0]["student_id"] == student["id"]

    # -------------------------------------------------------------------------
    # Direct delete should remain blocked
    # -------------------------------------------------------------------------
    response = client.delete(f"/student-run-assignments/{assignment_id}")

    assert response.status_code == 410
    assert response.json()["detail"] == (
        "Direct assignment deletion is retired. "
        "Use DELETE /districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students/{student_id}."
    )
