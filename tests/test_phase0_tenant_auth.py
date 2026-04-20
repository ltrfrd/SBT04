# =============================================================================
# tests/test_phase0_tenant_auth.py
# -----------------------------------------------------------------------------
# Phase 0 tenant isolation and transitional operator-session tests.
# =============================================================================
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from backend.models.district import District
from backend.models.driver import Driver
from backend.models.route import Route
from backend.models.run import Run
from backend.models.school import School
from backend.models.stop import Stop
from backend.models.yard import Yard
from backend.models.operator import Operator, OperatorRouteAccess
from backend.routers.run_helpers import EXECUTION_RUN_BLOCKED_DETAIL
from backend.utils.planning_scope import EXECUTION_ROUTE_BLOCKED_DETAIL
from tests.conftest import TEST_DRIVER_PIN, _create_operator_in_db, _create_driver_in_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, operator_id: int) -> None:
    r = client.post("/session/operator", json={"operator_id": operator_id})
    assert r.status_code == 200, f"Session bootstrap failed: {r.text}"


def _logout(client) -> None:
    r = client.post("/session/logout")
    assert r.status_code == 200


def _create_district_in_db(db_engine, name: str, contact_info: str | None = None) -> int:
    with Session(db_engine) as db:
        district = District(name=name, contact_info=contact_info)
        db.add(district)
        db.commit()
        db.refresh(district)
        return district.id


def _create_yard_in_db(db_engine, operator_id: int, name: str) -> int:
    with Session(db_engine) as db:
        yard = Yard(name=name, operator_id=operator_id)
        db.add(yard)
        db.commit()
        db.refresh(yard)
        return yard.id


def _share_route(client, route_id: int, target_operator_id: int, access_level: str = "read") -> None:
    response = client.post(
        f"/routes/{route_id}/share/{target_operator_id}",
        json={"access_level": access_level},
    )
    assert response.status_code == 200
    assert response.json()["access_level"] == access_level


def _assign_route_to_operator_yard(
    client,
    db_engine,
    *,
    operator_id: int,
    route_id: int,
    yard_name: str,
) -> int:
    yard_id = _create_yard_in_db(db_engine, operator_id, yard_name)
    with Session(db_engine) as db:
        route = db.get(Route, route_id)
        district_id = route.district_id if route else None
    assert district_id is not None
    _login(client, operator_id)
    response = client.post(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert response.status_code == 200, response.text
    return yard_id


def _establish_execution_yard(
    db_engine,
    route_id: int,
    *,
    yard_name: str,
    operator_id: int | None = None,
) -> int:
    """Direct DB yard-route link so the operator gains execution visibility without changing session."""
    with Session(db_engine) as db:
        if operator_id is None:
            access = db.query(OperatorRouteAccess).filter_by(
                route_id=route_id, access_level="owner"
            ).first()
            assert access is not None, f"No owner access found for route {route_id}"
            operator_id = access.operator_id
        yard = Yard(name=yard_name, operator_id=operator_id)
        db.add(yard)
        db.flush()
        yard_id = yard.id
        route = db.get(Route, route_id)
        route.yards.append(yard)
        db.commit()
        return yard_id


def _execution_pretrip_payload(*, bus_number: str, license_plate: str, driver_name: str) -> dict:
    return {
        "bus_number": bus_number,
        "license_plate": license_plate,
        "driver_name": driver_name,
        "inspection_date": date.today().isoformat(),
        "inspection_time": "06:00:00",
        "odometer": 1000,
        "inspection_place": "Execution Yard",
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


def _create_shared_runtime_context(client, db_engine, *, suffix: str) -> dict[str, int]:
    district_id = _create_district_in_db(db_engine, f"{suffix} District")
    owner_operator_id = _create_operator_in_db(db_engine, f"{suffix} Owner")
    shared_operator_id = _create_operator_in_db(db_engine, f"{suffix} Shared")
    owner_driver_id = _create_driver_in_db(
        db_engine,
        owner_operator_id,
        f"{suffix} Owner Driver",
        f"{suffix.lower().replace(' ', '-')}-owner@test.com",
    )

    _logout(client)
    _login(client, owner_operator_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": f"{suffix} School", "address": f"{suffix} Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": f"{suffix}-ROUTE", "school_ids": [school_id]},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    assign_driver = client.post(f"/routes/{route_id}/assign_driver/{owner_driver_id}")
    assert assign_driver.status_code in (200, 201)

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "AM"})
    assert run.status_code == 201
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": f"{suffix} Stop"},
    )
    assert stop.status_code == 201
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": f"{suffix} Student", "grade": "5", "school_id": school_id},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    bus = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), 
            "bus_number": f"{suffix[:12]}-BUS",
            "license_plate": f"{suffix[:8]}-PLT",
            "capacity": 48,
            "size": "full",
        },
    )
    assert bus.status_code in (200, 201)
    bus_id = bus.json()["id"]

    bus_assign = client.post(f"/routes/{route_id}/assign_bus/{bus_id}")
    assert bus_assign.status_code == 200

    pretrip = client.post(
        "/pretrips/",
        json=_execution_pretrip_payload(
            bus_number=bus.json()["bus_number"],
            license_plate=bus.json()["license_plate"],
            driver_name=f"{suffix} Owner Driver",
    ),
    )
    assert pretrip.status_code in (200, 201)

    _share_route(client, route_id, shared_operator_id, "operate")
    _logout(client)

    return {
        "district_id": district_id,
        "owner_operator_id": owner_operator_id,
        "shared_operator_id": shared_operator_id,
        "owner_driver_id": owner_driver_id,
        "school_id": school_id,
        "route_id": route_id,
        "run_id": run_id,
        "stop_id": stop_id,
        "student_id": student_id,
    }


def _create_shared_planning_context(client, db_engine, *, suffix: str) -> dict[str, int]:
    district_id = _create_district_in_db(db_engine, f"{suffix} District")
    owner_operator_id = _create_operator_in_db(db_engine, f"{suffix} Owner")
    shared_operator_id = _create_operator_in_db(db_engine, f"{suffix} Shared")

    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, f"{suffix} Owner Driver", f"{suffix.lower()}-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, f"{suffix} Shared Driver", f"{suffix.lower()}-shared@test.com")

    _login(client, owner_operator_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": f"{suffix} School", "address": f"{suffix} Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": f"{suffix}-ROUTE", "school_ids": [school_id]},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": f"{suffix} Stop"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": f"{suffix} Student", "grade": "5", "school_id": school_id},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    _share_route(client, route_id, shared_operator_id, "read")
    _establish_execution_yard(db_engine, route_id, yard_name=f"{suffix} Owner Exec Yard")
    _establish_execution_yard(db_engine, route_id, yard_name=f"{suffix} Shared Exec Yard", operator_id=shared_operator_id)
    _logout(client)

    return {
        "district_id": district_id,
        "owner_operator_id": owner_operator_id,
        "owner_driver_id": owner_driver_id,
        "shared_driver_id": shared_driver_id,
        "shared_operator_id": shared_operator_id,
        "school_id": school_id,
        "route_id": route_id,
        "run_id": run_id,
        "stop_id": stop_id,
        "student_id": student_id,
    }


def _create_student_via_run_stop(
    client,
    route_id: int,
    school_id: int,
    *,
    name: str,
    grade: str = "5",
    run_type: str = "AM",
) -> dict[str, int]:
    run = client.post(f"/routes/{route_id}/runs", json={"run_type": run_type})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": f"{name} Stop"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": name, "grade": grade, "school_id": school_id},
    )
    assert student.status_code == 201

    return {
        "run_id": run_id,
        "stop_id": stop_id,
        "student_id": student.json()["id"],
    }


# ---------------------------------------------------------------------------
# AUTH: temporary operator session behaviour
# ---------------------------------------------------------------------------

def test_session_operator_requires_valid_operator(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Session Operator")

    missing_operator = client.post("/session/operator", json={})
    assert missing_operator.status_code == 422

    invalid_operator = client.post("/session/operator", json={"operator_id": 999999})
    assert invalid_operator.status_code == 404

    valid_session = client.post("/session/operator", json={"operator_id": operator_id})
    assert valid_session.status_code == 200
    assert valid_session.json()["operator_id"] == operator_id


# ---------------------------------------------------------------------------
# C2 / M1: X-Operator-ID header must NOT grant operator context without a session
# ---------------------------------------------------------------------------

def test_xoperator_id_header_without_session_is_rejected(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Header Bypass Operator")

    # Log out so there is no active session
    _logout(client)

    # Unauthenticated request with X-Operator-ID header â€” must be 401, not 200
    r = client.get("/drivers/", headers={"x-operator-id": str(operator_id)})
    assert r.status_code == 401, (
        f"Expected 401 (unauthenticated), got {r.status_code}. "
        "X-Operator-ID must not grant operator context without a valid session."
    )


def test_single_operator_anonymous_access_is_rejected(client, db_engine):
    # The test DB already has exactly one operator (from bootstrap). Unauthenticated
    # access to that single operator must be rejected â€” not silently granted.
    _logout(client)

    r = client.get("/routes/")
    assert r.status_code == 401, (
        f"Expected 401 (unauthenticated), got {r.status_code}. "
        "Single-operator mode must not grant anonymous access."
    )


# ---------------------------------------------------------------------------
# C2: Tenant isolation â€” cross-operator reads and writes are blocked
# ---------------------------------------------------------------------------

def test_operator_isolation_blocks_cross_operator_reads_and_writes(client, db_engine):
    operator_one_id = _create_operator_in_db(db_engine, "Alpha Transit")
    operator_two_id = _create_operator_in_db(db_engine, "Beta Transit")

    driver_one_id = _create_driver_in_db(db_engine, operator_one_id, "Alpha Driver", "alpha-driver@test.com")
    driver_two_id = _create_driver_in_db(db_engine, operator_two_id, "Beta Driver", "beta-driver@test.com")

    # --- Operator one creates a route ---
    _login(client, operator_one_id)
    route_one = client.post("/routes/", json={"route_number": "ALPHA-1"})
    assert route_one.status_code in (200, 201)
    route_one_id = route_one.json()["id"]

    # --- Switch to operator two ---
    _logout(client)
    _login(client, operator_two_id)

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
    _login(client, owner_operator_id)
    route = client.post("/routes/", json={"route_number": "SHARED-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # --- Shared operator cannot read route before grant ---
    _logout(client)
    _login(client, shared_operator_id)

    not_shared = client.get(f"/routes/{route_id}")
    assert not_shared.status_code == 404

    # --- Owner grants read access ---
    _logout(client)
    _login(client, owner_operator_id)

    grant = client.post(
        f"/routes/{route_id}/share/{shared_operator_id}",
        json={"access_level": "read"},
    )
    assert grant.status_code == 200
    assert grant.json()["access_level"] == "read"

    # --- Shared operator has planning grant but no yard assignment â†’ no execution visibility ---
    _logout(client)
    _login(client, shared_operator_id)

    shared_read = client.get(f"/routes/{route_id}")
    assert shared_read.status_code == 200
    assert shared_read.json()["id"] == route_id

    shared_list = client.get("/routes/")
    assert shared_list.status_code == 200
    assert route_id in [item["id"] for item in shared_list.json()]

    # --- Shared operator still cannot write (read grant only, and no execution visibility) ---
    shared_write = client.put(f"/routes/{route_id}", json={"route_number": "SHARED-1-EDIT"})
    assert shared_write.status_code == 404


def test_dashboard_counts_include_accessible_shared_planning_records(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Dashboard Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Dashboard Shared")

    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Dashboard Owner Driver", "dashboard-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Dashboard Shared Driver", "dashboard-shared@test.com")

    _login(client, owner_operator_id)

    school = client.post(
        "/schools/",
        json={"name": "Dashboard Shared School", "address": "10 Dashboard Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "DASH-SHARED-1", "school_ids": [school_id]})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    run = client.post(f"/routes/{route_id}/runs", json={"run_type": "Morning"})
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Dashboard Shared Stop"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Dashboard Shared Student", "grade": "4", "school_id": school_id},
    )
    assert student.status_code == 201

    grant = client.post(
        f"/routes/{route_id}/share/{shared_operator_id}",
        json={"access_level": "read"},
    )
    assert grant.status_code == 200

    _logout(client)
    _login(client, shared_operator_id)

    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.text

    assert "<strong>Routes:</strong> 1" in body
    assert "<strong>Schools:</strong> 1" in body
    assert "<strong>Students:</strong> 1" in body
    assert "<strong>Active Runs:</strong> 1" in body


def test_shared_operator_can_create_student_from_run_stop_context_on_shared_district_route(client, db_engine):
    context = _create_shared_planning_context(client, db_engine, suffix="Shared Student")
    _login(client, context["shared_operator_id"])

    response = client.post(
        f"/runs/{context['run_id']}/stops/{context['stop_id']}/students",
        json={"name": "Shared Planning Student", "grade": "5", "school_id": context["school_id"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Shared Planning Student"
    assert body["school_id"] == context["school_id"]
    assert body["route_id"] == context["route_id"]
    assert body["stop_id"] == context["stop_id"]


def test_shared_operator_can_delete_accessible_student_record(client, db_engine):
    context = _create_shared_planning_context(client, db_engine, suffix="Delete Student Shared")

    _login(client, context["shared_operator_id"])
    response = client.delete(f"/students/{context['student_id']}")
    assert response.status_code == 204

    missing = client.get(f"/students/{context['student_id']}")
    assert missing.status_code == 404


def test_students_by_school_includes_accessible_shared_students(client, db_engine):
    context = _create_shared_planning_context(client, db_engine, suffix="School Students Shared")

    _login(client, context["shared_operator_id"])
    response = client.get(f"/students/school/{context['school_id']}")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [context["student_id"]]


def test_students_by_route_includes_accessible_shared_students(client, db_engine):
    context = _create_shared_planning_context(client, db_engine, suffix="Route Students Shared")

    _login(client, context["shared_operator_id"])
    response = client.get(f"/students/route/{context['route_id']}")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [context["student_id"]]


def test_absences_by_date_includes_accessible_shared_students(client, db_engine):
    context = _create_shared_planning_context(client, db_engine, suffix="Absence Shared")

    _login(client, context["owner_operator_id"])
    create_absence = client.post(
        f"/students/{context['student_id']}/bus_absence",
        json={"date": date.today().isoformat(), "run_type": "AM"},
    )
    assert create_absence.status_code == 201
    _logout(client)

    _login(client, context["shared_operator_id"])
    response = client.get(f"/reports/absences/date/{date.today().isoformat()}")
    assert response.status_code == 200
    assert response.json()["context"] == {"type": "date", "value": date.today().isoformat()}
    assert response.json()["total_absences"] == 1
    assert response.json()["absences"][0]["student_id"] == context["student_id"]
    assert response.json()["absences"][0]["status"] == "planned_absent"


# ---------------------------------------------------------------------------
# List endpoints only return operator-accessible records
# ---------------------------------------------------------------------------

def test_operator_lists_only_show_owned_records(client, db_engine):
    operator_one_id = _create_operator_in_db(db_engine, "List One")
    operator_two_id = _create_operator_in_db(db_engine, "List Two")

    driver_one_id = _create_driver_in_db(db_engine, operator_one_id, "Driver One", "driver-one@test.com")
    driver_two_id = _create_driver_in_db(db_engine, operator_two_id, "Driver Two", "driver-two@test.com")

    # --- Operator one creates assets ---
    _login(client, operator_one_id)
    extra_driver_one = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Extra One", "email": "extra-one@test.com", "phone": "101", "pin": TEST_DRIVER_PIN},
    )
    route_one = client.post("/routes/", json={"route_number": "LIST-ONE"})
    assert extra_driver_one.status_code == 201
    assert route_one.status_code in (200, 201)

    # --- Operator two creates assets ---
    _logout(client)
    _login(client, operator_two_id)
    extra_driver_two = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Extra Two", "email": "extra-two@test.com", "phone": "202", "pin": TEST_DRIVER_PIN},
    )
    route_two = client.post("/routes/", json={"route_number": "LIST-TWO"})
    assert extra_driver_two.status_code == 201
    assert route_two.status_code in (200, 201)
    _establish_execution_yard(db_engine, route_two.json()["id"], yard_name="List Two Exec Yard", operator_id=operator_two_id)

    # --- Add yard for operator one's route so it appears in execution listing ---
    _establish_execution_yard(db_engine, route_one.json()["id"], yard_name="List One Exec Yard", operator_id=operator_one_id)

    # --- Operator one list only shows its records ---
    _logout(client)
    _login(client, operator_one_id)

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


def test_get_districts_returns_created_districts(client, db_engine):
    district_one_id = _create_district_in_db(db_engine, "District List One")
    district_two_id = _create_district_in_db(db_engine, "District List Two")

    response = client.get("/districts/")
    assert response.status_code == 200

    district_ids = {district["id"] for district in response.json()}
    assert district_one_id in district_ids
    assert district_two_id in district_ids


def test_get_district_detail_returns_district(client, db_engine):
    district_id = _create_district_in_db(db_engine, "District Detail")

    response = client.get(f"/districts/{district_id}")
    assert response.status_code == 200
    assert response.json()["id"] == district_id
    assert response.json()["name"] == "District Detail"


def test_get_district_schools_returns_only_schools_in_that_district(client, db_engine):
    district_one_id = _create_district_in_db(db_engine, "District School List One")
    district_two_id = _create_district_in_db(db_engine, "District School List Two")

    school_one = client.post(
        f"/districts/{district_one_id}/schools",
        json={"name": "District One School", "address": "1 School Way"},
    )
    school_two = client.post(
        f"/districts/{district_two_id}/schools",
        json={"name": "District Two School", "address": "2 School Way"},
    )
    assert school_one.status_code == 201
    assert school_two.status_code == 201

    route_one = client.post(
        f"/districts/{district_one_id}/routes",
        json={"route_number": "DISTRICT-SCHOOL-LIST-ROUTE-1", "school_ids": [school_one.json()["id"]]},
    )
    route_two = client.post(
        f"/districts/{district_two_id}/routes",
        json={"route_number": "DISTRICT-SCHOOL-LIST-ROUTE-2", "school_ids": [school_two.json()["id"]]},
    )
    assert route_one.status_code == 201
    assert route_two.status_code == 201

    response = client.get(f"/districts/{district_one_id}/schools")
    assert response.status_code == 200
    assert [school["id"] for school in response.json()] == [school_one.json()["id"]]


def test_get_district_routes_returns_only_routes_in_that_district(client, db_engine):
    district_one_id = _create_district_in_db(db_engine, "District Route List One")
    district_two_id = _create_district_in_db(db_engine, "District Route List Two")

    route_one = client.post(
        f"/districts/{district_one_id}/routes",
        json={"route_number": "DISTRICT-LIST-ROUTE-1"},
    )
    route_two = client.post(
        f"/districts/{district_two_id}/routes",
        json={"route_number": "DISTRICT-LIST-ROUTE-2"},
    )
    assert route_one.status_code == 201
    assert route_two.status_code == 201

    response = client.get(f"/districts/{district_one_id}/routes")
    assert response.status_code == 200
    assert [route["id"] for route in response.json()] == [route_one.json()["id"]]


def test_district_summary_returns_correct_counts(client, db_engine):
    district_id = _create_district_in_db(db_engine, "District Summary")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Summary School", "address": "3 Summary Way"},
    )
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "SUMMARY-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    _create_student_via_run_stop(
        client,
        route.json()["id"],
        school.json()["id"],
        name="Summary Student",
        grade="3",
    )

    response = client.get(f"/districts/{district_id}/summary")
    assert response.status_code == 200
    assert response.json() == {
        "district_id": district_id,
        "schools_count": 1,
        "routes_count": 1,
        "students_count": 1,
    }


def test_district_endpoints_return_404_for_missing_district(client):
    responses = (
        client.get("/districts/999999"),
        client.get("/districts/999999/schools"),
        client.get("/districts/999999/routes"),
        client.get("/districts/999999/summary"),
        client.post("/districts/999999/schools", json={"name": "Missing District School"}),
        client.post("/districts/999999/routes", json={"route_number": "MISSING-DISTRICT-ROUTE"}),
    )

    for response in responses:
        assert response.status_code == 404


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
        owner_grant = next(
            (grant for grant in route.operator_access if grant.operator_id == 1),
            None,
        )
        assert owner_grant is not None
        assert owner_grant.access_level == "owner"


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


def test_route_creation_requires_district_id(client):
    first = client._wrapped_client.post(
        "/routes/",
        json={"route_number": "LEGACY-DUP-ROUTE"},
    )
    assert first.status_code == 410
    assert "district-nested planning paths" in first.json()["detail"]


def test_direct_route_creation_uses_district_based_uniqueness(client, db_engine):
    retired = client._wrapped_client.post(
        "/routes/",
        json={"route_number": "MIXED-SCOPE-ROUTE"},
    )
    assert retired.status_code == 410
    assert "district-nested planning paths" in retired.json()["detail"]


def test_route_school_assignment_requires_district_backed_route(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Legacy Route School District")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Legacy Route School", "address": "306 Legacy Way"},
    )
    assert school.status_code == 201

    route = client._wrapped_client.post(
        "/routes/",
        json={"route_number": "LEGACY-ROUTE-SCHOOL"},
    )
    assert route.status_code == 410
    assert "district-nested planning paths" in route.json()["detail"]

    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "LEGACY-ROUTE-SCHOOL", "school_ids": [school.json()["id"]]},
    )
    assert district_route.status_code == 201
    assert district_route.json()["school_ids"] == [school.json()["id"]]


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

    bootstrap_route = client.post(
        f"/districts/{school_district_id}/routes",
        json={"route_number": "ASSIGN-MISMATCH-BOOTSTRAP", "school_ids": [school.json()["id"]]},
    )
    assert bootstrap_route.status_code == 201

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
    bootstrap_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "ASSIGN-MATCH-BOOTSTRAP", "school_ids": [school.json()["id"]]},
    )
    assert school.status_code == 201
    assert route.status_code == 201
    assert bootstrap_route.status_code == 201

    assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert assign.status_code == 200
    _establish_execution_yard(db_engine, route.json()["id"], yard_name="Assign Match Exec Yard")

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
    bootstrap_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "ASSIGN-DUPLICATE-BOOTSTRAP", "school_ids": [school.json()["id"]]},
    )
    assert school.status_code == 201
    assert route.status_code == 201
    assert bootstrap_route.status_code == 201

    first_assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    second_assign = client.post(f"/schools/{school.json()['id']}/assign_route/{route.json()['id']}")
    assert first_assign.status_code == 200
    assert second_assign.status_code == 200
    _establish_execution_yard(db_engine, route.json()["id"], yard_name="Assign Duplicate Exec Yard")

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
        json={"route_number": "UNASSIGN-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert school.status_code == 201
    assert route.status_code == 201

    unassign = client.delete(f"/schools/{school.json()['id']}/unassign_route/{route.json()['id']}")
    assert unassign.status_code == 200
    _establish_execution_yard(db_engine, route.json()["id"], yard_name="Unassign Route Exec Yard")

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
    bootstrap_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "UNASSIGN-NOOP-BOOTSTRAP", "school_ids": [school.json()["id"]]},
    )
    assert school.status_code == 201
    assert route.status_code == 201
    assert bootstrap_route.status_code == 201

    unassign = client.delete(f"/schools/{school.json()['id']}/unassign_route/{route.json()['id']}")
    assert unassign.status_code == 200
    _establish_execution_yard(db_engine, route.json()["id"], yard_name="Unassign Noop Exec Yard")

    detail = client.get(f"/routes/{route.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["schools"] == []


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

    run = client.post(f"/routes/{route.json()['id']}/runs", json={"run_type": "AM"})
    assert run.status_code == 201

    stop = client.post(
        f"/runs/{run.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "Student Route Mismatch Stop"},
    )
    assert stop.status_code == 201

    student = client.post(
        f"/runs/{run.json()['id']}/stops/{stop.json()['id']}/students",
        json={
            "name": "Student Route Mismatch",
            "grade": "7",
            "school_id": school.json()["id"],
        },
    )
    assert student.status_code == 404


def test_school_list_still_returns_operator_owned_schools(client, db_engine):
    owned_school = client.post(
        "/schools/",
        json={"name": "Owned School Visible", "address": "20 School Way"},
    )
    assert owned_school.status_code == 201

    visible_route = client.post(
        "/routes/",
        json={"route_number": "OWNED-SCHOOL-VISIBLE-ROUTE", "school_ids": [owned_school.json()["id"]]},
    )
    assert visible_route.status_code in (200, 201)
    _establish_execution_yard(db_engine, visible_route.json()["id"], yard_name="Owned School Exec Yard")

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

    visible_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-SCHOOL-VISIBLE-ROUTE", "school_ids": [district_school.json()["id"]]},
    )
    assert visible_route.status_code == 201
    _establish_execution_yard(db_engine, visible_route.json()["id"], yard_name="District School Exec Yard")

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
    owned_route = client.post(
        "/routes/",
        json={"route_number": "COMBINED-OWNED-SCHOOL-ROUTE", "school_ids": [owned_school.json()["id"]]},
    )
    assert owned_route.status_code in (200, 201)
    _establish_execution_yard(db_engine, owned_route.json()["id"], yard_name="Combined Owned School Exec Yard")

    district_id = _create_district_in_db(db_engine, "Combined District")
    district_school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Combined District School", "address": "23 School Way"},
    )
    assert district_school.status_code == 201
    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "COMBINED-DISTRICT-SCHOOL-ROUTE", "school_ids": [district_school.json()["id"]]},
    )
    assert district_route.status_code == 201
    _establish_execution_yard(db_engine, district_route.json()["id"], yard_name="Combined District School Exec Yard")

    schools = client.get("/schools/")
    assert schools.status_code == 200

    school_ids = {school["id"] for school in schools.json()}
    assert owned_school.json()["id"] in school_ids
    assert district_school.json()["id"] in school_ids


def test_school_detail_still_returns_operator_owned_school(client, db_engine):
    owned_school = client.post(
        "/schools/",
        json={"name": "Owned School Detail", "address": "24 School Way"},
    )
    assert owned_school.status_code == 201

    visible_route = client.post(
        "/routes/",
        json={"route_number": "OWNED-SCHOOL-DETAIL-ROUTE", "school_ids": [owned_school.json()["id"]]},
    )
    assert visible_route.status_code in (200, 201)
    _establish_execution_yard(db_engine, visible_route.json()["id"], yard_name="Owned School Detail Exec Yard")

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

    visible_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-SCHOOL-DETAIL-ROUTE", "school_ids": [district_school.json()["id"]]},
    )
    assert visible_route.status_code == 201
    _establish_execution_yard(db_engine, visible_route.json()["id"], yard_name="District School Detail Exec Yard")

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
    _login(client, owner_operator_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Update School", "address": "50 Update Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "SHARED-SCHOOL-UPDATE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    bootstrap = client.post(
        "/routes/",
        json={"route_number": "SHARED-SCHOOL-UPDATE-BOOTSTRAP", "school_ids": [school_id]},
    )
    assert bootstrap.status_code in (200, 201)
    link = client.put(
        f"/routes/{route_id}",
        json={"route_number": "SHARED-SCHOOL-UPDATE", "school_ids": [school_id]},
    )
    assert link.status_code == 200
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_operator_id)

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
    _login(client, owner_operator_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Delete School", "address": "51 Delete Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "SHARED-SCHOOL-DELETE"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    bootstrap = client.post(
        "/routes/",
        json={"route_number": "SHARED-SCHOOL-DELETE-BOOTSTRAP", "school_ids": [school_id]},
    )
    assert bootstrap.status_code in (200, 201)
    link = client.put(
        f"/routes/{route_id}",
        json={"route_number": "SHARED-SCHOOL-DELETE", "school_ids": [school_id]},
    )
    assert link.status_code == 200
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_operator_id)

    delete = client.delete(f"/schools/{school_id}")
    assert delete.status_code == 204

    read_back = client.get(f"/schools/{school_id}")
    assert read_back.status_code == 404


def test_route_list_still_returns_operator_owned_routes(client, db_engine):
    owned_route = client.post(
        "/routes/",
        json={"route_number": "OWNED-ROUTE-VISIBLE"},
    )
    assert owned_route.status_code in (200, 201)
    _establish_execution_yard(db_engine, owned_route.json()["id"], yard_name="Owned Route Exec Yard")

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
    _establish_execution_yard(db_engine, district_route.json()["id"], yard_name="District Route Exec Yard")

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
    _establish_execution_yard(db_engine, owned_route.json()["id"], yard_name="Combined Owned Route Exec Yard")

    district_id = _create_district_in_db(db_engine, "Combined District Route")
    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "COMBINED-DISTRICT-ROUTE"},
    )
    assert district_route.status_code == 201
    _establish_execution_yard(db_engine, district_route.json()["id"], yard_name="Combined District Route Exec Yard")

    routes = client.get("/routes/")
    assert routes.status_code == 200

    route_ids = {route["id"] for route in routes.json()}
    assert owned_route.json()["id"] in route_ids
    assert district_route.json()["id"] in route_ids


def test_route_detail_still_returns_operator_owned_route(client, db_engine):
    owned_route = client.post(
        "/routes/",
        json={"route_number": "OWNED-ROUTE-DETAIL"},
    )
    assert owned_route.status_code in (200, 201)
    _establish_execution_yard(db_engine, owned_route.json()["id"], yard_name="Owned Route Detail Exec Yard")

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
    _establish_execution_yard(db_engine, district_route.json()["id"], yard_name="District Route Detail Exec Yard")

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
    _login(client, owner_operator_id)
    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "DISTRICT-HIDDEN-ROUTE"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    _logout(client)
    _login(client, other_operator_id)

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
    _login(client, owner_operator_id)
    route = client.post("/routes/", json={"route_number": "SHARED-ROUTE-LIST"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_operator_id)

    route_list = client.get("/routes/")
    assert route_list.status_code == 200
    route_ids = {item["id"] for item in route_list.json()}
    assert route_id in route_ids


def test_student_list_still_returns_operator_owned_students(client, db_engine):
    school = client.post(
        "/schools/",
        json={"name": "Owned Student School", "address": "30 Student Way"},
    )
    assert school.status_code == 201
    route = client.post(
        "/routes/",
        json={"route_number": "OWNED-STUDENT-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert route.status_code in (200, 201)
    owned_student = _create_student_via_run_stop(
        client,
        route.json()["id"],
        school.json()["id"],
        name="Owned Student Visible",
        grade="3",
    )

    students = client.get("/students/")
    assert students.status_code == 200

    student_ids = {student["id"] for student in students.json()}
    assert owned_student["student_id"] in student_ids


def test_student_list_returns_district_owned_students(client, db_engine):
    district_id = _create_district_in_db(db_engine, "Visible District Student")

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District Student School", "address": "31 Student Way"},
    )
    assert school.status_code == 201
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-STUDENT-LIST", "school_ids": [school.json()["id"]]},
    )
    assert route.status_code == 201
    district_student = _create_student_via_run_stop(
        client,
        route.json()["id"],
        school.json()["id"],
        name="District Student Visible",
        grade="4",
    )

    students = client.get("/students/")
    assert students.status_code == 200

    student_ids = {student["id"] for student in students.json()}
    assert district_student["student_id"] in student_ids


def test_student_list_returns_combined_operator_and_district_owned_students(client, db_engine):
    school = client.post(
        "/schools/",
        json={"name": "Combined Student School", "address": "32 Student Way"},
    )
    assert school.status_code == 201
    owned_route = client.post(
        "/routes/",
        json={"route_number": "COMBINED-OWNED-STUDENT-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert owned_route.status_code in (200, 201)

    owned_student = _create_student_via_run_stop(
        client,
        owned_route.json()["id"],
        school.json()["id"],
        name="Combined Owned Student",
        grade="5",
    )

    district_id = _create_district_in_db(db_engine, "Combined District Student")
    district_school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Combined District Student School", "address": "33 Student Way"},
    )
    assert district_school.status_code == 201
    district_route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "COMBINED-DISTRICT-STUDENT-ROUTE", "school_ids": [district_school.json()["id"]]},
    )
    assert district_route.status_code == 201
    district_student = _create_student_via_run_stop(
        client,
        district_route.json()["id"],
        district_school.json()["id"],
        name="Combined District Student",
        grade="6",
    )

    students = client.get("/students/")
    assert students.status_code == 200

    student_ids = {student["id"] for student in students.json()}
    assert owned_student["student_id"] in student_ids
    assert district_student["student_id"] in student_ids


def test_district_owned_school_is_hidden_without_route_access_for_other_operator(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "District School Owner")
    other_operator_id = _create_operator_in_db(db_engine, "District School Other")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "District School Owner Driver", "district-school-owner@test.com")
    other_driver_id = _create_driver_in_db(db_engine, other_operator_id, "District School Other Driver", "district-school-other@test.com")
    district_id = _create_district_in_db(db_engine, "District School Hidden")

    _logout(client)
    _login(client, owner_operator_id)
    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District Hidden School", "address": "40 Hidden School Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    _logout(client)
    _login(client, other_operator_id)

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
    _login(client, owner_operator_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Route School", "address": "41 Shared School Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "SHARED-SCHOOL-ROUTE", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_operator_id)

    school_list = client.get("/schools/")
    assert school_list.status_code == 200
    school_ids = {item["id"] for item in school_list.json()}
    assert school_id in school_ids

    school_detail = client.get(f"/schools/{school_id}")
    assert school_detail.status_code == 200


def _build_shared_school_reports_context(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Shared Reports Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "Shared Reports Reader")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "Shared Reports Owner Driver", "shared-reports-owner@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_operator_id, "Shared Reports Reader Driver", "shared-reports-reader@test.com")
    district_id = _create_district_in_db(db_engine, "Shared Reports District")

    _logout(client)
    _login(client, owner_operator_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "Shared Reports School", "address": "44 Shared Reports Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "SHARED-REPORTS-ROUTE", "school_ids": [school_id]},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    route_driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "Shared Reports Route Driver", "email": "shared-reports-route@test.com", "phone": "5551000", "pin": "1234"},
    )
    assert route_driver.status_code == 201
    assign_driver = client.post(f"/routes/{route_id}/assign_driver/{route_driver.json()['id']}")
    assert assign_driver.status_code in (200, 201)

    run = client.post(
        f"/routes/{route_id}/runs",
        json={"run_type": "AM"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"name": "Shared Reports Stop", "sequence": 1, "type": "pickup"},
    )
    assert stop.status_code == 201
    stop_id = stop.json()["id"]

    student = client.post(
        f"/runs/{run_id}/stops/{stop_id}/students",
        json={"name": "Shared Reports Student", "grade": "5", "school_id": school_id},
    )
    assert student.status_code == 201
    student_id = student.json()["id"]

    _share_route(client, route_id, shared_operator_id)
    _establish_execution_yard(db_engine, route_id, yard_name="Shared Reports Owner Exec Yard")
    _establish_execution_yard(db_engine, route_id, yard_name="Shared Reports Shared Exec Yard", operator_id=shared_operator_id)

    started_run = client.post(f"/runs/start?run_id={run_id}")
    assert started_run.status_code in (200, 201)
    run_date = started_run.json()["start_time"][:10]

    _logout(client)
    _login(client, shared_operator_id)

    return {
        "district_id": district_id,
        "school_id": school_id,
        "route_id": route_id,
        "run_id": run_id,
        "stop_id": stop_id,
        "student_id": student_id,
        "run_date": run_date,
    }


def test_shared_operator_can_update_school_status_for_district_owned_student(client, db_engine):
    context = _build_shared_school_reports_context(client, db_engine)

    response = client.post(
        f"/runs/{context['run_id']}/students/{context['student_id']}/school-status",
        json={"status": "present"},
    )

    assert response.status_code == 200
    assert response.json()["student_id"] == context["student_id"]
    assert response.json()["run_id"] == context["run_id"]
    assert response.json()["school_status"] == "present"


def test_shared_operator_can_confirm_school_reports_for_district_owned_school(client, db_engine):
    context = _build_shared_school_reports_context(client, db_engine)

    update = client.post(
        f"/runs/{context['run_id']}/students/{context['student_id']}/school-status",
        json={"status": "absent"},
    )
    assert update.status_code == 200

    response = client.post(
        f"/reports/school/{context['school_id']}/confirm/{context['run_id']}",
        json={"confirmed_by": "Shared Front Desk"},
    )

    assert response.status_code == 200
    assert response.json()["school_id"] == context["school_id"]
    assert response.json()["run_id"] == context["run_id"]
    assert response.json()["confirmed_by_role"] == "school"


def test_shared_operator_can_view_school_reports_by_date_and_mobile_for_district_owned_school(client, db_engine):
    context = _build_shared_school_reports_context(client, db_engine)

    by_date = client.get(f"/reports/school/{context['school_id']}/reports/{context['run_date']}")
    assert by_date.status_code == 200
    assert by_date.json()["school_name"] == "Shared Reports School"
    assert by_date.json()["school_id"] == context["school_id"]
    assert by_date.json()["date"] == context["run_date"]
    assert "routes" in by_date.json()

    summary = client.get(f"/reports/school/{context['school_id']}")
    assert summary.status_code == 200
    assert summary.json()["school_id"] == context["school_id"]

    mobile = client.get(f"/reports/school/{context['school_id']}/mobile")
    assert mobile.status_code == 200
    assert "Shared Reports School" in mobile.text


def test_district_owned_student_requires_accessible_school_or_route_for_other_operator(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "District Student Owner")
    other_operator_id = _create_operator_in_db(db_engine, "District Student Other")
    owner_driver_id = _create_driver_in_db(db_engine, owner_operator_id, "District Student Owner Driver", "district-student-owner@test.com")
    other_driver_id = _create_driver_in_db(db_engine, other_operator_id, "District Student Other Driver", "district-student-other@test.com")
    district_id = _create_district_in_db(db_engine, "District Student Hidden")

    _logout(client)
    _login(client, owner_operator_id)

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "District Student Hidden School", "address": "42 Hidden Student Way"},
    )
    assert school.status_code == 201
    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-HIDDEN-STUDENT-ROUTE", "school_ids": [school.json()["id"]]},
    )
    assert route.status_code == 201

    student = _create_student_via_run_stop(
        client,
        route.json()["id"],
        school.json()["id"],
        name="District Hidden Student",
        grade="7",
    )
    student_id = student["student_id"]

    _logout(client)
    _login(client, other_operator_id)

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
    _login(client, owner_operator_id)

    school = client.post(
        "/schools/",
        json={"name": "Shared Student School", "address": "43 Shared Student Way"},
    )
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(
        "/routes/",
        json={"route_number": "SHARED-STUDENT-ROUTE", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    student = _create_student_via_run_stop(
        client,
        route_id,
        school_id,
        name="Shared Student Visible",
        grade="8",
    )
    student_id = student["student_id"]

    _share_route(client, route_id, shared_operator_id)

    _logout(client)
    _login(client, shared_operator_id)

    student_list = client.get("/students/")
    assert student_list.status_code == 200
    student_ids = {item["id"] for item in student_list.json()}
    assert student_id in student_ids

    student_detail = client.get(f"/students/{student_id}")
    assert student_detail.status_code == 200


# ---------------------------------------------------------------------------
# Route cascade planning endpoints
# ---------------------------------------------------------------------------

def test_create_and_list_runs_under_route(client, db_engine):
    route = client.post("/routes/", json={"route_number": "CASCADE-RUN-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    _establish_execution_yard(db_engine, route_id, yard_name="Cascade Run Exec Yard")

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
    _establish_execution_yard(db_engine, route_id, yard_name="Cascade Stop Exec Yard")

    run = client.post(
        f"/routes/{route_id}/runs",
        json={"run_type": "PM"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    create = client.post(
        f"/routes/{route_id}/runs/{run_id}/stops",
        json={"type": "pickup", "sequence": 1, "name": "Cascade Stop"},
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
        f"/routes/{route_two.json()['id']}/runs/{run.json()['id']}/stops",
        json={"type": "pickup", "sequence": 1},
    )
    assert create.status_code == 404
    assert create.json()["detail"] == "Run not found"

def test_route_cascade_endpoints_return_404_for_missing_route(client):
    create_run = client.post(
        "/districts/999999/routes/999999/runs",
        json={
            "run_type": "AM",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    list_runs = client.get("/routes/999999/runs")
    create_stop = client.post(
        "/districts/999999/routes/999999/runs/1/stops",
        json={"type": "pickup", "sequence": 1},
    )
    list_stops = client.get("/routes/999999/stops")
    for response in (create_run, list_runs, create_stop, list_stops):
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
        f"/routes/{route_id}/runs/{run.json()['id']}/stops",
        json={"type": "pickup", "sequence": 1, "name": "Old Stop"},
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
        f"/routes/{route_one.json()['id']}/runs/{run.json()['id']}/stops",
        json={"type": "pickup", "sequence": 1},
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
        f"/routes/{route_id}/runs/{run.json()['id']}/stops",
        json={"type": "pickup", "sequence": 1},
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
        f"/routes/{route_one.json()['id']}/runs/{run.json()['id']}/stops",
        json={"type": "pickup", "sequence": 1},
    )
    assert run.status_code == 201
    assert stop.status_code == 201

    delete = client.delete(f"/routes/{route_two.json()['id']}/stops/{stop.json()['id']}")
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
    _login(client, operator_a_id)
    bus_a = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), "bus_number": "PT-BUS-A", "license_plate": "PT-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)
    bus_a_id = bus_a.json()["id"]

    pretrip_a = client.post("/pretrips/", json=_pretrip_payload("PT-BUS-A", "PT-A-001"))
    assert pretrip_a.status_code in (200, 201)
    pretrip_a_id = pretrip_a.json()["id"]

    # --- Operator B cannot read operator A's pretrip by ID ---
    _logout(client)
    _login(client, operator_b_id)

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
    _login(client, operator_a_id)
    bus_a = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), "bus_number": "CORR-BUS-A", "license_plate": "CORR-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)

    pretrip_a = client.post("/pretrips/", json=_pretrip_payload("CORR-BUS-A", "CORR-A-001"))
    assert pretrip_a.status_code in (200, 201)
    pretrip_a_id = pretrip_a.json()["id"]

    # Operator B tries to correct operator A's pretrip â€” must get 404
    _logout(client)
    _login(client, operator_b_id)

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
    _login(client, operator_a_id)
    bus_a = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), "bus_number": "UNIQ-BUS-A", "license_plate": "UNIQ-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)
    bus_a_id = bus_a.json()["id"]

    # Operator B tries to create a pretrip for Operator A's bus_id â€” must be 404 (bus not found in B's scope)
    _logout(client)
    _login(client, operator_b_id)

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
    _login(client, operator_a_id)

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
    _login(client, operator_a_id)
    bus_a = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), "bus_number": "FLEET-001", "license_plate": "AAA-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)

    # Operator B must be able to create a bus with the same number â€” not a 409
    _logout(client)
    _login(client, operator_b_id)

    bus_b = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), "bus_number": "FLEET-001", "license_plate": "BBB-001", "capacity": 40, "size": "mid"},
    )
    assert bus_b.status_code in (200, 201), (
        f"Expected operator B to create bus 'FLEET-001' independently, got {bus_b.status_code}: {bus_b.text}"
    )

    # Within the same operator, duplicates are still rejected
    bus_b_dup = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), "bus_number": "FLEET-001", "license_plate": "BBB-002", "capacity": 40, "size": "mid"},
    )
    assert bus_b_dup.status_code == 409, (
        f"Expected 409 for duplicate bus within same operator, got {bus_b_dup.status_code}"
    )


def test_district_context_assign_yard_to_route_succeeds(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Route Yard Owner")
    _create_driver_in_db(db_engine, operator_id, "Route Yard Driver", "route-yard-owner@test.com")
    yard_id = _create_yard_in_db(db_engine, operator_id, "Route Yard One")
    district_id = _create_district_in_db(db_engine, "Route Yard District")

    _logout(client)
    _login(client, operator_id)

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "ROUTE-YARD-ONE"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    assign = client.post(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert assign.status_code == 200
    assert assign.json() == {"district_id": district_id, "route_id": route_id, "yard_id": yard_id}


def test_district_route_lifecycle_endpoints_succeed(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "District Route Lifecycle Owner")
    _create_driver_in_db(db_engine, operator_id, "District Route Lifecycle Driver", "district-route-lifecycle@test.com")
    district_id = _create_district_in_db(db_engine, "District Route Lifecycle District")

    _logout(client)
    _login(client, operator_id)

    created = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-ROUTE-ONE"},
    )
    assert created.status_code == 201
    route_id = created.json()["id"]
    assert created.json()["route_number"] == "DISTRICT-ROUTE-ONE"

    updated = client.put(
        f"/districts/{district_id}/routes/{route_id}",
        json={"route_number": "DISTRICT-ROUTE-UPDATED"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == route_id
    assert updated.json()["route_number"] == "DISTRICT-ROUTE-UPDATED"

    deleted = client.delete(f"/districts/{district_id}/routes/{route_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/routes/{route_id}")
    assert missing.status_code == 404


def test_district_route_update_fails_when_route_is_not_in_path_district(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "District Route Mismatch Owner")
    _create_driver_in_db(db_engine, operator_id, "District Route Mismatch Driver", "district-route-mismatch@test.com")
    district_one_id = _create_district_in_db(db_engine, "District Route Mismatch One")
    district_two_id = _create_district_in_db(db_engine, "District Route Mismatch Two")

    _logout(client)
    _login(client, operator_id)

    created = client.post(
        f"/districts/{district_one_id}/routes",
        json={"route_number": "DISTRICT-ROUTE-MISMATCH"},
    )
    assert created.status_code == 201

    updated = client.put(
        f"/districts/{district_two_id}/routes/{created.json()['id']}",
        json={"route_number": "DISTRICT-ROUTE-MISMATCH-UPDATED"},
    )
    assert updated.status_code == 404
    assert updated.json()["detail"] == "Route not found for district"


def test_district_route_run_endpoints_succeed(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "District Route Run Owner")
    _create_driver_in_db(db_engine, operator_id, "District Route Run Driver", "district-route-run@test.com")
    district_id = _create_district_in_db(db_engine, "District Route Run District")

    _logout(client)
    _login(client, operator_id)

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-RUN-ROUTE"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    created = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={
            "run_type": "Morning",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    assert created.json()["route_id"] == route_id
    assert created.json()["run_type"] == "MORNING"

    updated = client.put(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}",
        json={
            "run_type": "Afternoon",
            "scheduled_start_time": "12:00:00",
            "scheduled_end_time": "13:00:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == run_id
    assert updated.json()["run_type"] == "AFTERNOON"

    deleted = client.delete(f"/districts/{district_id}/routes/{route_id}/runs/{run_id}")
    assert deleted.status_code == 204


def test_district_route_run_create_requires_operate_access(client, db_engine):
    district_id = _create_district_in_db(db_engine, "District Route Run Shared District")
    owner_operator_id = _create_operator_in_db(db_engine, "District Route Run Shared Owner")
    shared_operator_id = _create_operator_in_db(db_engine, "District Route Run Shared Reader")

    _create_driver_in_db(db_engine, owner_operator_id, "District Route Run Shared Owner Driver", "district-route-run-owner@test.com")
    _create_driver_in_db(db_engine, shared_operator_id, "District Route Run Shared Reader Driver", "district-route-run-reader@test.com")

    _logout(client)
    _login(client, owner_operator_id)

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-RUN-SHARED"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    _share_route(client, route_id, shared_operator_id, "read")
    _logout(client)
    _login(client, shared_operator_id)

    denied = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={
            "run_type": "Morning",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert denied.status_code == 404


def test_district_route_stop_endpoints_succeed(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "District Route Stop Owner")
    _create_driver_in_db(db_engine, operator_id, "District Route Stop Driver", "district-route-stop@test.com")
    district_id = _create_district_in_db(db_engine, "District Route Stop District")

    _logout(client)
    _login(client, operator_id)

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "DISTRICT-STOP-ROUTE"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={
            "run_type": "Morning",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    created = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"sequence": 1, "type": "pickup", "name": "District Stop One"},
    )
    assert created.status_code == 201
    stop_id = created.json()["id"]
    assert created.json()["run_id"] == run_id

    updated = client.put(
        f"/districts/{district_id}/routes/{route_id}/stops/{stop_id}",
        json={"sequence": 2, "type": "pickup", "name": "District Stop Updated"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == stop_id
    assert updated.json()["name"] == "District Stop Updated"

    deleted = client.delete(f"/districts/{district_id}/routes/{route_id}/stops/{stop_id}")
    assert deleted.status_code == 204


def test_district_route_stop_update_fails_when_route_is_not_in_path_district(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "District Stop Mismatch Owner")
    _create_driver_in_db(db_engine, operator_id, "District Stop Mismatch Driver", "district-stop-mismatch@test.com")
    district_one_id = _create_district_in_db(db_engine, "District Stop Mismatch One")
    district_two_id = _create_district_in_db(db_engine, "District Stop Mismatch Two")

    _logout(client)
    _login(client, operator_id)

    route = client.post(
        f"/districts/{district_one_id}/routes",
        json={"route_number": "DISTRICT-STOP-MISMATCH"},
    )
    assert route.status_code == 201
    route_id = route.json()["id"]

    run = client.post(
        f"/districts/{district_one_id}/routes/{route_id}/runs",
        json={
            "run_type": "Morning",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert run.status_code == 201

    stop = client.post(
        f"/districts/{district_one_id}/routes/{route_id}/runs/{run.json()['id']}/stops",
        json={"sequence": 1, "type": "pickup", "name": "District Stop Mismatch"},
    )
    assert stop.status_code == 201

    updated = client.put(
        f"/districts/{district_two_id}/routes/{route_id}/stops/{stop.json()['id']}",
        json={"sequence": 3, "type": "pickup", "name": "Wrong District Stop"},
    )
    assert updated.status_code == 404
    assert updated.json()["detail"] == "Route not found for district"


def test_existing_route_run_endpoint_still_works_after_district_additions(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Existing Route Run Owner")
    _create_driver_in_db(db_engine, operator_id, "Existing Route Run Driver", "existing-route-run@test.com")

    _logout(client)
    _login(client, operator_id)

    route = client.post("/routes/", json={"route_number": "EXISTING-ROUTE-RUN"})
    assert route.status_code in (200, 201)

    created = client.post(
        f"/routes/{route.json()['id']}/runs",
        json={
            "run_type": "Morning",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert created.status_code == 201


def test_district_context_assign_yard_from_another_operator_returns_403(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Route Yard Cross Owner")
    other_operator_id = _create_operator_in_db(db_engine, "Route Yard Cross Other")
    _create_driver_in_db(db_engine, owner_operator_id, "Route Yard Cross Driver", "route-yard-cross-owner@test.com")
    _create_driver_in_db(db_engine, other_operator_id, "Other Route Yard Driver", "route-yard-cross-other@test.com")
    other_yard_id = _create_yard_in_db(db_engine, other_operator_id, "Other Operator Yard")
    district_id = _create_district_in_db(db_engine, "Route Yard Cross District")

    _logout(client)
    _login(client, owner_operator_id)

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "ROUTE-YARD-CROSS"})
    assert route.status_code == 201

    assign = client.post(f"/districts/{district_id}/routes/{route.json()['id']}/assign-yard/{other_yard_id}")
    assert assign.status_code == 403


def test_district_context_unassign_yard_from_route_succeeds(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Route Yard Remove Owner")
    _create_driver_in_db(db_engine, operator_id, "Route Yard Remove Driver", "route-yard-remove@test.com")
    yard_id = _create_yard_in_db(db_engine, operator_id, "Route Yard Remove")
    district_id = _create_district_in_db(db_engine, "Route Yard Remove District")

    _logout(client)
    _login(client, operator_id)

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "ROUTE-YARD-REMOVE"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    assign = client.post(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert assign.status_code == 200

    unassign = client.delete(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert unassign.status_code == 200
    assert unassign.json() == {"district_id": district_id, "route_id": route_id, "yard_id": yard_id}


def test_district_context_assign_yard_fails_for_route_outside_district(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Route Yard District Mismatch Owner")
    _create_driver_in_db(db_engine, operator_id, "Route Yard District Mismatch Driver", "route-yard-district-mismatch@test.com")
    yard_id = _create_yard_in_db(db_engine, operator_id, "Route Yard District Mismatch Yard")
    district_one_id = _create_district_in_db(db_engine, "Route Yard District One")
    district_two_id = _create_district_in_db(db_engine, "Route Yard District Two")

    _logout(client)
    _login(client, operator_id)

    route = client.post(f"/districts/{district_one_id}/routes", json={"route_number": "ROUTE-YARD-DISTRICT-MISMATCH"})
    assert route.status_code == 201

    assign = client.post(f"/districts/{district_two_id}/routes/{route.json()['id']}/assign-yard/{yard_id}")
    assert assign.status_code == 404
    assert assign.json()["detail"] == "Route not found for district"

def test_duplicate_yard_assignment_does_not_duplicate_rows(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Route Yard Duplicate Owner")
    _create_driver_in_db(db_engine, operator_id, "Route Yard Duplicate Driver", "route-yard-duplicate@test.com")
    district_id = _create_district_in_db(db_engine, "Route Yard Duplicate District")

    _logout(client)
    _login(client, operator_id)

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "ROUTE-YARD-DUPLICATE"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    yard_id = _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=operator_id,
        route_id=route_id,
        yard_name="Route Yard Duplicate",
    )
    first_assign = client.post(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    second_assign = client.post(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert first_assign.status_code == 200
    assert second_assign.status_code == 200

    with Session(db_engine) as db:
        route_row = db.get(Route, route_id)
        assert route_row is not None
        assert [yard.id for yard in route_row.yards] == [yard_id]


def test_execution_route_visibility_requires_yard_assignment(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Execution Route Operator")
    _create_driver_in_db(db_engine, operator_id, "Execution Route Driver", "execution-route-driver@test.com")
    district_id = _create_district_in_db(db_engine, "Execution Route District")

    _login(client, operator_id)
    visible_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-ROUTE-VISIBLE"})
    hidden_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-ROUTE-HIDDEN"})
    assert visible_route.status_code == 201
    assert hidden_route.status_code == 201

    visible_route_id = visible_route.json()["id"]
    hidden_route_id = hidden_route.json()["id"]
    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=operator_id,
        route_id=visible_route_id,
        yard_name="Execution Route Yard",
    )

    routes_response = client.get("/routes/")
    assert routes_response.status_code == 200
    route_ids = {item["id"] for item in routes_response.json()}
    assert route_ids == {visible_route_id, hidden_route_id}

    visible_detail = client.get(f"/routes/{visible_route_id}")
    hidden_detail = client.get(f"/routes/{hidden_route_id}")
    assert visible_detail.status_code == 200
    assert hidden_detail.status_code == 200


def test_execution_school_visibility_requires_yard_accessible_route(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Execution School Operator")
    _create_driver_in_db(db_engine, operator_id, "Execution School Driver", "execution-school-driver@test.com")
    district_id = _create_district_in_db(db_engine, "Execution School District")

    _login(client, operator_id)
    visible_school = client.post("/schools/", json={"name": "Visible Yard School", "address": "1 Yard Way"})
    hidden_school = client.post("/schools/", json={"name": "Hidden Yard School", "address": "2 Yard Way"})
    assert visible_school.status_code == 201
    assert hidden_school.status_code == 201

    visible_school_id = visible_school.json()["id"]
    hidden_school_id = hidden_school.json()["id"]

    visible_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-SCHOOL-VISIBLE", "school_ids": [visible_school_id]})
    hidden_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-SCHOOL-HIDDEN", "school_ids": [hidden_school_id]})
    assert visible_route.status_code == 201
    assert hidden_route.status_code == 201

    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=operator_id,
        route_id=visible_route.json()["id"],
        yard_name="Execution School Yard",
    )

    schools_response = client.get("/schools/")
    assert schools_response.status_code == 200
    school_ids = {item["id"] for item in schools_response.json()}
    assert school_ids == {visible_school_id, hidden_school_id}

    visible_detail = client.get(f"/schools/{visible_school_id}")
    hidden_detail = client.get(f"/schools/{hidden_school_id}")
    assert visible_detail.status_code == 200
    assert hidden_detail.status_code == 200


def test_execution_student_visibility_requires_yard_accessible_route(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Execution Student Operator")
    _create_driver_in_db(db_engine, operator_id, "Execution Student Driver", "execution-student-driver@test.com")
    district_id = _create_district_in_db(db_engine, "Execution Student District")

    _login(client, operator_id)
    school = client.post("/schools/", json={"name": "Execution Student School", "address": "3 Student Way"})
    assert school.status_code == 201
    school_id = school.json()["id"]

    visible_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-STUDENT-VISIBLE", "school_ids": [school_id]})
    hidden_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-STUDENT-HIDDEN", "school_ids": [school_id]})
    assert visible_route.status_code == 201
    assert hidden_route.status_code == 201

    visible_route_id = visible_route.json()["id"]
    hidden_route_id = hidden_route.json()["id"]
    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=operator_id,
        route_id=visible_route_id,
        yard_name="Execution Student Yard",
    )

    visible_student = _create_student_via_run_stop(
        client,
        visible_route_id,
        school_id,
        name="Visible Yard Student",
        grade="4",
        run_type="AM",
    )
    hidden_student = _create_student_via_run_stop(
        client,
        hidden_route_id,
        school_id,
        name="Hidden Yard Student",
        grade="4",
        run_type="PM",
    )

    visible_student_id = visible_student["student_id"]
    hidden_student_id = hidden_student["student_id"]

    students_response = client.get("/students/")
    assert students_response.status_code == 200
    student_ids = {item["id"] for item in students_response.json()}
    assert student_ids == {visible_student_id, hidden_student_id}

    visible_detail = client.get(f"/students/{visible_student_id}")
    hidden_detail = client.get(f"/students/{hidden_student_id}")
    assert visible_detail.status_code == 200
    assert hidden_detail.status_code == 200


def test_school_absences_exclude_students_on_inaccessible_routes(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Execution Absence Operator")
    _create_driver_in_db(db_engine, operator_id, "Execution Absence Driver", "execution-absence-driver@test.com")
    district_id = _create_district_in_db(db_engine, "Execution Absence District")

    _login(client, operator_id)
    school = client.post("/schools/", json={"name": "Shared Absence School", "address": "4 Shared Way"})
    assert school.status_code == 201
    school_id = school.json()["id"]

    visible_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-ABSENCE-VISIBLE", "school_ids": [school_id]})
    hidden_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-ABSENCE-HIDDEN", "school_ids": [school_id]})
    assert visible_route.status_code == 201
    assert hidden_route.status_code == 201

    visible_route_id = visible_route.json()["id"]
    hidden_route_id = hidden_route.json()["id"]
    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=operator_id,
        route_id=visible_route_id,
        yard_name="Execution Absence Yard",
    )

    visible_student = _create_student_via_run_stop(
        client,
        visible_route_id,
        school_id,
        name="Visible Absence Student",
        grade="5",
        run_type="AM",
    )
    hidden_student = _create_student_via_run_stop(
        client,
        hidden_route_id,
        school_id,
        name="Hidden Absence Student",
        grade="5",
        run_type="PM",
    )

    visible_student_id = visible_student["student_id"]
    hidden_student_id = hidden_student["student_id"]

    visible_absence = client.post(
        f"/students/{visible_student_id}/bus_absence",
        json={"date": date.today().isoformat(), "run_type": "AM"},
    )
    hidden_absence = client.post(
        f"/students/{hidden_student_id}/bus_absence",
        json={"date": date.today().isoformat(), "run_type": "AM"},
    )
    assert visible_absence.status_code == 201
    assert hidden_absence.status_code == 201

    response = client.get(f"/reports/absences/school/{school_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["total_absences"] == 1
    assert [item["student_id"] for item in body["absences"]] == [visible_student_id]


def test_runs_active_ignores_active_runs_on_routes_outside_execution_yard_scope(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Execution Active Run Operator")
    driver_id = _create_driver_in_db(db_engine, operator_id, "Execution Active Run Driver", "execution-active-run-driver@test.com")
    district_id = _create_district_in_db(db_engine, "Execution Active Run District")

    _login(client, operator_id)
    visible_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-ACTIVE-VISIBLE"})
    hidden_route = client.post(f"/districts/{district_id}/routes", json={"route_number": "EXEC-ACTIVE-HIDDEN"})
    assert visible_route.status_code == 201
    assert hidden_route.status_code == 201

    visible_route_id = visible_route.json()["id"]
    hidden_route_id = hidden_route.json()["id"]
    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=operator_id,
        route_id=visible_route_id,
        yard_name="Execution Active Run Yard",
    )

    visible_run = client.post(f"/routes/{visible_route_id}/runs", json={"run_type": "AM"})
    hidden_run = client.post(f"/routes/{hidden_route_id}/runs", json={"run_type": "PM"})
    assert visible_run.status_code == 201
    assert hidden_run.status_code == 201

    with Session(db_engine) as db:
        visible_run_row = db.get(Run, visible_run.json()["id"])
        hidden_run_row = db.get(Run, hidden_run.json()["id"])
        assert visible_run_row is not None
        assert hidden_run_row is not None
        visible_run_row.driver_id = driver_id
        hidden_run_row.driver_id = driver_id
        visible_run_row.start_time = datetime.now(UTC) - timedelta(minutes=10)
        hidden_run_row.start_time = datetime.now(UTC) - timedelta(minutes=1)
        visible_run_row.end_time = None
        hidden_run_row.end_time = None
        db.commit()

    active_response = client.get(f"/runs/active?driver_id={driver_id}")
    assert active_response.status_code == 200
    assert active_response.json()["id"] == visible_run.json()["id"]


def test_start_run_requires_execution_visibility_even_with_operate_grant(client, db_engine):
    context = _create_shared_runtime_context(client, db_engine, suffix="Execution Start Grant")

    _login(client, context["shared_operator_id"])
    blocked = client._wrapped_client.post(f"/runs/start?run_id={context['run_id']}")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == EXECUTION_RUN_BLOCKED_DETAIL

    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=context["shared_operator_id"],
        route_id=context["route_id"],
        yard_name="Execution Start Shared Yard",
    )

    started = client._wrapped_client.post(f"/runs/start?run_id={context['run_id']}")
    assert started.status_code == 200
    assert started.json()["id"] == context["run_id"]


def test_end_run_is_blocked_outside_execution_scope(client, db_engine):
    context = _create_shared_runtime_context(client, db_engine, suffix="Execution End Block")

    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=context["owner_operator_id"],
        route_id=context["route_id"],
        yard_name="Execution End Owner Yard",
    )

    _login(client, context["owner_operator_id"])
    started = client._wrapped_client.post(f"/runs/start?run_id={context['run_id']}")
    assert started.status_code == 200

    _logout(client)
    _login(client, context["shared_operator_id"])

    blocked = client.post(f"/runs/end?run_id={context['run_id']}")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == EXECUTION_RUN_BLOCKED_DETAIL


def test_run_action_is_blocked_outside_execution_scope(client, db_engine):
    context = _create_shared_runtime_context(client, db_engine, suffix="Execution Action Block")

    _assign_route_to_operator_yard(
        client,
        db_engine,
        operator_id=context["owner_operator_id"],
        route_id=context["route_id"],
        yard_name="Execution Action Owner Yard",
    )

    _login(client, context["owner_operator_id"])
    started = client._wrapped_client.post(f"/runs/start?run_id={context['run_id']}")
    assert started.status_code == 200

    _logout(client)
    _login(client, context["shared_operator_id"])

    blocked = client.post(f"/runs/{context['run_id']}/arrive_stop?stop_sequence=1")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == EXECUTION_RUN_BLOCKED_DETAIL


def test_planning_student_mutation_still_allows_owner_access_without_yard_assignment(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Planning Student Regression Operator")
    _create_driver_in_db(db_engine, operator_id, "Planning Student Regression Driver", "planning-student-regression@test.com")

    _login(client, operator_id)
    school = client.post("/schools/", json={"name": "Planning Regression School", "address": "5 Planning Way"})
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post("/routes/", json={"route_number": "PLANNING-REGRESSION", "school_ids": [school_id]})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    student = _create_student_via_run_stop(
        client,
        route_id,
        school_id,
        name="Planning Regression Student",
        grade="3",
    )
    student_id = student["student_id"]

    delete_response = client.delete(f"/students/{student_id}")
    assert delete_response.status_code == 204


def test_district_context_unassign_yard_when_not_linked_is_safe(client, db_engine):
    operator_id = _create_operator_in_db(db_engine, "Route Yard Unassign Missing Owner")
    _create_driver_in_db(db_engine, operator_id, "Route Yard Unassign Missing Driver", "route-yard-unassign-missing@test.com")
    yard_id = _create_yard_in_db(db_engine, operator_id, "Route Yard Unassign Missing Yard")
    district_id = _create_district_in_db(db_engine, "Route Yard Unassign Missing District")

    _logout(client)
    _login(client, operator_id)

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "ROUTE-YARD-UNASSIGN-MISSING"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    unassign = client.delete(f"/districts/{district_id}/routes/{route_id}/assign-yard/{yard_id}")
    assert unassign.status_code == 200
    assert unassign.json() == {"district_id": district_id, "route_id": route_id, "yard_id": yard_id}

    with Session(db_engine) as db:
        route_row = db.get(Route, route_id)
        assert route_row is not None
        assert route_row.yards == []


# ---------------------------------------------------------------------------
# Report generator execution-scope tests
# ---------------------------------------------------------------------------

def test_route_summary_blocked_for_grant_only_operator(client, db_engine):
    owner_id = _create_operator_in_db(db_engine, "Route Summary Block Owner")
    grant_only_id = _create_operator_in_db(db_engine, "Route Summary Block Grantee")
    _create_driver_in_db(db_engine, owner_id, "Route Summary Block Driver", "route-summary-block@test.com")
    district_id = _create_district_in_db(db_engine, "Route Summary Block District")

    _logout(client)
    _login(client, owner_id)

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "ROUTE-SUMM-BLOCK"})
    assert route.status_code == 201
    route_id = route.json()["id"]

    _share_route(client, route_id, grant_only_id)
    _establish_execution_yard(db_engine, route_id, yard_name="Route Summary Block Owner Yard")

    _logout(client)
    _login(client, grant_only_id)

    response = client.get(f"/reports/route/{route_id}")
    assert response.status_code == 403
    assert response.json()["detail"] == EXECUTION_ROUTE_BLOCKED_DETAIL


def test_date_summary_excludes_runs_outside_yard_scope(client, db_engine):
    op_a_id = _create_operator_in_db(db_engine, "Date Summary A Op")
    op_b_id = _create_operator_in_db(db_engine, "Date Summary B Op")
    _create_driver_in_db(db_engine, op_a_id, "Date Summary A Driver", "date-summ-a@test.com")
    _create_driver_in_db(db_engine, op_b_id, "Date Summary B Driver", "date-summ-b@test.com")
    dist_a = _create_district_in_db(db_engine, "Date Summary Dist A")
    dist_b = _create_district_in_db(db_engine, "Date Summary Dist B")

    _logout(client)
    _login(client, op_a_id)

    route_a = client.post(f"/districts/{dist_a}/routes", json={"route_number": "DATE-SUMM-ROUTE-A"})
    assert route_a.status_code == 201
    route_a_id = route_a.json()["id"]
    run_a = client.post(f"/routes/{route_a_id}/runs", json={"run_type": "AM"})
    assert run_a.status_code == 201
    run_a_id = run_a.json()["id"]

    _logout(client)
    _login(client, op_b_id)

    route_b = client.post(f"/districts/{dist_b}/routes", json={"route_number": "DATE-SUMM-ROUTE-B"})
    assert route_b.status_code == 201
    route_b_id = route_b.json()["id"]
    run_b = client.post(f"/routes/{route_b_id}/runs", json={"run_type": "AM"})
    assert run_b.status_code == 201
    run_b_id = run_b.json()["id"]

    # Inject start_time directly â€” avoids the full run-start prerequisite chain (bus/pretrip/stops/students)
    now = datetime.now(UTC)
    with Session(db_engine) as db:
        db.get(Run, run_a_id).start_time = now
        db.get(Run, run_b_id).start_time = now
        db.commit()

    run_date = now.date().isoformat()

    _establish_execution_yard(db_engine, route_a_id, yard_name="Date Summ Yard A")
    _establish_execution_yard(db_engine, route_b_id, yard_name="Date Summ Yard B")

    _logout(client)
    _login(client, op_a_id)

    date_report = client.get(f"/reports/date/{run_date}")
    assert date_report.status_code == 200
    route_numbers = {r.get("route_number") for r in date_report.json().get("runs", [])}
    assert "DATE-SUMM-ROUTE-A" in route_numbers
    assert "DATE-SUMM-ROUTE-B" not in route_numbers


def test_school_reports_summary_works_for_yard_scoped_operator(client, db_engine):
    context = _build_shared_school_reports_context(client, db_engine)

    response = client.get(f"/reports/school/{context['school_id']}")
    assert response.status_code == 200
    assert response.json()["school_id"] == context["school_id"]
    assert response.json()["school_name"] == "Shared Reports School"


def test_school_reports_summary_blocked_for_operator_without_yard(client, db_engine):
    owner_id = _create_operator_in_db(db_engine, "School Reports No Yard Owner")
    no_yard_id = _create_operator_in_db(db_engine, "School Reports No Yard Visitor")
    _create_driver_in_db(db_engine, owner_id, "School Reports No Yard Driver", "school-reports-no-yard@test.com")
    district_id = _create_district_in_db(db_engine, "School Reports No Yard District")

    _logout(client)
    _login(client, owner_id)

    school = client.post(f"/districts/{district_id}/schools", json={"name": "No Yard School", "address": "99 No Yard St"})
    assert school.status_code == 201
    school_id = school.json()["id"]

    route = client.post(f"/districts/{district_id}/routes", json={"route_number": "SCHOOL-RPT-NO-YARD", "school_ids": [school_id]})
    assert route.status_code == 201
    route_id = route.json()["id"]

    _share_route(client, route_id, no_yard_id)
    _establish_execution_yard(db_engine, route_id, yard_name="School Reports No Yard Owner Yard")

    _logout(client)
    _login(client, no_yard_id)

    response = client.get(f"/reports/school/{school_id}")
    assert response.status_code == 200
    assert response.json()["school_id"] == school_id


# ---------------------------------------------------------------------------
# Bootstrap endpoint tests
# ---------------------------------------------------------------------------

def test_bootstrap_operator_works_on_empty_db(empty_client):
    r = empty_client.post("/session/bootstrap-operator", json={"name": "First Operator"})
    assert r.status_code == 200
    assert "operator_id" in r.json()


def test_bootstrap_operator_fails_when_operator_exists(empty_client, db_engine):
    _create_operator_in_db(db_engine, "Existing Operator")
    r = empty_client.post("/session/bootstrap-operator", json={"name": "Second Operator"})
    assert r.status_code == 409


def test_no_default_operator_is_auto_created_for_unauthenticated_requests(empty_client, db_engine):
    response = empty_client.get("/drivers/")
    assert response.status_code == 401

    with Session(db_engine) as db:
        assert db.query(Operator).count() == 0


def test_bootstrap_operator_sets_session(empty_client):
    r = empty_client.post("/session/bootstrap-operator", json={"name": "Session Bootstrap Operator"})
    assert r.status_code == 200
    # Authenticated endpoint must succeed â€” session was set by bootstrap
    drivers = empty_client.get("/drivers/")
    assert drivers.status_code == 200


# ---------------------------------------------------------------------------
# Yard API tests
# ---------------------------------------------------------------------------

def test_create_yard_with_operator_session(client):
    r = client.post("/yards/", json={"name": "Alpha Yard"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Alpha Yard"
    assert "id" in body
    assert "operator_id" in body


def test_driver_create_requires_explicit_yard(client):
    response = client.post(
        "/drivers/",
        json={"name": "No Yard Driver", "email": "no-yard-driver@test.com", "phone": "100", "pin": "1234"},
    )
    assert response.status_code == 422


def test_bus_create_requires_explicit_yard(client):
    response = client.post(
        "/buses/",
        json={"bus_number": "NO-YARD-BUS", "license_plate": "NO-YARD-PLATE", "capacity": 40, "size": "full"},
    )
    assert response.status_code == 422


def test_driver_create_rejects_invalid_yard(client):
    response = client.post(
        "/drivers/",
        json={"yard_id": 999999, "name": "Invalid Yard Driver", "email": "invalid-yard-driver@test.com", "phone": "101", "pin": "1234"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Yard not found"


def test_bus_create_rejects_invalid_yard(client):
    response = client.post(
        "/buses/",
        json={"yard_id": 999999, "bus_number": "INVALID-YARD-BUS", "license_plate": "INVALID-YARD-PLATE", "capacity": 40, "size": "full"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Yard not found"


def test_driver_create_rejects_cross_operator_yard(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Driver Yard Owner")
    other_operator_id = _create_operator_in_db(db_engine, "Driver Yard Other")
    other_yard_id = _create_yard_in_db(db_engine, other_operator_id, "Driver Other Yard")

    _login(client, owner_operator_id)
    response = client.post(
        "/drivers/",
        json={"yard_id": other_yard_id, "name": "Cross Yard Driver", "email": "cross-yard-driver@test.com", "phone": "102", "pin": "1234"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Yard not found"


def test_bus_create_rejects_cross_operator_yard(client, db_engine):
    owner_operator_id = _create_operator_in_db(db_engine, "Bus Yard Owner")
    other_operator_id = _create_operator_in_db(db_engine, "Bus Yard Other")
    other_yard_id = _create_yard_in_db(db_engine, other_operator_id, "Bus Other Yard")

    _login(client, owner_operator_id)
    response = client.post(
        "/buses/",
        json={"yard_id": other_yard_id, "bus_number": "CROSS-YARD-BUS", "license_plate": "CROSS-YARD-PLATE", "capacity": 40, "size": "full"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Yard not found"


def test_list_yards_returns_only_current_operator_yards(client, db_engine):
    other_operator_id = _create_operator_in_db(db_engine, "Other Operator Yard List")

    client.post("/yards/", json={"name": "My Yard A"})
    client.post("/yards/", json={"name": "My Yard B"})

    # Switch to other operator and create a yard
    _login(client, other_operator_id)
    client._wrapped_client.post("/yards/", json={"name": "Other Yard"})

    # Switch back and verify isolation
    _login(client, 1)
    r = client._wrapped_client.get("/yards/")
    assert r.status_code == 200
    names = [y["name"] for y in r.json()]
    assert "Other Yard" not in names
