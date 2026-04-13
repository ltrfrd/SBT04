# =============================================================================
# tests/test_phase0_tenant_auth.py
# -----------------------------------------------------------------------------
# Phase 0 tenant isolation and authentication tests.
# All multi-operator scenarios use session auth (login/logout) — no X-Operator-ID
# header trust, which is intentionally removed as a security fix.
# =============================================================================
from datetime import date

from sqlalchemy.orm import Session

from backend.models.district import District
from backend.models.driver import Driver
from backend.models.route import Route
from backend.models.run import Run
from backend.models.school import School
from backend.models.stop import Stop
from backend.models.student import Student
from tests.conftest import TEST_DRIVER_PIN, _create_operator_in_db, _create_driver_in_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, driver_id: int, pin: str = TEST_DRIVER_PIN) -> None:
    r = client.post("/login", json={"driver_id": driver_id, "pin": pin})
    assert r.status_code == 200, f"Login failed: {r.text}"


def _logout(client) -> None:
    r = client.post("/logout")
    assert r.status_code == 200


def _create_district_in_db(db_engine, name: str, contact_info: str | None = None) -> int:
    with Session(db_engine) as db:
        district = District(name=name, contact_info=contact_info)
        db.add(district)
        db.commit()
        db.refresh(district)
        return district.id


def _share_route(client, route_id: int, target_operator_id: int, access_level: str = "read") -> None:
    response = client.post(
        f"/routes/{route_id}/share/{target_operator_id}",
        json={"access_level": access_level},
    )
    assert response.status_code == 200
    assert response.json()["access_level"] == access_level


# ---------------------------------------------------------------------------
# AUTH: login / logout behaviour
# ---------------------------------------------------------------------------

def test_login_requires_valid_pin(client, db_engine):
    # PIN is supplied explicitly here — this test documents what credential is used.
    driver = client.post(
        "/drivers/",
        json={"name": "Secure Driver", "email": "secure@test.com", "phone": "555", "pin": "5678"},
    )
    assert driver.status_code == 201
    with Session(db_engine) as db:
        expected_operator_id = db.get(Driver, driver.json()["id"]).operator_id

    missing_pin = client.post("/login", json={"driver_id": driver.json()["id"]})
    assert missing_pin.status_code == 401

    wrong_pin = client.post("/login", json={"driver_id": driver.json()["id"], "pin": "9999"})
    assert wrong_pin.status_code == 401

    valid_login = client.post("/login", json={"driver_id": driver.json()["id"], "pin": "5678"})
    assert valid_login.status_code == 200
    assert valid_login.json()["operator_id"] == expected_operator_id


# ---------------------------------------------------------------------------
# C2 / M1: X-Operator-ID header must NOT grant operator context without a session
# ---------------------------------------------------------------------------

def test_xoperator_id_header_without_session_is_rejected(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Header Bypass Operator")

    # Log out so there is no active session
    _logout(client)

    # Unauthenticated request with X-Operator-ID header — must be 401, not 200
    r = client.get("/drivers/", headers={"x-operator-id": str(operator_id)})
    assert r.status_code == 401, (
        f"Expected 401 (unauthenticated), got {r.status_code}. "
        "X-Operator-ID must not grant operator context without a valid session."
    )


def test_single_operator_anonymous_access_is_rejected(client, db_engine):
    # The test DB already has exactly one operator (from bootstrap). Unauthenticated
    # access to that single operator must be rejected — not silently granted.
    _logout(client)

    r = client.get("/routes/")
    assert r.status_code == 401, (
        f"Expected 401 (unauthenticated), got {r.status_code}. "
        "Single-operator mode must not grant anonymous access."
    )


# ---------------------------------------------------------------------------
# C2: Tenant isolation — cross-operator reads and writes are blocked
# ---------------------------------------------------------------------------

def test_operator_isolation_blocks_cross_operator_reads_and_writes(client, db_engine):
    operator_one_id = _create_operator_in_db(db_engine, "Alpha Transit")
    operator_two_id = _create_operator_in_db(db_engine, "Beta Transit")

    driver_one_id = _create_driver_in_db(db_engine, operator_one_id, "Alpha Driver", "alpha-driver@test.com")
    driver_two_id = _create_driver_in_db(db_engine, operator_two_id, "Beta Driver", "beta-driver@test.com")

    # --- Operator one creates a route ---
    _login(client, driver_one_id)
    route_one = client.post("/routes/", json={"route_number": "ALPHA-1"})
    assert route_one.status_code in (200, 201)
    route_one_id = route_one.json()["id"]

    # --- Switch to operator two ---
    _logout(client)
    _login(client, driver_two_id)

    # Operator two cannot read operator one's driver
    cross_read_driver = client.get(f"/drivers/{driver_one_id}")
    assert cross_read_driver.status_code == 404

    # Operator two cannot read operator one's route
    cross_read_route = client.get(f"/routes/{route_one_id}")
    assert cross_read_route.status_code == 404

    # Operator two cannot write operator one's route
    cross_write_route = client.put(
        f"/routes/{route_one_id}",
        json={"route_number": "BETA-HIJACK"},
    )
    assert cross_write_route.status_code == 404


# ---------------------------------------------------------------------------
# Shared route access requires explicit grant
# ---------------------------------------------------------------------------

def test_shared_route_access_requires_explicit_grant(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Owner Operator")
    shared_operator_id = _create_operator_in_db(db_engine, "Shared Operator")

    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Owner Driver", "owner-driver@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Shared Driver", "shared-driver@test.com")

    # --- Owner creates a route ---
    _login(client, owner_driver_id)
    route = client.post("/routes/", json={"route_number": "SHARED-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # --- Shared operator cannot read route before grant ---
    _logout(client)
    _login(client, shared_driver_id)

    not_shared = client.get(f"/routes/{route_id}")
    assert not_shared.status_code == 404

    # --- Owner grants read access ---
    _logout(client)
    _login(client, owner_driver_id)

    grant = client.post(
        f"/routes/{route_id}/share/{shared_operator_id}",
        json={"access_level": "read"},
    )
    assert grant.status_code == 200
    assert grant.json()["access_level"] == "read"

    # --- Shared operator can now read ---
    _logout(client)
    _login(client, shared_driver_id)

    shared_read = client.get(f"/routes/{route_id}")
    assert shared_read.status_code == 200

    # --- Shared operator still cannot write ---
    shared_write = client.put(f"/routes/{route_id}", json={"route_number": "SHARED-1-EDIT"})
    assert shared_write.status_code == 404


# ---------------------------------------------------------------------------
# List endpoints only return operator-owned records
# ---------------------------------------------------------------------------

def test_operator_lists_only_show_owned_records(client, db_engine):
    operator_one_id = _create_operator_in_db(db_engine, "List One")
    operator_two_id = _create_operator_in_db(db_engine, "List Two")

    driver_one_id = _create_driver_in_db(db_engine, operator_one_id, "Driver One", "driver-one@test.com")
    driver_two_id = _create_driver_in_db(db_engine, operator_two_id, "Driver Two", "driver-two@test.com")

    # --- Operator one creates assets ---
    _login(client, driver_one_id)
    extra_driver_one = client.post(
        "/drivers/",
        json={"name": "Extra One", "email": "extra-one@test.com", "phone": "101", "pin": TEST_DRIVER_PIN},
    )
    route_one = client.post("/routes/", json={"route_number": "LIST-ONE"})
    assert extra_driver_one.status_code == 201
    assert route_one.status_code in (200, 201)

    # --- Operator two creates assets ---
    _logout(client)
    _login(client, driver_two_id)
    extra_driver_two = client.post(
        "/drivers/",
        json={"name": "Extra Two", "email": "extra-two@test.com", "phone": "202", "pin": TEST_DRIVER_PIN},
    )
    route_two = client.post("/routes/", json={"route_number": "LIST-TWO"})
    assert extra_driver_two.status_code == 201
    assert route_two.status_code in (200, 201)

    # --- Operator one list only shows its records ---
    _logout(client)
    _login(client, driver_one_id)

    drivers_one = client.get("/drivers/")
    routes_one = client.get("/routes/")

    assert drivers_one.status_code == 200
    assert routes_one.status_code == 200

    driver_ids_one = {d["id"] for d in drivers_one.json()}
    route_ids_one = {r["id"] for r in routes_one.json()}

    assert extra_driver_one.json()["id"] in driver_ids_one
    assert extra_driver_two.json()["id"] not in driver_ids_one
    assert route_one.json()["id"] in route_ids_one
    assert route_two.json()["id"] not in route_ids_one


def test_create_school_under_district_context_sets_district_and_operator(client, db_engine):
    district_id = _create_district_in_db(db_engine, "District Alpha")

    response = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District School", "address": "100 District Way"},
    )
    assert response.status_code == 201

    school_id = response.json()["id"]
    with Session(db_engine) as db:
        school = db.get(School, school_id)
        assert school is not None
        assert school.district_id == district_id
        assert school.operator_id == 1


def test_create_school_under_district_context_returns_404_for_missing_district(client):
    response = client.post(
        "/districts/999999/schools",
        json={"name": "Missing District School", "address": "404 Way"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "District not found"


def test_create_school_under_district_context_ignores_payload_district_id(client, db_engine):
    path_district_id = _create_district_in_db(db_engine, "Path District")
    payload_district_id = _create_district_in_db(db_engine, "Payload District")

    response = client.post(
        f"/districts/{path_district_id}/schools",
        json={
            "name": "Path Wins School",
            "address": "200 Context Way",
            "district_id": payload_district_id,
        },
    )
    assert response.status_code == 201

    school_id = response.json()["id"]
    with Session(db_engine) as db:
        school = db.get(School, school_id)
        assert school is not None
        assert school.district_id == path_district_id
        assert school.district_id != payload_district_id


def test_create_route_under_district_context_sets_district_and_operator(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Route District Alpha")

    response = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-ROUTE-1"},
    )
    assert response.status_code == 201

    route_id = response.json()["id"]
    with Session(db_engine) as db:
        route = db.get(Route, route_id)
        assert route is not None
        assert route.district_id == district_id
        assert route.operator_id == 1


def test_create_route_under_district_context_returns_404_for_missing_district(client):
    response = client.post(
        "/districts/999999/routes",
        json={"route_number": "MISSING-DISTRICT-ROUTE"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "District not found"


def test_create_route_under_district_context_ignores_payload_district_id(client, db_engine):
    path_district_id = _create_district_in_db(db_engine, "Route Path District")
    payload_district_id = _create_district_in_db(db_engine, "Route Payload District")

    response = client.post(
        f"/districts/{path_district_id}/routes",
        json={
            "route_number": "PATH-WINS-ROUTE",
            "district_id": payload_district_id,
        },
    )
    assert response.status_code == 201

    route_id = response.json()["id"]
    with Session(db_engine) as db:
        route = db.get(Route, route_id)
        assert route is not None
        assert route.district_id == path_district_id
        assert route.district_id != payload_district_id


def test_route_duplicate_within_same_district_fails(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Duplicate District Route")

    first = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-DUP-ROUTE"},
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-DUP-ROUTE"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Route number already exists"


def test_same_route_number_across_different_districts_succeeds(client, db_engine):
    district_one_id = _create_district_in_db(db_engine, "Route District One")
    district_two_id = _create_district_in_db(db_engine, "Route District Two")

    first = client.post(
        f"/districts/{district_one_id}/routes",
        json={"route_number": "CROSS-DISTRICT-ROUTE"},
    )
    assert first.status_code == 201

    second = client.post(
        f"/districts/{district_two_id}/routes",
        json={"route_number": "CROSS-DISTRICT-ROUTE"},
    )
    assert second.status_code == 201


def test_legacy_route_duplicate_fallback_still_works_without_district(client):
    first = client.post(
        "/routes/",
        json={"route_number": "LEGACY-DUP-ROUTE"},
    )
    assert first.status_code in (200, 201)

    duplicate = client.post(
        "/routes/",
        json={"route_number": "LEGACY-DUP-ROUTE"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Route number already exists"


def test_district_route_and_legacy_route_can_share_route_number(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Mixed Scope Route District")

    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "MIXED-SCOPE-ROUTE"},
    )
    assert district_route.status_code == 201

    legacy_route = client.post(
        "/routes/",
        json={"route_number": "MIXED-SCOPE-ROUTE"},
    )
    assert legacy_route.status_code in (200, 201)


def test_create_route_with_matching_school_district_succeeds(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Route School Match District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Matched Route School", "address": "300 Match Way"},
    )
    assert school.status_code == 201

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-MATCH-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert route.status_code == 201
    assert school.json()["id"] in route.json()["school_ids"]


def test_create_route_with_mismatched_school_district_fails(client, db_engine):
    school_district_id = _create_district_in_db(db_engine, "Route School Mismatch A")
    route_district_id = _create_district_in_db(db_engine, "Route School Mismatch B")

    school = client.post(
        f"/districts/{school_district_id}/schools",
        json={"name": "Mismatched Route School", "address": "301 Mismatch Way"},
    )
    assert school.status_code == 201

    route = client.post(
        f"/districts/{route_district_id}/routes",
        json={"route_number": "DISTRICT-MISMATCH-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert route.status_code == 400
    assert route.json()["detail"] == "School does not match route district"


def test_assign_route_to_school_with_mismatched_district_fails(client, db_engine):
    school_district_id = _create_district_in_db(db_engine, "Assign Mismatch School District")
    route_district_id = _create_district_in_db(db_engine, "Assign Mismatch Route District")

    school = client.post(
        f"/districts/{school_district_id}/schools",
        json={"name": "Assign Mismatch School", "address": "302 Assign Way"},
    )
    assert school.status_code == 201

    route = client.post(
        f"/districts/{route_district_id}/routes",
        json={"route_number": "ASSIGN-MISMATCH-ROUTE"},
    )
    assert route.status_code == 201

    assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert assign.status_code == 400
    assert assign.json()["detail"] == "School does not match route district"


def test_assign_route_to_school_with_matching_district_succeeds(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Assign Match District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Assign Match School", "address": "303 Assign Match Way"},
    )
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "ASSIGN-MATCH-ROUTE"},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert assign.status_code == 200

    detail = client.get(f"/routes/{route.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["schools"] == [
        {"school_id": school.json()["id"], "school_name": "Assign Match School"}
    ]


def test_assigning_same_route_to_school_twice_does_not_duplicate_link(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Assign Duplicate District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Assign Duplicate School", "address": "304 Duplicate Way"},
    )
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "ASSIGN-DUPLICATE-ROUTE"},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    first_assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    second_assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert first_assign.status_code == 200
    assert second_assign.status_code == 200

    detail = client.get(f"/routes/{route.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["schools"] == [
        {"school_id": school.json()["id"], "school_name": "Assign Duplicate School"}
    ]


def test_unassign_route_from_school_succeeds(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Unassign District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Unassign School", "address": "305 Unassign Way"},
    )
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "UNASSIGN-ROUTE"},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert assign.status_code == 200

    unassign = client.delete(f"/schools/{school.json()['id']}/unassign_route/{route.json()['id']}")
    assert unassign.status_code == 200

    detail = client.get(f"/routes/{route.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["schools"] == []


def test_unassigning_non_linked_route_from_school_is_safe_no_op(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Unassign Noop District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Unassign Noop School", "address": "306 Noop Way"},
    )
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "UNASSIGN-NOOP-ROUTE"},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    unassign = client.delete(f"/schools/{school.json()['id']}/unassign_route/{route.json()['id']}")
    assert unassign.status_code == 200

    detail = client.get(f"/routes/{route.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["schools"] == []


def test_create_student_under_district_context_sets_district_and_operator(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Student District Alpha")

    school_response = client.post(
        "/schools/",
        json={"name": "Student District School", "address": "10 Student Way"},
    )
    assert school_response.status_code == 201
    school_id = school_response.json()["id"]

    response = client.post(
        f"/districts/{district_id}/students",
        json={"name": "District Student", "grade": "4", "school_id": school_id},
    )
    assert response.status_code == 201

    student_id = response.json()["id"]
    with Session(db_engine) as db:
        student = db.get(Student, student_id)
        assert student is not None
        assert student.district_id == district_id
        assert student.operator_id == 1


def test_create_student_under_district_context_returns_404_for_missing_district(client):
    school_response = client.post(
        "/schools/",
        json={"name": "Missing District Student School", "address": "11 Student Way"},
    )
    assert school_response.status_code == 201
    school_id = school_response.json()["id"]

    response = client.post(
        "/districts/999999/students",
        json={"name": "Missing District Student", "grade": "5", "school_id": school_id},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "District not found"


def test_create_student_under_district_context_ignores_payload_district_id(client, db_engine):
    path_district_id = _create_district_in_db(db_engine, "Student Path District")
    payload_district_id = _create_district_in_db(db_engine, "Student Payload District")

    school_response = client.post(
        "/schools/",
        json={"name": "Student Path School", "address": "12 Student Way"},
    )
    assert school_response.status_code == 201
    school_id = school_response.json()["id"]

    response = client.post(
        f"/districts/{path_district_id}/students",
        json={
            "name": "Path Wins Student",
            "grade": "6",
            "school_id": school_id,
            "district_id": payload_district_id,
        },
    )
    assert response.status_code == 201

    student_id = response.json()["id"]
    with Session(db_engine) as db:
        student = db.get(Student, student_id)
        assert student is not None
        assert student.district_id == path_district_id
        assert student.district_id != payload_district_id


def test_create_student_with_matching_school_district_succeeds(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Student School Match District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Matched Student School", "address": "303 Student Match Way"},
    )
    assert school.status_code == 201

    student = client.post(
        f"/districts/{district_id}/students",
        json={"name": "Matched Student", "grade": "5", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201


def test_create_student_with_mismatched_school_district_fails(client, db_engine):
    school_district_id = _create_district_in_db(db_engine, "Student School Mismatch A")
    student_district_id = _create_district_in_db(db_engine, "Student School Mismatch B")

    school = client.post(
        f"/districts/{school_district_id}/schools",
        json={"name": "Mismatched Student School", "address": "304 Student Mismatch Way"},
    )
    assert school.status_code == 201

    student = client.post(
        f"/districts/{student_district_id}/students",
        json={"name": "Mismatched Student", "grade": "6", "school_id": school.json()["id"]},
    )
    assert student.status_code == 400
    assert student.json()["detail"] == "School does not match student district"


def test_create_student_with_mismatched_route_district_fails(client, db_engine):
    school_district_id = _create_district_in_db(db_engine, "Student Route Mismatch School District")
    route_district_id = _create_district_in_db(db_engine, "Student Route Mismatch Route District")

    school = client.post(
        f"/districts/{school_district_id}/schools",
        json={"name": "Student Route Mismatch School", "address": "305 Route Mismatch Way"},
    )
    assert school.status_code == 201

    route = client.post(
        f"/districts/{route_district_id}/routes",
        json={"route_number": "STUDENT-ROUTE-MISMATCH"},
    )
    assert route.status_code == 201

    student = client.post(
        "/students/",
        json={
            "name": "Student Route Mismatch",
            "grade": "7",
            "school_id": school.json()["id"],
            "route_id": route.json()["id"],
            "district_id": school_district_id,
        },
    )
    assert student.status_code == 400
    assert student.json()["detail"] == "Student does not match route district"


def test_legacy_route_school_assignment_still_works_without_district_ids(client):
    school = client.post(
        "/schools/",
        json={"name": "Legacy Route School", "address": "306 Legacy Way"},
    )
    assert school.status_code == 201

    route = client.post(
        "/routes/",
        json={"route_number": "LEGACY-ROUTE-SCHOOL"},
    )
    assert route.status_code in (200, 201)

    assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert assign.status_code == 200


def test_legacy_student_route_link_still_works_without_district_ids(client):
    school = client.post(
        "/schools/",
        json={"name": "Legacy Student School", "address": "307 Legacy Student Way"},
    )
    assert school.status_code == 201

    route = client.post(
        "/routes/",
        json={"route_number": "LEGACY-STUDENT-ROUTE"},
    )
    assert route.status_code in (200, 201)

    assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert assign.status_code == 200

    student = client.post(
        "/students/",
        json={
            "name": "Legacy Student",
            "grade": "8",
            "school_id": school.json()["id"],
            "route_id": route.json()["id"],
        },
    )
    assert student.status_code == 201


def test_school_list_still_returns_operator_owned_schools(client):
    owned_school = client.post(
        "/schools/",
        json={"name": "Owned School Visible", "address": "20 School Way"},
    )
    assert owned_school.status_code == 201

    schools = client.get("/schools/")
    assert schools.status_code == 200

    school_ids = {school["id"] for school in schools.json()}
    assert owned_school.json()["id"] in school_ids


def test_school_list_returns_district_owned_schools(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Visible District School")

    district_school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District Visible School", "address": "21 School Way"},
    )
    assert district_school.status_code == 201

    schools = client.get("/schools/")
    assert schools.status_code == 200

    school_ids = {school["id"] for school in schools.json()}
    assert district_school.json()["id"] in school_ids


def test_school_list_returns_combined_operator_and_district_owned_schools(client, db_engine):
    owned_school = client.post(
        "/schools/",
        json={"name": "Combined Owned School", "address": "22 School Way"},
    )
    assert owned_school.status_code == 201

    district_id = _create_district_in_db(db_engine, "Combined District")
    district_school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Combined District School", "address": "23 School Way"},
    )
    assert district_school.status_code == 201

    schools = client.get("/schools/")
    assert schools.status_code == 200

    school_ids = {school["id"] for school in schools.json()}
    assert owned_school.json()["id"] in school_ids
    assert district_school.json()["id"] in school_ids


def test_school_detail_still_returns_operator_owned_school(client):
    owned_school = client.post(
        "/schools/",
        json={"name": "Owned School Detail", "address": "24 School Way"},
    )
    assert owned_school.status_code == 201

    school = client.get(f"/schools/{owned_school.json()['id']}")
    assert school.status_code == 200
    assert school.json()["id"] == owned_school.json()["id"]


def test_school_detail_returns_district_owned_school(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Detail District School")

    district_school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District School Detail", "address": "25 School Way"},
    )
    assert district_school.status_code == 201

    school = client.get(f"/schools/{district_school.json()['id']}")
    assert school.status_code == 200
    assert school.json()["id"] == district_school.json()["id"]


def test_school_detail_returns_404_for_missing_school(client):
    school = client.get("/schools/999999")
    assert school.status_code == 404
    assert school.json()["detail"] == "School not found"


def test_school_update_succeeds_via_valid_shared_planning_access(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "School Update Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "School Update Shared")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "School Update Owner Driver", "school-update-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "School Update Shared Driver", "school-update-shared@test.com")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Update School", "address": "50 Update Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "SHARED-SCHOOL-UPDATE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert assign.status_code == 200
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    update = client.put(
        f"/schools/{school_id}",
        json={"name": "Shared Update School Renamed", "address": "50 Update Way"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "Shared Update School Renamed"


def test_school_delete_succeeds_via_valid_shared_planning_access(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "School Delete Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "School Delete Shared")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "School Delete Owner Driver", "school-delete-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "School Delete Shared Driver", "school-delete-shared@test.com")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Delete School", "address": "51 Delete Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "SHARED-SCHOOL-DELETE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert assign.status_code == 200
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    delete = client.delete(f"/schools/{school_id}")
    assert delete.status_code == 204

    read_back = client.get(f"/schools/{school_id}")
    assert read_back.status_code == 404


def test_route_list_still_returns_operator_owned_routes(client):
    owned_route = client.post(
        "/routes/",
        json={"route_number": "OWNED-ROUTE-VISIBLE"},
    )
    assert owned_route.status_code in (200, 201)

    routes = client.get("/routes/")
    assert routes.status_code == 200

    route_ids = {route["id"] for route in routes.json()}
    assert owned_route.json()["id"] in route_ids


def test_route_list_returns_district_owned_routes(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Visible District Route")

    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-ROUTE-VISIBLE"},
    )
    assert district_route.status_code == 201

    routes = client.get("/routes/")
    assert routes.status_code == 200

    route_ids = {route["id"] for route in routes.json()}
    assert district_route.json()["id"] in route_ids


def test_route_list_returns_combined_operator_and_district_owned_routes(client, db_engine):
    owned_route = client.post(
        "/routes/",
        json={"route_number": "COMBINED-OWNED-ROUTE"},
    )
    assert owned_route.status_code in (200, 201)

    district_id = _create_district_in_db(db_engine, "Combined District Route")
    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "COMBINED-DISTRICT-ROUTE"},
    )
    assert district_route.status_code == 201

    routes = client.get("/routes/")
    assert routes.status_code == 200

    route_ids = {route["id"] for route in routes.json()}
    assert owned_route.json()["id"] in route_ids
    assert district_route.json()["id"] in route_ids


def test_route_detail_still_returns_operator_owned_route(client):
    owned_route = client.post(
        "/routes/",
        json={"route_number": "OWNED-ROUTE-DETAIL"},
    )
    assert owned_route.status_code in (200, 201)

    route = client.get(f"/routes/{owned_route.json()['id']}")
    assert route.status_code == 200
    assert route.json()["id"] == owned_route.json()["id"]


def test_route_detail_returns_district_owned_route(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Detail District Route")

    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-ROUTE-DETAIL"},
    )
    assert district_route.status_code == 201

    route = client.get(f"/routes/{district_route.json()['id']}")
    assert route.status_code == 200
    assert route.json()["id"] == district_route.json()["id"]


def test_route_detail_returns_404_for_missing_route(client):
    route = client.get("/routes/999999")
    assert route.status_code == 404
    assert route.json()["detail"] == "Route not found"


def test_district_owned_route_is_not_automatically_visible_to_other_operator(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "District Route Owner")
    other_operator_id = _create_operator_in_db(db_engine, "District Route Other")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "District Route Owner Driver", "district-route-owner@test.com")
    other_driver_id = _create_driver_in_db(db_engine, other_operator_id, "District Route Other Driver", "district-route-other@test.com")
    district_id = _create_district_in_db(db_engine, "District Route Hidden")

    _logout(client)
    _login(client, owner_driver_id)
    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "DISTRICT-HIDDEN-ROUTE"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    _logout(client)
    _login(client, other_driver_id)

    route_list = client.get("/routes/")
    assert route_list.status_code == 200
    route_ids = {item["id"] for item in route_list.json()}
    assert route_id not in route_ids

    route_detail = client.get(f"/routes/{route_id}")
    assert route_detail.status_code == 404


def test_shared_route_remains_visible_in_route_list(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Shared Route List Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Shared Route List Reader")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Shared Route List Owner Driver", "shared-route-list-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Shared Route List Reader Driver", "shared-route-list-reader@test.com")

    _logout(client)
    _login(client, owner_driver_id)
    route = client.post("/routes/", json={"route_number": "SHARED-ROUTE-LIST"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    route_list = client.get("/routes/")
    assert route_list.status_code == 200
    route_ids = {item["id"] for item in route_list.json()}
    assert route_id in route_ids


def test_student_list_still_returns_operator_owned_students(client):
    school = client.post(
        "/schools/",
        json={"name": "Owned Student School", "address": "30 Student Way"},
    )
    assert school.status_code == 201

    owned_student = client.post(
        "/students/",
        json={"name": "Owned Student Visible", "grade": "3", "school_id": school.json()["id"]},
    )
    assert owned_student.status_code == 201

    students = client.get("/students/")
    assert students.status_code == 200

    student_ids = {student["id"] for student in students.json()}
    assert owned_student.json()["id"] in student_ids


def test_student_list_returns_district_owned_students(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Visible District Student")

    school = client.post(
        "/schools/",
        json={"name": "District Student School", "address": "31 Student Way"},
    )
    assert school.status_code == 201

    district_student = client.post(
        f"/districts/{district_id}/students",
        json={"name": "District Student Visible", "grade": "4", "school_id": school.json()["id"]},
    )
    assert district_student.status_code == 201

    students = client.get("/students/")
    assert students.status_code == 200

    student_ids = {student["id"] for student in students.json()}
    assert district_student.json()["id"] in student_ids


def test_student_list_returns_combined_operator_and_district_owned_students(client, db_engine):
    school = client.post(
        "/schools/",
        json={"name": "Combined Student School", "address": "32 Student Way"},
    )
    assert school.status_code == 201

    owned_student = client.post(
        "/students/",
        json={"name": "Combined Owned Student", "grade": "5", "school_id": school.json()["id"]},
    )
    assert owned_student.status_code == 201

    district_id = _create_district_in_db(db_engine, "Combined District Student")
    district_student = client.post(
        f"/districts/{district_id}/students",
        json={"name": "Combined District Student", "grade": "6", "school_id": school.json()["id"]},
    )
    assert district_student.status_code == 201

    students = client.get("/students/")
    assert students.status_code == 200

    student_ids = {student["id"] for student in students.json()}
    assert owned_student.json()["id"] in student_ids
    assert district_student.json()["id"] in student_ids


def test_district_owned_school_requires_route_access_for_other_operator(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "District School Owner")
    other_operator_id = _create_operator_in_db(db_engine, "District School Other")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "District School Owner Driver", "district-school-owner@test.com")
    other_driver_id = _create_driver_in_db(db_engine, other_operator_id, "District School Other Driver", "district-school-other@test.com")
    district_id = _create_district_in_db(db_engine, "District School Hidden")

    _logout(client)
    _login(client, owner_driver_id)
    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District Hidden School", "address": "40 Hidden School Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    _logout(client)
    _login(client, other_driver_id)

    school_list = client.get("/schools/")
    assert school_list.status_code == 200
    school_ids = {item["id"] for item in school_list.json()}
    assert school_id not in school_ids

    school_detail = client.get(f"/schools/{school_id}")
    assert school_detail.status_code == 404


def test_school_becomes_visible_when_linked_to_shared_route(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Shared School Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Shared School Reader")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Shared School Owner Driver", "shared-school-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Shared School Reader Driver", "shared-school-reader@test.com")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Route School", "address": "41 Shared School Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "SHARED-SCHOOL-ROUTE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert assign.status_code == 200
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    school_list = client.get("/schools/")
    assert school_list.status_code == 200
    school_ids = {item["id"] for item in school_list.json()}
    assert school_id in school_ids

    school_detail = client.get(f"/schools/{school_id}")
    assert school_detail.status_code == 200
    assert school_detail.json()["id"] == school_id


def test_district_owned_student_requires_accessible_school_or_route_for_other_operator(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "District Student Owner")
    other_operator_id = _create_operator_in_db(db_engine, "District Student Other")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "District Student Owner Driver", "district-student-owner@test.com")
    other_driver_id = _create_driver_in_db(db_engine, other_operator_id, "District Student Other Driver", "district-student-other@test.com")
    district_id = _create_district_in_db(db_engine, "District Student Hidden")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District Student Hidden School", "address": "42 Hidden Student Way"},
    )
    assert school.status_code == 201

    student = client.post(
        f"/districts/{district_id}/students",
        json={"name": "District Hidden Student", "grade": "7", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    _logout(client)
    _login(client, other_driver_id)

    student_list = client.get("/students/")
    assert student_list.status_code == 200
    student_ids = {item["id"] for item in student_list.json()}
    assert student_id not in student_ids

    student_detail = client.get(f"/students/{student_id}")
    assert student_detail.status_code == 404


def test_student_becomes_visible_through_shared_route_school_access(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Shared Student Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Shared Student Reader")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Shared Student Owner Driver", "shared-student-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Shared Student Reader Driver", "shared-student-reader@test.com")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Student School", "address": "43 Shared Student Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "SHARED-STUDENT-ROUTE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert assign.status_code == 200

    student = client.post(
        "/students/",
        json={"name": "Shared Student Visible", "grade": "8", "school_id": school_id},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    student_list = client.get("/students/")
    assert student_list.status_code == 200
    student_ids = {item["id"] for item in student_list.json()}
    assert student_id in student_ids

    student_detail = client.get(f"/students/{student_id}")
    assert student_detail.status_code == 200
    assert student_detail.json()["id"] == student_id


def test_student_create_succeeds_via_valid_shared_district_planning_access(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Student Create Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Student Create Shared")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Student Create Owner Driver", "student-create-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Student Create Shared Driver", "student-create-shared@test.com")
    district_id = _create_district_in_db(db_engine, "Shared Student Create District")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Shared District Student School", "address": "52 Student Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "SHARED-DISTRICT-STUDENT-ROUTE"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert assign.status_code == 200
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    student = client.post(
        "/students/",
        json={
            "name": "Shared District Student",
            "grade": "9",
            "school_id": school_id,
            "route_id": route_id,
            "district_id": district_id,
        },
    )
    assert student.status_code == 201


def test_student_assignment_update_succeeds_via_valid_shared_district_planning_access(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Student Update Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Student Update Shared")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Student Update Owner Driver", "student-update-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Student Update Shared Driver", "student-update-shared@test.com")
    district_id = _create_district_in_db(db_engine, "Shared Student Update District")

    _logout(client)
    _login(client, owner_driver_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Shared Update Student School", "address": "53 Student Update Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "SHARED-DISTRICT-STUDENT-UPDATE"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    assign = client.post(f"/schools/{school_id}/assign_route/{route_id}")
    assert assign.status_code == 200

    run = client.post(
        f"/routes/{route_id}/runs",
        json={"run_type": "AM"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"name": "Shared Update Stop", "sequence": 1, "type": "pickup"},
    )
    assert stop.status_code == 201
    stop_id = stop.json()["id"]

    student = client.post(
        f"/districts/{district_id}/students",
        json={"name": "Shared Update Student", "grade": "10", "school_id": school_id},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_driver_id)

    update = client.put(
        f"/students/{student_id}/assignment",
        json={"route_id": route_id, "run_id": run_id, "stop_id": stop_id},
    )
    assert update.status_code == 200
    assert update.json()["route_id"] == route_id
    assert update.json()["stop_id"] == stop_id


def test_student_assignment_update_fails_for_mismatched_district_route(client, db_engine):
    district_one_id = _create_district_in_db(db_engine, "Student Update Mismatch School District")
    district_two_id = _create_district_in_db(db_engine, "Student Update Mismatch Route District")

    school = client.post(
        f"/districts/{district_one_id}/schools",
        json={"name": "Mismatch Update School", "address": "54 Mismatch Update Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    student = client.post(
        f"/districts/{district_one_id}/students",
        json={"name": "Mismatch Update Student", "grade": "11", "school_id": school_id},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    route = client.post(
        f"/districts/{district_two_id}/routes",
        json={"route_number": "MISMATCH-STUDENT-UPDATE-ROUTE"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    run = client.post(
        f"/routes/{route_id}/runs",
        json={"run_type": "AM"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"name": "Mismatch Update Stop", "sequence": 1, "type": "pickup"},
    )
    assert stop.status_code == 201
    stop_id = stop.json()["id"]

    update = client.put(
        f"/students/{student_id}/assignment",
        json={"route_id": route_id, "run_id": run_id, "stop_id": stop_id},
    )
    assert update.status_code == 400
    assert update.json()["detail"] == "Student does not match route district"


# ---------------------------------------------------------------------------
# Route cascade planning endpoints
# ---------------------------------------------------------------------------

def test_create_and_list_runs_under_route(client):
    route = client.post("/routes/", json={"route_number": "CASCADE-RUN-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    create = client.post(
        f"/routes/{route_id}/runs",
        json={"run_type": "AM"},
    )
    assert create.status_code == 201
    run_id = create.json()["id"]
    assert create.json()["route_id"] == route_id

    listing = client.get(f"/routes/{route_id}/runs")
    assert listing.status_code == 200
    assert {run["id"] for run in listing.json()} == {run_id}


def test_create_and_list_stops_under_route_sets_route_identity(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Cascade Stop District")
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "CASCADE-STOP-1"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    run = client.post(
        f"/routes/{route_id}/runs",
        json={"run_type": "PM"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    create = client.post(
        f"/routes/{route_id}/stops",
        json={"run_id": run_id, "type": "pickup", "sequence": 1, "name": "Cascade Stop"},
    )
    assert create.status_code == 201
    stop_id = create.json()["id"]
    assert create.json()["run_id"] == run_id

    listing = client.get(f"/routes/{route_id}/stops")
    assert listing.status_code == 200
    assert {stop["id"] for stop in listing.json()} == {stop_id}

    with Session(db_engine) as db:
        stop = db.get(Stop, stop_id)
        assert stop is not None
        assert stop.route_id == route_id
        assert stop.district_id == district_id


def test_route_stop_creation_fails_when_run_belongs_to_other_route(client):
    route_one = client.post("/routes/", json={"route_number": "CASCADE-STOP-A"})
    route_two = client.post("/routes/", json={"route_number": "CASCADE-STOP-B"})
    assert route_one.status_code in (200, 201)
    assert route_two.status_code in (200, 201)

    run = client.post(
        f"/routes/{route_one.json()['id']}/runs",
        json={"run_type": "AM"},
    )
    assert run.status_code == 201

    create = client.post(
        f"/routes/{route_two.json()['id']}/stops",
        json={"run_id": run.json()["id"], "type": "pickup", "sequence": 1},
    )
    assert create.status_code == 400
    assert create.json()["detail"] == "Run does not belong to route"


def test_create_and_list_students_under_route_sets_route_and_district(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Cascade Student District")
    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Cascade School", "address": "100 Cascade Way"},
    )
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "CASCADE-STUDENT-1"},
    )
    assert school.status_code == 201
    assert route.status_code == 201
    route_id = route.json()["id"]

    create = client.post(
        f"/routes/{route_id}/students",
        json={
            "name": "Cascade Student",
            "grade": "4",
            "school_id": school.json()["id"],
        },
    )
    assert create.status_code == 201
    student_id = create.json()["id"]
    assert create.json()["route_id"] == route_id

    listing = client.get(f"/routes/{route_id}/students")
    assert listing.status_code == 200
    assert {student["id"] for student in listing.json()} == {student_id}

    with Session(db_engine) as db:
        student = db.get(Student, student_id)
        assert student is not None
        assert student.route_id == route_id
        assert student.district_id == district_id


def test_route_student_creation_fails_for_mismatched_school_district(client, db_engine):
    district_one_id = _create_district_in_db(db_engine, "Cascade Student District One")
    district_two_id = _create_district_in_db(db_engine, "Cascade Student District Two")

    school = client.post(
        f"/districts/{district_one_id}/schools",
        json={"name": "Mismatch Cascade School", "address": "10 Mismatch Way"},
    )
    route = client.post(
        f"/districts/{district_two_id}/routes",
        json={"route_number": "CASCADE-STUDENT-MISMATCH"},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    create = client.post(
        f"/routes/{route.json()['id']}/students",
        json={
            "name": "Mismatch Student",
            "grade": "5",
            "school_id": school.json()["id"],
        },
    )
    assert create.status_code == 400
    assert create.json()["detail"] == "School does not match student district"


def test_route_cascade_endpoints_return_404_for_missing_route(client):
    create_run = client.post("/routes/999999/runs", json={"run_type": "AM"})
    list_runs = client.get("/routes/999999/runs")
    create_stop = client.post(
        "/routes/999999/stops",
        json={"run_id": 1, "type": "pickup", "sequence": 1},
    )
    list_stops = client.get("/routes/999999/stops")
    create_student = client.post(
        "/routes/999999/students",
        json={"name": "Missing Route Student", "school_id": 1},
    )
    list_students = client.get("/routes/999999/students")

    for response in (create_run, list_runs, create_stop, list_stops, create_student, list_students):
        assert response.status_code == 404


def test_update_route_run_under_correct_route_succeeds(client):
    route = client.post("/routes/", json={"route_number": "CASCADE-RUN-UPDATE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code == 201
    run_id = run.json()["id"]

    update = client.put(
        f"/routes/{route_id}/runs/{run_id}",
        json={
            "run_type": "PM",
            "scheduled_start_time": "08:00:00",
            "scheduled_end_time": "09:00:00",
        },
    )
    assert update.status_code == 200
    assert update.json()["id"] == run_id
    assert update.json()["route_id"] == route_id
    assert update.json()["run_type"] == "PM"


def test_update_route_run_under_wrong_route_returns_404(client):
    route_one = client.post("/routes/", json={"route_number": "CASCADE-RUN-WRONG-A"})
    route_two = client.post("/routes/", json={"route_number": "CASCADE-RUN-WRONG-B"})
    assert route_one.status_code in (200, 201)
    assert route_two.status_code in (200, 201)

    run = client.post(f"/routes/{route_one.json()['id']}/runs", json={"run_type": "AM"})
    assert run.status_code == 201

    update = client.put(
        f"/routes/{route_two.json()['id']}/runs/{run.json()['id']}",
        json={"run_type": "PM"},
    )
    assert update.status_code == 404


def test_delete_route_run_under_correct_route_succeeds(client, db_engine):
    route = client.post("/routes/", json={"route_number": "CASCADE-RUN-DELETE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code == 201
    run_id = run.json()["id"]

    delete = client.delete(f"/routes/{route_id}/runs/{run_id}")
    assert delete.status_code == 204

    with Session(db_engine) as db:
        assert db.get(Run, run_id) is None


def test_delete_route_run_under_wrong_route_returns_404(client):
    route_one = client.post("/routes/", json={"route_number": "CASCADE-RUN-DEL-WRONG-A"})
    route_two = client.post("/routes/", json={"route_number": "CASCADE-RUN-DEL-WRONG-B"})
    assert route_one.status_code in (200, 201)
    assert route_two.status_code in (200, 201)

    run = client.post(f"/routes/{route_one.json()['id']}/runs", json={"run_type": "AM"})
    assert run.status_code == 201

    delete = client.delete(f"/routes/{route_two.json()['id']}/runs/{run.json()['id']}")
    assert delete.status_code == 404


def test_update_route_stop_under_correct_route_succeeds(client):
    route = client.post("/routes/", json={"route_number": "CASCADE-STOP-UPDATE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code == 201
    stop = client.post(
        f"/routes/{route_id}/stops",
        json={"run_id": run.json()["id"], "type": "pickup", "sequence": 1, "name": "Old Stop"},
    )
    assert stop.status_code == 201
    stop_id = stop.json()["id"]

    update = client.put(
        f"/routes/{route_id}/stops/{stop_id}",
        json={"name": "New Stop Name", "sequence": 1},
    )
    assert update.status_code == 200
    assert update.json()["id"] == stop_id
    assert update.json()["name"] == "New Stop Name"


def test_update_route_stop_under_wrong_route_returns_404(client):
    route_one = client.post("/routes/", json={"route_number": "CASCADE-STOP-UP-WRONG-A"})
    route_two = client.post("/routes/", json={"route_number": "CASCADE-STOP-UP-WRONG-B"})
    assert route_one.status_code in (200, 201)
    assert route_two.status_code in (200, 201)

    run = client.post(f"/routes/{route_one.json()['id']}/runs", json={"run_type": "AM"})
    stop = client.post(
        f"/routes/{route_one.json()['id']}/stops",
        json={"run_id": run.json()["id"], "type": "pickup", "sequence": 1},
    )
    assert run.status_code == 201
    assert stop.status_code == 201

    update = client.put(
        f"/routes/{route_two.json()['id']}/stops/{stop.json()['id']}",
        json={"name": "Wrong Route Stop"},
    )
    assert update.status_code == 404


def test_delete_route_stop_under_correct_route_succeeds(client, db_engine):
    route = client.post("/routes/", json={"route_number": "CASCADE-STOP-DELETE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    stop = client.post(
        f"/routes/{route_id}/stops",
        json={"run_id": run.json()["id"], "type": "pickup", "sequence": 1},
    )
    assert run.status_code == 201
    assert stop.status_code == 201
    stop_id = stop.json()["id"]

    delete = client.delete(f"/routes/{route_id}/stops/{stop_id}")
    assert delete.status_code == 204

    with Session(db_engine) as db:
        assert db.get(Stop, stop_id) is None


def test_delete_route_stop_under_wrong_route_returns_404(client):
    route_one = client.post("/routes/", json={"route_number": "CASCADE-STOP-DEL-WRONG-A"})
    route_two = client.post("/routes/", json={"route_number": "CASCADE-STOP-DEL-WRONG-B"})
    assert route_one.status_code in (200, 201)
    assert route_two.status_code in (200, 201)

    run = client.post(f"/routes/{route_one.json()['id']}/runs", json={"run_type": "AM"})
    stop = client.post(
        f"/routes/{route_one.json()['id']}/stops",
        json={"run_id": run.json()["id"], "type": "pickup", "sequence": 1},
    )
    assert run.status_code == 201
    assert stop.status_code == 201

    delete = client.delete(f"/routes/{route_two.json()['id']}/stops/{stop.json()['id']}")
    assert delete.status_code == 404


def test_remove_student_from_route_succeeds(client, db_engine):
    route = client.post("/routes/", json={"route_number": "CASCADE-STUDENT-REMOVE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    school = client.post("/schools/", json={"name": "Route Student Remove School", "address": "1 Remove Way"})
    assert school.status_code == 201

    student = client.post(
        f"/routes/{route_id}/students",
        json={"name": "Route Student", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    delete = client.delete(f"/routes/{route_id}/students/{student_id}")
    assert delete.status_code == 204

    with Session(db_engine) as db:
        student_row = db.get(Student, student_id)
        assert student_row is not None
        assert student_row.route_id is None
        assert student_row.stop_id is None


def test_remove_student_from_wrong_route_returns_404(client):
    route_one = client.post("/routes/", json={"route_number": "CASCADE-STUDENT-WRONG-A"})
    route_two = client.post("/routes/", json={"route_number": "CASCADE-STUDENT-WRONG-B"})
    school = client.post("/schools/", json={"name": "Route Student Wrong School", "address": "2 Wrong Way"})
    assert route_one.status_code in (200, 201)
    assert route_two.status_code in (200, 201)
    assert school.status_code == 201

    student = client.post(
        f"/routes/{route_one.json()['id']}/students",
        json={"name": "Wrong Route Student", "school_id": school.json()["id"]},
    )
    assert student.status_code == 201

    delete = client.delete(f"/routes/{route_two.json()['id']}/students/{student.json()['id']}")
    assert delete.status_code == 404


# ---------------------------------------------------------------------------
# C1: Pretrip endpoints are operator-scoped
# ---------------------------------------------------------------------------

def _pretrip_payload(bus_number: str, license_plate: str) -> dict:
    return {
        "bus_number": bus_number,
        "license_plate": license_plate,
        "driver_name": "Test Driver",
        "inspection_date": date.today().isoformat(),
        "inspection_time": "06:00:00",
        "odometer": 1000,
        "inspection_place": "Test Yard",
        "use_type": "school_bus",
        "brakes_checked": True,
        "lights_checked": True,
        "tires_checked": True,
        "emergency_equipment_checked": True,
        "fit_for_duty": "yes",
        "no_defects": True,
        "signature": "test-sig",
        "defects": [],
    }


def test_pretrip_create_and_read_are_operator_scoped(client, db_engine):
    operator_a_id = _create_operator_in_db(db_engine, "Pretrip Operator A")
    operator_b_id = _create_operator_in_db(db_engine, "Pretrip Operator B")

    driver_a_id = _create_driver_in_db(db_engine, operator_a_id, "Driver A", "driver-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, operator_b_id, "Driver B", "driver-b@test.com")

    # --- Operator A creates a bus and a pretrip ---
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "PT-BUS-A", "license_plate": "PT-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)
    bus_a_id = bus_a.json()["id"]

    pretrip_a = client.post("/pretrips/", json=_pretrip_payload("PT-BUS-A", "PT-A-001"))
    assert pretrip_a.status_code in (200, 201)
    pretrip_a_id = pretrip_a.json()["id"]

    # --- Operator B cannot read operator A's pretrip by ID ---
    _logout(client)
    _login(client, driver_b_id)

    read_cross = client.get(f"/pretrips/{pretrip_a_id}")
    assert read_cross.status_code == 404, (
        f"Expected 404 for cross-operator pretrip GET, got {read_cross.status_code}"
    )

    # --- Operator B list does NOT include operator A's pretrip ---
    list_b = client.get("/pretrips/")
    assert list_b.status_code == 200
    listed_ids = {p["id"] for p in list_b.json()}
    assert pretrip_a_id not in listed_ids, "Operator B's list must not include Operator A's pretrip"

    # --- Operator B cannot look up operator A's bus by bus_id ---
    read_today = client.get(f"/pretrips/bus/{bus_a_id}/today")
    assert read_today.status_code == 404, (
        f"Expected 404 for cross-operator bus pretrip today, got {read_today.status_code}"
    )

    list_bus_b = client.get(f"/pretrips/bus/{bus_a_id}")
    assert list_bus_b.status_code == 404, (
        f"Expected 404 for cross-operator bus pretrip list, got {list_bus_b.status_code}"
    )


def test_pretrip_correct_is_operator_scoped(client, db_engine):
    operator_a_id = _create_operator_in_db(db_engine, "Correct Operator A")
    operator_b_id = _create_operator_in_db(db_engine, "Correct Operator B")

    driver_a_id = _create_driver_in_db(db_engine, operator_a_id, "Correct Driver A", "correct-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, operator_b_id, "Correct Driver B", "correct-b@test.com")

    # Operator A creates bus and pretrip
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "CORR-BUS-A", "license_plate": "CORR-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)

    pretrip_a = client.post("/pretrips/", json=_pretrip_payload("CORR-BUS-A", "CORR-A-001"))
    assert pretrip_a.status_code in (200, 201)
    pretrip_a_id = pretrip_a.json()["id"]

    # Operator B tries to correct operator A's pretrip — must get 404
    _logout(client)
    _login(client, driver_b_id)

    correct_payload = _pretrip_payload("CORR-BUS-A", "CORR-A-001")
    correct_payload["corrected_by"] = "attacker"
    correct_cross = client.put(f"/pretrips/{pretrip_a_id}/correct", json=correct_payload)
    assert correct_cross.status_code == 404, (
        f"Expected 404 for cross-operator pretrip correct, got {correct_cross.status_code}"
    )


# ---------------------------------------------------------------------------
# H2: Pretrip uniqueness check cannot be abused across operators
# ---------------------------------------------------------------------------

def test_pretrip_uniqueness_cannot_block_another_operator(client, db_engine):
    operator_a_id = _create_operator_in_db(db_engine, "Unique Block A")
    operator_b_id = _create_operator_in_db(db_engine, "Unique Block B")

    driver_a_id = _create_driver_in_db(db_engine, operator_a_id, "Uniq Driver A", "uniq-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, operator_b_id, "Uniq Driver B", "uniq-b@test.com")

    # Operator A creates its bus
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "UNIQ-BUS-A", "license_plate": "UNIQ-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)
    bus_a_id = bus_a.json()["id"]

    # Operator B tries to create a pretrip for Operator A's bus_id — must be 404 (bus not found in B's scope)
    _logout(client)
    _login(client, driver_b_id)

    attack_payload = _pretrip_payload("UNIQ-BUS-A", "UNIQ-A-001")
    attack_payload["bus_id"] = bus_a_id
    del attack_payload["bus_number"]  # Force bus_id resolution path

    attack = client.post("/pretrips/", json=attack_payload)
    assert attack.status_code == 404, (
        f"Expected 404 (bus not found in B's scope), got {attack.status_code}. "
        "Operator B must not be able to trigger Operator A's uniqueness constraint."
    )

    # Operator A can still file its own pretrip without conflict
    _logout(client)
    _login(client, driver_a_id)

    own_pretrip = client.post("/pretrips/", json=_pretrip_payload("UNIQ-BUS-A", "UNIQ-A-001"))
    assert own_pretrip.status_code in (200, 201), (
        f"Operator A's own pretrip creation failed after the cross-operator attack: {own_pretrip.text}"
    )


# ---------------------------------------------------------------------------
# H1: Bus uniqueness is per-operator, not global
# ---------------------------------------------------------------------------

def test_bus_uniqueness_does_not_leak_across_operators(client, db_engine):
    operator_a_id = _create_operator_in_db(db_engine, "Bus Unique A")
    operator_b_id = _create_operator_in_db(db_engine, "Bus Unique B")

    driver_a_id = _create_driver_in_db(db_engine, operator_a_id, "Bus Driver A", "bus-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, operator_b_id, "Bus Driver B", "bus-b@test.com")

    # Operator A creates a bus with number "FLEET-001"
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "FLEET-001", "license_plate": "AAA-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)

    # Operator B must be able to create a bus with the same number — not a 409
    _logout(client)
    _login(client, driver_b_id)

    bus_b = client.post(
        "/buses/",
        json={"bus_number": "FLEET-001", "license_plate": "BBB-001", "capacity": 40, "size": "mid"},
    )
    assert bus_b.status_code in (200, 201), (
        f"Expected operator B to create bus 'FLEET-001' independently, got {bus_b.status_code}: {bus_b.text}"
    )

    # Within the same operator, duplicates are still rejected
    bus_b_dup = client.post(
        "/buses/",
        json={"bus_number": "FLEET-001", "license_plate": "BBB-002", "capacity": 40, "size": "mid"},
    )
    assert bus_b_dup.status_code == 409, (
        f"Expected 409 for duplicate bus within same operator, got {bus_b_dup.status_code}"
    )

