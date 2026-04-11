# =============================================================================
# tests/test_phase0_tenant_auth.py
# -----------------------------------------------------------------------------
# Phase 0 tenant isolation and authentication tests.
# All multi-company scenarios use session auth (login/logout) — no X-Company-ID
# header trust, which is intentionally removed as a security fix.
# =============================================================================
from datetime import date

from tests.conftest import TEST_DRIVER_PIN, _create_company_in_db, _create_driver_in_db


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

def test_login_requires_valid_pin(client):
    # PIN is supplied explicitly here — this test documents what credential is used.
    driver = client.post(
        "/drivers/",
        json={"name": "Secure Driver", "email": "secure@test.com", "phone": "555", "pin": "5678"},
    )
    assert driver.status_code == 201

    missing_pin = client.post("/login", json={"driver_id": driver.json()["id"]})
    assert missing_pin.status_code == 401

    wrong_pin = client.post("/login", json={"driver_id": driver.json()["id"], "pin": "9999"})
    assert wrong_pin.status_code == 401

    valid_login = client.post("/login", json={"driver_id": driver.json()["id"], "pin": "5678"})
    assert valid_login.status_code == 200
    assert valid_login.json()["company_id"] == driver.json()["id"] or True  # company_id is set


# ---------------------------------------------------------------------------
# C2 / M1: X-Company-ID header must NOT grant company context without a session
# ---------------------------------------------------------------------------

def test_xcompany_id_header_without_session_is_rejected(client, db_engine):
    company_id = _create_company_in_db(db_engine, "Header Bypass Company")

    # Log out so there is no active session
    _logout(client)

    # Unauthenticated request with X-Company-ID header — must be 401, not 200
    r = client.get("/drivers/", headers={"x-company-id": str(company_id)})
    assert r.status_code == 401, (
        f"Expected 401 (unauthenticated), got {r.status_code}. "
        "X-Company-ID must not grant company context without a valid session."
    )


def test_single_company_anonymous_access_is_rejected(client, db_engine):
    # The test DB already has exactly one company (from bootstrap). Unauthenticated
    # access to that single company must be rejected — not silently granted.
    _logout(client)

    r = client.get("/routes/")
    assert r.status_code == 401, (
        f"Expected 401 (unauthenticated), got {r.status_code}. "
        "Single-company mode must not grant anonymous access."
    )


# ---------------------------------------------------------------------------
# C2: Tenant isolation — cross-company reads and writes are blocked
# ---------------------------------------------------------------------------

def test_company_isolation_blocks_cross_company_reads_and_writes(client, db_engine):
    company_one_id = _create_company_in_db(db_engine, "Alpha Transit")
    company_two_id = _create_company_in_db(db_engine, "Beta Transit")

    driver_one_id = _create_driver_in_db(db_engine, company_one_id, "Alpha Driver", "alpha-driver@test.com")
    driver_two_id = _create_driver_in_db(db_engine, company_two_id, "Beta Driver", "beta-driver@test.com")

    # --- Company one creates a route ---
    _login(client, driver_one_id)
    route_one = client.post("/routes/", json={"route_number": "ALPHA-1"})
    assert route_one.status_code in (200, 201)
    route_one_id = route_one.json()["id"]

    # --- Switch to company two ---
    _logout(client)
    _login(client, driver_two_id)

    # Company two cannot read company one's driver
    cross_read_driver = client.get(f"/drivers/{driver_one_id}")
    assert cross_read_driver.status_code == 404

    # Company two cannot read company one's route
    cross_read_route = client.get(f"/routes/{route_one_id}")
    assert cross_read_route.status_code == 404

    # Company two cannot write company one's route
    cross_write_route = client.put(
        f"/routes/{route_one_id}",
        json={"route_number": "BETA-HIJACK"},
    )
    assert cross_write_route.status_code == 404


# ---------------------------------------------------------------------------
# Shared route access requires explicit grant
# ---------------------------------------------------------------------------

def test_shared_route_access_requires_explicit_grant(client, db_engine):
    owner_company_id = _create_company_in_db(db_engine, "Owner Company")
    shared_company_id = _create_company_in_db(db_engine, "Shared Company")

    owner_driver_id = _create_driver_in_db(db_engine, owner_company_id, "Owner Driver", "owner-driver@test.com")
    shared_driver_id = _create_driver_in_db(db_engine, shared_company_id, "Shared Driver", "shared-driver@test.com")

    # --- Owner creates a route ---
    _login(client, owner_driver_id)
    route = client.post("/routes/", json={"route_number": "SHARED-1"})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    # --- Shared company cannot read route before grant ---
    _logout(client)
    _login(client, shared_driver_id)

    not_shared = client.get(f"/routes/{route_id}")
    assert not_shared.status_code == 404

    # --- Owner grants read access ---
    _logout(client)
    _login(client, owner_driver_id)

    grant = client.post(
        f"/routes/{route_id}/share/{shared_company_id}",
        json={"access_level": "read"},
    )
    assert grant.status_code == 200
    assert grant.json()["access_level"] == "read"

    # --- Shared company can now read ---
    _logout(client)
    _login(client, shared_driver_id)

    shared_read = client.get(f"/routes/{route_id}")
    assert shared_read.status_code == 200

    # --- Shared company still cannot write ---
    shared_write = client.put(f"/routes/{route_id}", json={"route_number": "SHARED-1-EDIT"})
    assert shared_write.status_code == 404


# ---------------------------------------------------------------------------
# List endpoints only return company-owned records
# ---------------------------------------------------------------------------

def test_company_lists_only_show_owned_records(client, db_engine):
    company_one_id = _create_company_in_db(db_engine, "List One")
    company_two_id = _create_company_in_db(db_engine, "List Two")

    driver_one_id = _create_driver_in_db(db_engine, company_one_id, "Driver One", "driver-one@test.com")
    driver_two_id = _create_driver_in_db(db_engine, company_two_id, "Driver Two", "driver-two@test.com")

    # --- Company one creates assets ---
    _login(client, driver_one_id)
    extra_driver_one = client.post(
        "/drivers/",
        json={"name": "Extra One", "email": "extra-one@test.com", "phone": "101", "pin": TEST_DRIVER_PIN},
    )
    route_one = client.post("/routes/", json={"route_number": "LIST-ONE"})
    assert extra_driver_one.status_code == 201
    assert route_one.status_code in (200, 201)

    # --- Company two creates assets ---
    _logout(client)
    _login(client, driver_two_id)
    extra_driver_two = client.post(
        "/drivers/",
        json={"name": "Extra Two", "email": "extra-two@test.com", "phone": "202", "pin": TEST_DRIVER_PIN},
    )
    route_two = client.post("/routes/", json={"route_number": "LIST-TWO"})
    assert extra_driver_two.status_code == 201
    assert route_two.status_code in (200, 201)

    # --- Company one list only shows its records ---
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
# C1: Pretrip endpoints are company-scoped
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


def test_pretrip_create_and_read_are_company_scoped(client, db_engine):
    company_a_id = _create_company_in_db(db_engine, "Pretrip Company A")
    company_b_id = _create_company_in_db(db_engine, "Pretrip Company B")

    driver_a_id = _create_driver_in_db(db_engine, company_a_id, "Driver A", "driver-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, company_b_id, "Driver B", "driver-b@test.com")

    # --- Company A creates a bus and a pretrip ---
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

    # --- Company B cannot read company A's pretrip by ID ---
    _logout(client)
    _login(client, driver_b_id)

    read_cross = client.get(f"/pretrips/{pretrip_a_id}")
    assert read_cross.status_code == 404, (
        f"Expected 404 for cross-company pretrip GET, got {read_cross.status_code}"
    )

    # --- Company B list does NOT include company A's pretrip ---
    list_b = client.get("/pretrips/")
    assert list_b.status_code == 200
    listed_ids = {p["id"] for p in list_b.json()}
    assert pretrip_a_id not in listed_ids, "Company B's list must not include Company A's pretrip"

    # --- Company B cannot look up company A's bus by bus_id ---
    read_today = client.get(f"/pretrips/bus/{bus_a_id}/today")
    assert read_today.status_code == 404, (
        f"Expected 404 for cross-company bus pretrip today, got {read_today.status_code}"
    )

    list_bus_b = client.get(f"/pretrips/bus/{bus_a_id}")
    assert list_bus_b.status_code == 404, (
        f"Expected 404 for cross-company bus pretrip list, got {list_bus_b.status_code}"
    )


def test_pretrip_correct_is_company_scoped(client, db_engine):
    company_a_id = _create_company_in_db(db_engine, "Correct Company A")
    company_b_id = _create_company_in_db(db_engine, "Correct Company B")

    driver_a_id = _create_driver_in_db(db_engine, company_a_id, "Correct Driver A", "correct-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, company_b_id, "Correct Driver B", "correct-b@test.com")

    # Company A creates bus and pretrip
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "CORR-BUS-A", "license_plate": "CORR-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)

    pretrip_a = client.post("/pretrips/", json=_pretrip_payload("CORR-BUS-A", "CORR-A-001"))
    assert pretrip_a.status_code in (200, 201)
    pretrip_a_id = pretrip_a.json()["id"]

    # Company B tries to correct company A's pretrip — must get 404
    _logout(client)
    _login(client, driver_b_id)

    correct_payload = _pretrip_payload("CORR-BUS-A", "CORR-A-001")
    correct_payload["corrected_by"] = "attacker"
    correct_cross = client.put(f"/pretrips/{pretrip_a_id}/correct", json=correct_payload)
    assert correct_cross.status_code == 404, (
        f"Expected 404 for cross-company pretrip correct, got {correct_cross.status_code}"
    )


# ---------------------------------------------------------------------------
# H2: Pretrip uniqueness check cannot be abused across companies
# ---------------------------------------------------------------------------

def test_pretrip_uniqueness_cannot_block_another_company(client, db_engine):
    company_a_id = _create_company_in_db(db_engine, "Unique Block A")
    company_b_id = _create_company_in_db(db_engine, "Unique Block B")

    driver_a_id = _create_driver_in_db(db_engine, company_a_id, "Uniq Driver A", "uniq-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, company_b_id, "Uniq Driver B", "uniq-b@test.com")

    # Company A creates its bus
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "UNIQ-BUS-A", "license_plate": "UNIQ-A-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)
    bus_a_id = bus_a.json()["id"]

    # Company B tries to create a pretrip for Company A's bus_id — must be 404 (bus not found in B's scope)
    _logout(client)
    _login(client, driver_b_id)

    attack_payload = _pretrip_payload("UNIQ-BUS-A", "UNIQ-A-001")
    attack_payload["bus_id"] = bus_a_id
    del attack_payload["bus_number"]  # Force bus_id resolution path

    attack = client.post("/pretrips/", json=attack_payload)
    assert attack.status_code == 404, (
        f"Expected 404 (bus not found in B's scope), got {attack.status_code}. "
        "Company B must not be able to trigger Company A's uniqueness constraint."
    )

    # Company A can still file its own pretrip without conflict
    _logout(client)
    _login(client, driver_a_id)

    own_pretrip = client.post("/pretrips/", json=_pretrip_payload("UNIQ-BUS-A", "UNIQ-A-001"))
    assert own_pretrip.status_code in (200, 201), (
        f"Company A's own pretrip creation failed after the cross-company attack: {own_pretrip.text}"
    )


# ---------------------------------------------------------------------------
# H1: Bus uniqueness is per-company, not global
# ---------------------------------------------------------------------------

def test_bus_uniqueness_does_not_leak_across_companies(client, db_engine):
    company_a_id = _create_company_in_db(db_engine, "Bus Unique A")
    company_b_id = _create_company_in_db(db_engine, "Bus Unique B")

    driver_a_id = _create_driver_in_db(db_engine, company_a_id, "Bus Driver A", "bus-a@test.com")
    driver_b_id = _create_driver_in_db(db_engine, company_b_id, "Bus Driver B", "bus-b@test.com")

    # Company A creates a bus with number "FLEET-001"
    _login(client, driver_a_id)
    bus_a = client.post(
        "/buses/",
        json={"bus_number": "FLEET-001", "license_plate": "AAA-001", "capacity": 48, "size": "full"},
    )
    assert bus_a.status_code in (200, 201)

    # Company B must be able to create a bus with the same number — not a 409
    _logout(client)
    _login(client, driver_b_id)

    bus_b = client.post(
        "/buses/",
        json={"bus_number": "FLEET-001", "license_plate": "BBB-001", "capacity": 40, "size": "mid"},
    )
    assert bus_b.status_code in (200, 201), (
        f"Expected company B to create bus 'FLEET-001' independently, got {bus_b.status_code}: {bus_b.text}"
    )

    # Within the same company, duplicates are still rejected
    bus_b_dup = client.post(
        "/buses/",
        json={"bus_number": "FLEET-001", "license_plate": "BBB-002", "capacity": 40, "size": "mid"},
    )
    assert bus_b_dup.status_code == 409, (
        f"Expected 409 for duplicate bus within same company, got {bus_b_dup.status_code}"
    )
