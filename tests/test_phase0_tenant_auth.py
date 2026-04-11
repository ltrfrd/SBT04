# =============================================================================
# tests/test_phase0_tenant_auth.py
# -----------------------------------------------------------------------------
# Phase 0 tenant isolation and authentication tests.
# All multi-operator scenarios use session auth (login/logout) — no X-Operator-ID
# header trust, which is intentionally removed as a security fix.
# =============================================================================
from datetime import date

from sqlalchemy.orm import Session

from backend.models.driver import Driver
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

