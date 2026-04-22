# -----------------------------------------------------------
# Run pre-trip enforcement tests
# - Verify scheduled create payloads and start blocking rules
# -----------------------------------------------------------
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy.orm import Session

from backend.models.dispatch_alert import DispatchAlert

from tests.conftest import ensure_route_has_execution_yard


def _pretrip_payload(context, **overrides):
    payload = {
        "bus_number": context["bus"]["bus_number"],
        "license_plate": context["bus"]["license_plate"],
        "driver_name": context["driver"]["name"],
        "inspection_date": datetime.now().date().isoformat(),
        "inspection_time": "06:15:00",
        "odometer": 12345,
        "inspection_place": "Main Yard",
        "use_type": "school_bus",
        "brakes_checked": True,
        "lights_checked": True,
        "tires_checked": True,
        "emergency_equipment_checked": True,
        "fit_for_duty": "yes",
        "no_defects": True,
        "signature": "driver-signature",
        "defects": [],
    }
    payload.update(overrides)
    return payload


# -----------------------------------------------------------
# - Shared setup helper
# - Create one prepared run with driver and active bus
# -----------------------------------------------------------
def _create_pretrip_enforced_run(client, *, route_number: str, run_type: str = "AM", scheduled_start_time: str = "07:00:00"):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": f"{route_number} Driver", "email": f"{route_number.lower()}@test.com", "phone": "5550000", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)

    district = client.post(
        "/districts/",
        json={"name": f"{route_number} District"},
    )
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": f"{route_number} School", "address": f"{route_number} Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": route_number, "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    ensure_route_has_execution_yard(client, route_id)

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assigned_driver.status_code in (200, 201)

    bus = client.post("/buses/", json={"yard_id": client.ensure_current_operator_yard_id(), 
            "bus_number": f"{route_number}-BUS",
            "license_plate": f"{route_number[:3]}-PLATE",
            "capacity": 48,
            "size": "full",
        },
    )
    assert bus.status_code in (200, 201)

    assigned_bus = client.post(f"/routes/{route_id}/assign_bus/{bus.json()['id']}")
    assert assigned_bus.status_code == 200

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={
            "run_type": run_type,
            "scheduled_start_time": scheduled_start_time,
            "scheduled_end_time": "08:00:00",
        },
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": f"{route_number} Stop", "sequence": 1, "type": "pickup"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students",
        json={"name": f"{route_number} Student", "grade": "1", "school_id": school_id},
    )
    assert student.status_code in (200, 201)

    return {
        "driver": driver.json(),
        "route": route.json(),
        "bus": bus.json(),
        "run": run.json(),
    }


def test_run_create_returns_scheduled_fields(client):
    context = _create_pretrip_enforced_run(client, route_number="SCHEDULED-RUN-1")

    assert context["run"]["scheduled_start_time"] == "07:00:00"
    assert context["run"]["scheduled_end_time"] == "08:00:00"


def test_start_run_blocks_when_no_pretrip_for_active_bus(client):
    context = _create_pretrip_enforced_run(client, route_number="NO-PRETRIP-START")

    response = client._wrapped_client.post(f"/runs/start?run_id={context['run']['id']}")

    assert response.status_code == 400
    assert response.json()["detail"] == "No pre-trip found for active bus for today"


def test_start_run_blocks_when_route_has_no_active_bus(client):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": "No Bus Driver", "email": "no.bus.driver@test.com", "phone": "5550001", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)

    district = client.post(
        "/districts/",
        json={"name": "NO-ACTIVE-BUS-START District"},
    )
    assert district.status_code in (200, 201)
    district_id = district.json()["id"]

    school = client.post(
        f"/districts/{district_id}/schools",
        json={"name": "NO-ACTIVE-BUS-START School", "address": "No Active Bus Way"},
    )
    assert school.status_code in (200, 201)
    school_id = school.json()["id"]

    route = client.post(
        f"/districts/{district_id}/routes",
        json={"route_number": "NO-ACTIVE-BUS-START", "school_ids": [school_id]},
    )
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]
    ensure_route_has_execution_yard(client, route_id)

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assigned_driver.status_code in (200, 201)

    run = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs",
        json={
            "run_type": "AM",
            "scheduled_start_time": "07:00:00",
            "scheduled_end_time": "08:00:00",
        },
    )
    assert run.status_code in (200, 201)

    stop = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run.json()['id']}/stops",
        json={"name": "No Bus Stop", "sequence": 1, "type": "pickup"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run.json()['id']}/stops/{stop_id}/students",
        json={"name": "No Bus Student", "grade": "1", "school_id": school_id},
    )
    assert student.status_code in (200, 201)

    response = client._wrapped_client.post(f"/runs/start?run_id={run.json()['id']}")

    assert response.status_code == 400
    assert response.json()["detail"] == "Route has no active bus assigned"


def test_start_run_blocks_when_driver_marked_not_fit(client):
    context = _create_pretrip_enforced_run(client, route_number="NOT-FIT-START")

    pretrip = client.post(
        "/pretrips/",
        json=_pretrip_payload(context, fit_for_duty="no"),
    )
    assert pretrip.status_code in (200, 201)

    response = client._wrapped_client.post(f"/runs/start?run_id={context['run']['id']}")

    assert response.status_code == 400
    assert response.json()["detail"] == "Run blocked: driver marked not fit for duty"


def test_start_run_blocks_when_major_defect_reported(client):
    context = _create_pretrip_enforced_run(client, route_number="MAJOR-DEFECT-START")

    pretrip = client.post(
        "/pretrips/",
        json=_pretrip_payload(
            context,
            inspection_time="06:20:00",
            odometer=22345,
            no_defects=False,
            defects=[{"description": "Brake issue", "severity": "major"}],
        ),
    )
    assert pretrip.status_code in (200, 201)

    response = client._wrapped_client.post(f"/runs/start?run_id={context['run']['id']}")

    assert response.status_code == 400
    assert response.json()["detail"] == "Run blocked: major defect reported on pre-trip"


def test_pretrip_create_and_correct_persist_checklist_history(client):
    context = _create_pretrip_enforced_run(client, route_number="PRETRIP-CHECKLIST-PERSIST")

    created = client.post(
        "/pretrips/",
        json=_pretrip_payload(
            context,
            brakes_checked=True,
            lights_checked=False,
            tires_checked=True,
            emergency_equipment_checked=False,
        ),
    )
    assert created.status_code in (200, 201)
    created_body = created.json()

    assert created_body["brakes_checked"] is True
    assert created_body["lights_checked"] is False
    assert created_body["tires_checked"] is True
    assert created_body["emergency_equipment_checked"] is False

    corrected = client.put(
        f"/pretrips/{created_body['id']}/correct",
        json=_pretrip_payload(
            context,
            inspection_time="06:25:00",
            brakes_checked=False,
            lights_checked=True,
            tires_checked=False,
            emergency_equipment_checked=True,
            corrected_by=context["driver"]["name"],
        ),
    )
    assert corrected.status_code == 200
    corrected_body = corrected.json()

    assert corrected_body["brakes_checked"] is False
    assert corrected_body["lights_checked"] is True
    assert corrected_body["tires_checked"] is False
    assert corrected_body["emergency_equipment_checked"] is True
    assert corrected_body["original_payload"]["brakes_checked"] is True
    assert corrected_body["original_payload"]["lights_checked"] is False
    assert corrected_body["original_payload"]["tires_checked"] is True
    assert corrected_body["original_payload"]["emergency_equipment_checked"] is False


def test_start_run_creates_one_missing_pretrip_alert_within_window(client, db_engine):
    current_day = datetime.now()

    class _FixedAlertDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                current_day.year,
                current_day.month,
                current_day.day,
                12,
                0,
                0,
                tzinfo=tz,
            )

    context = _create_pretrip_enforced_run(
        client,
        route_number="MISSING-PRETRIP-ALERT",
        scheduled_start_time="12:10:00",
    )

    with patch("backend.utils.pretrip_alerts.datetime", _FixedAlertDateTime):
        first_response = client._wrapped_client.post(f"/runs/start?run_id={context['run']['id']}")
        second_response = client._wrapped_client.post(f"/runs/start?run_id={context['run']['id']}")

    assert first_response.status_code == 400
    assert second_response.status_code == 400

    with Session(db_engine) as db:
        alerts = (
            db.query(DispatchAlert)
            .filter(DispatchAlert.alert_type == "MISSING_PRETRIP_BEFORE_RUN_START")
            .filter(DispatchAlert.run_id == context["run"]["id"])
            .filter(DispatchAlert.resolved.is_(False))
            .all()
        )

    assert len(alerts) == 1
