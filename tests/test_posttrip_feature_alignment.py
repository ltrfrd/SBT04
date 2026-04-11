import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models.dispatch_alert import DispatchAlert
from backend.models.posttrip import PostTripInspection

from tests.conftest import ensure_prepared_run_student


def _create_started_run_ready_for_posttrip(client, *, route_number: str = "POSTTRIP-ROUTE"):
    driver = client.post(
        "/drivers/",
        json={"name": f"{route_number} Driver", "email": f"{route_number.lower()}@test.com", "phone": "5551000", "pin": "1234"},
    )
    assert driver.status_code in (200, 201)

    route = client.post("/routes/", json={"route_number": route_number})
    assert route.status_code in (200, 201)
    route_id = route.json()["id"]

    assigned_driver = client.post(f"/routes/{route_id}/assign_driver/{driver.json()['id']}")
    assert assigned_driver.status_code in (200, 201)

    bus = client.post(
        "/buses/",
        json={
            "bus_number": f"{route_number}-BUS",
            "license_plate": f"{route_number[:3]}-POST",
            "capacity": 48,
            "size": "full",
        },
    )
    assert bus.status_code in (200, 201)

    assigned_bus = client.post(f"/routes/{route_id}/assign_bus/{bus.json()['id']}")
    assert assigned_bus.status_code == 200

    run = client.post(
        f"/routes/{route_id}/runs",
        json={
            "run_type": "PM",
            "scheduled_start_time": "15:00:00",
            "scheduled_end_time": "16:00:00",
        },
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/runs/{run_id}/stops",
        json={"name": f"{route_number} Stop", "sequence": 1, "type": "dropoff"},
    )
    assert stop.status_code in (200, 201)

    ensure_prepared_run_student(client, run_id)

    pretrip = client.post(
        "/pretrips/",
        json={
            "bus_number": bus.json()["bus_number"],
            "license_plate": bus.json()["license_plate"],
            "driver_name": driver.json()["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "14:00:00",
            "odometer": 55555,
            "inspection_place": "Yard",
            "use_type": "school_bus",
            "brakes_checked": True,
            "lights_checked": True,
            "tires_checked": True,
            "emergency_equipment_checked": True,
            "fit_for_duty": "yes",
            "no_defects": True,
            "signature": "driver-signature",
            "defects": [],
        },
    )
    assert pretrip.status_code in (200, 201)

    started = client._wrapped_client.post(f"/runs/start?run_id={run_id}")
    assert started.status_code in (200, 201)

    return {
        "driver": driver.json(),
        "route": route.json(),
        "bus": bus.json(),
        "run": started.json(),
    }


def _submit_phase1(client, run_id: int):
    response = client.post(
        f"/runs/{run_id}/posttrip/phase1",
        json={
            "phase1_no_students_remaining": True,
            "phase1_belongings_checked": True,
            "phase1_checked_sign_hung": True,
        },
    )
    assert response.status_code == 200
    return response


def _submit_phase2(client, run_id: int, *, exterior_status: str = "clear", exterior_description: str | None = None):
    payload = {
        "phase2_full_internal_recheck": True,
        "phase2_checked_to_cleared_switched": True,
        "phase2_rear_button_triggered": True,
        "exterior_status": exterior_status,
    }
    if exterior_description is not None:
        payload["exterior_description"] = exterior_description

    response = client.post(f"/runs/{run_id}/posttrip/phase2", json=payload)
    assert response.status_code == 200
    return response


def test_posttrip_endpoints_are_reachable_and_phase1_updates_single_record(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-REACH")
    run_id = context["run"]["id"]

    first = _submit_phase1(client, run_id).json()
    second = _submit_phase1(client, run_id).json()

    assert first["id"] == second["id"]
    assert second["run_id"] == run_id
    assert second["phase1_completed"] is True
    assert second["phase2_completed"] is False
    assert second["phase2_status"] == "pending"
    assert second["phase2_pending_since"] is not None

    fetched = client.get(f"/runs/{run_id}/posttrip")
    assert fetched.status_code == 200
    assert fetched.json()["phase2_decision_status"] in {
        "pending_recent_activity",
        "pending_no_recent_location",
        "pending_no_recent_driver_activity",
        "pending_low_confidence_inactive",
    }


def test_posttrip_phase2_requires_description_for_non_clear_status(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-VALIDATE")
    run_id = context["run"]["id"]
    _submit_phase1(client, run_id)

    response = client.post(
        f"/runs/{run_id}/posttrip/phase2",
        json={
            "phase2_full_internal_recheck": True,
            "phase2_checked_to_cleared_switched": True,
            "phase2_rear_button_triggered": True,
            "exterior_status": "major",
        },
    )

    assert response.status_code == 422
    assert "exterior_description is required" in response.text


def test_run_end_is_blocked_without_phase2_but_complete_endpoint_remains_legacy_compatible(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-END-BLOCK")
    run_id = context["run"]["id"]
    _submit_phase1(client, run_id)

    end_response = client.post(f"/runs/end?run_id={run_id}")
    assert end_response.status_code == 400
    assert end_response.json()["detail"] == "Post-trip phase 2 must be completed before ending the run"

    driver_end_response = client.post(f"/runs/end_by_driver?driver_id={context['driver']['id']}")
    assert driver_end_response.status_code == 400
    assert driver_end_response.json()["detail"] == "Post-trip phase 2 must be completed before ending the run"

    complete_response = client.post(f"/runs/{run_id}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["id"] == run_id
    assert complete_response.json()["is_completed"] is True


def test_run_end_is_allowed_after_phase2_completion(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-END-ALLOW")
    run_id = context["run"]["id"]
    _submit_phase1(client, run_id)
    phase2 = _submit_phase2(client, run_id).json()

    assert phase2["phase2_completed"] is True
    assert phase2["phase2_status"] == "completed"

    end_response = client.post(f"/runs/end?run_id={run_id}")
    assert end_response.status_code == 200
    assert end_response.json()["id"] == run_id
    assert end_response.json()["end_time"] is not None


def test_posttrip_major_defect_alert_is_created_once_and_is_per_run(client, db_engine):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-MAJOR")
    run_id = context["run"]["id"]
    _submit_phase1(client, run_id)

    first = _submit_phase2(client, run_id, exterior_status="major", exterior_description="Damaged body panel")
    second = _submit_phase2(client, run_id, exterior_status="major", exterior_description="Damaged body panel")

    assert first.status_code == 200
    assert second.status_code == 200

    with Session(db_engine) as db:
        alerts = (
            db.query(DispatchAlert)
            .filter(DispatchAlert.alert_type == "POSTTRIP_MAJOR_DEFECT")
            .filter(DispatchAlert.run_id == run_id)
            .filter(DispatchAlert.resolved.is_(False))
            .all()
        )

    assert len(alerts) == 1
    assert alerts[0].severity == "urgent"


def test_posttrip_neglect_alert_is_only_triggered_by_get_flow(client, db_engine):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-NEGLECT")
    run_id = context["run"]["id"]
    phase1 = _submit_phase1(client, run_id).json()
    assert phase1["neglect_flagged_at"] is None

    with Session(db_engine) as db:
        inspection = db.query(PostTripInspection).filter(PostTripInspection.run_id == run_id).first()
        assert inspection is not None
        stale_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=20)
        inspection.phase2_pending_since = stale_time
        inspection.last_driver_activity_at = stale_time
        inspection.last_location_update_at = stale_time
        db.commit()

    with Session(db_engine) as db:
        alerts_before = (
            db.query(DispatchAlert)
            .filter(DispatchAlert.alert_type == "POSTTRIP_NEGLECT")
            .filter(DispatchAlert.run_id == run_id)
            .all()
        )
    assert alerts_before == []

    response = client.get(f"/runs/{run_id}/posttrip")
    assert response.status_code == 200
    body = response.json()
    assert body["phase2_decision_status"] == "suspected_neglect_ready"
    assert body["neglect_flagged_at"] is not None

    with Session(db_engine) as db:
        alerts_after = (
            db.query(DispatchAlert)
            .filter(DispatchAlert.alert_type == "POSTTRIP_NEGLECT")
            .filter(DispatchAlert.run_id == run_id)
            .filter(DispatchAlert.resolved.is_(False))
            .all()
        )

    assert len(alerts_after) == 1


def test_websocket_gps_persists_posttrip_activity_fields_when_posttrip_exists(client, db_engine):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-WS")
    run_id = context["run"]["id"]
    _submit_phase1(client, run_id)

    with client._wrapped_client.websocket_connect(f"/ws/gps/{run_id}") as websocket:
        websocket.send_text(json.dumps({"lat": 39.7392, "lng": -104.9903}))
        message = websocket.receive_json()

    assert message["run_id"] == run_id
    assert message["lat"] == 39.7392
    assert message["lng"] == -104.9903

    with Session(db_engine) as db:
        inspection = db.query(PostTripInspection).filter(PostTripInspection.run_id == run_id).first()
        assert inspection is not None
        assert inspection.last_known_lat == 39.7392
        assert inspection.last_known_lng == -104.9903
        assert inspection.last_location_update_at is not None
        assert inspection.last_driver_activity_at is not None
