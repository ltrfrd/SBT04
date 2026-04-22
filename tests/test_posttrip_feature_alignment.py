import json
from base64 import b64decode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.dispatch_alert import DispatchAlert
from backend.models.posttrip import PostTripInspection, PostTripPhoto

from tests.conftest import ensure_route_has_execution_yard


def _create_started_run_ready_for_posttrip(client, *, route_number: str = "POSTTRIP-ROUTE"):
    driver = client.post("/drivers/", json={"yard_id": client.ensure_current_operator_yard_id(), "name": f"{route_number} Driver", "email": f"{route_number.lower()}@test.com", "phone": "5551000", "pin": "1234"},
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
            "license_plate": f"{route_number[:3]}-POST",
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
            "run_type": "PM",
            "scheduled_start_time": "15:00:00",
            "scheduled_end_time": "16:00:00",
        },
    )
    assert run.status_code in (200, 201)
    run_id = run.json()["id"]

    stop = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops",
        json={"name": f"{route_number} Stop", "sequence": 1, "type": "dropoff"},
    )
    assert stop.status_code in (200, 201)
    stop_id = stop.json()["id"]

    student = client.post(
        f"/districts/{district_id}/routes/{route_id}/runs/{run_id}/stops/{stop_id}/students",
        json={"name": f"{route_number} Student", "grade": "1", "school_id": school_id},
    )
    assert student.status_code in (200, 201)

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
    capture_token = _cache_posttrip_capture_token(client, run_id)

    return {
        "driver": driver.json(),
        "route": route.json(),
        "bus": bus.json(),
        "run": started.json(),
        "capture_token": capture_token,
    }


def _make_test_image(filename: str, color: tuple[int, int, int]) -> tuple[str, bytes, str]:
    del color
    jpeg_bytes = b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBUQEBAVFRUVFRUVFRUVFRUVFRUVFRUWFhUV"
        "FRUYHSggGBolHRUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGxAQGi0lHyUtLS0tLS0tLS0tLS0t"
        "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBIgACEQEDEQH/xAAVAAEBAAAA"
        "AAAAAAAAAAAAAAABAv/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAdAf/8QAFBABAAAA"
        "AAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAEP/aAAgBAwEBPwF//8QA"
        "FBEBAAAAAAAAAAAAAAAAAAAAEP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAEP/aAAgBAQAG"
        "PwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAEP/aAAgBAQABPyF//9k="
    )
    return filename, jpeg_bytes, "image/jpeg"


def _get_posttrip_capture_token_for_run(client, run_id: int) -> str:
    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    run_body = run_response.json()

    workspace_response = client.get(
        f"/driver_run/{run_body['driver_id']}?route_id={run_body['route_id']}"
    )
    assert workspace_response.status_code == 200

    match = re.search(r'data-capture-token="([^"]+)"', workspace_response.text)
    assert match is not None
    return match.group(1)


def _cache_posttrip_capture_token(client, run_id: int) -> str:
    token = _get_posttrip_capture_token_for_run(client, run_id)
    cache = getattr(client, "_posttrip_capture_tokens", {})
    cache[run_id] = token
    setattr(client, "_posttrip_capture_tokens", cache)
    return token


def _get_cached_posttrip_capture_token(client, run_id: int) -> str:
    cache = getattr(client, "_posttrip_capture_tokens", {})
    token = cache.get(run_id)
    if token:
        return token
    return _cache_posttrip_capture_token(client, run_id)


def _submit_phase1(client, run_id: int, *, include_image: bool = True, capture_token: str | None = None):
    data = {
        "phase1_no_students_remaining": "true",
        "phase1_belongings_checked": "true",
        "phase1_checked_sign_hung": "true",
        "capture_token": capture_token or _get_cached_posttrip_capture_token(client, run_id),
    }
    files = {}
    if include_image:
        files["phase1_rear_to_front_image"] = _make_test_image("phase1.jpg", (40, 90, 150))
    response = client.post(f"/runs/{run_id}/posttrip/phase1", data=data, files=files or None)
    return response


def _submit_phase2(
    client,
    run_id: int,
    *,
    include_rear_image: bool = True,
    include_cleared_sign_image: bool = True,
    exterior_status: str = "clear",
    exterior_description: str | None = None,
    capture_token: str | None = None,
):
    data = {
        "phase2_full_internal_recheck": "true",
        "phase2_checked_to_cleared_switched": "true",
        "phase2_rear_button_triggered": "true",
        "exterior_status": exterior_status,
        "capture_token": capture_token or _get_cached_posttrip_capture_token(client, run_id),
    }
    if exterior_description is not None:
        data["exterior_description"] = exterior_description

    files = {}
    if include_rear_image:
        files["phase2_rear_to_front_image"] = _make_test_image("phase2-rear.jpg", (10, 120, 80))
    if include_cleared_sign_image:
        files["phase2_cleared_sign_image"] = _make_test_image("phase2-cleared.jpg", (220, 220, 40))

    response = client.post(f"/runs/{run_id}/posttrip/phase2", data=data, files=files or None)
    return response


def _end_run(client, run_id: int, *, driver_id: int | None = None):
    if driver_id is not None:
        return client.post(f"/runs/end_by_driver?driver_id={driver_id}")
    return client.post(f"/runs/end?run_id={run_id}")


def test_posttrip_phase1_fails_without_required_rear_photo(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P1-NO-PHOTO")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200

    response = _submit_phase1(client, run_id, include_image=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "Required photo missing: rear of bus photo"


def test_posttrip_phase1_succeeds_with_required_rear_photo(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P1-WITH-PHOTO")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200

    response = _submit_phase1(client, run_id)

    assert response.status_code == 200
    body = response.json()
    assert body["phase1_completed"] is True
    assert body["phase2_completed"] is False
    assert body["phase2_status"] == "pending"
    assert body["phase2_pending_since"] is not None
    assert len(body["photos"]) == 1
    assert body["photos"][0]["photo_type"] == "phase1_rear_photo"
    assert body["photos"][0]["source"] == "camera"
    assert body["photos"][0]["file_path"].startswith("posttrip/run_")


def test_posttrip_backend_rejects_phase1_without_driver_workspace_capture_token(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P1-NO-TOKEN")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200

    response = client.post(
        f"/runs/{run_id}/posttrip/phase1",
        data={
            "phase1_no_students_remaining": "true",
            "phase1_belongings_checked": "true",
            "phase1_checked_sign_hung": "true",
            "capture_token": "invalid-token",
        },
        files={"phase1_rear_to_front_image": _make_test_image("phase1.jpg", (40, 90, 150))},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid photo submission"


def test_posttrip_phase2_fails_without_phase1_complete(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P2-NO-P1")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200

    response = _submit_phase2(client, run_id)

    assert response.status_code == 400
    assert response.json()["detail"] == "Post-Trip Inspection Phase 1 must be completed first"


def test_posttrip_phase2_fails_if_any_required_image_is_missing(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P2-MISSING-ONE")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200
    phase1 = _submit_phase1(client, run_id)
    assert phase1.status_code == 200

    missing_rear = _submit_phase2(client, run_id, include_rear_image=False)
    assert missing_rear.status_code == 400
    missing_rear_body = missing_rear.json()
    assert missing_rear_body["detail"] == "Required photo missing: final rear of bus photo"

    missing_sign = _submit_phase2(client, run_id, include_cleared_sign_image=False)
    assert missing_sign.status_code == 400
    assert missing_sign.json()["detail"] == "Required photo missing: cleared sign photo"


def test_posttrip_phase2_succeeds_with_both_required_images(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P2-SUCCESS")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200
    phase1 = _submit_phase1(client, run_id)
    assert phase1.status_code == 200

    response = _submit_phase2(client, run_id)

    assert response.status_code == 200
    body = response.json()
    assert body["phase2_completed"] is True
    assert body["phase2_status"] == "completed"
    photo_types = {item["photo_type"] for item in body["photos"]}
    assert photo_types == {
        "phase1_rear_photo",
        "phase2_rear_photo",
        "phase2_cleared_sign_photo",
    }


def test_posttrip_phase1_requires_run_to_be_ended_and_complete_requires_both_phases(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-END-BLOCK")
    run_id = context["run"]["id"]

    phase1_while_active = _submit_phase1(client, run_id)
    assert phase1_while_active.status_code == 400
    assert phase1_while_active.json()["detail"] == "Run must be ended before Post-Trip Phase 1"

    end_response = _end_run(client, run_id)
    assert end_response.status_code == 200
    assert end_response.json()["end_time"] is not None

    complete_response = client.post(f"/runs/{run_id}/complete")
    assert complete_response.status_code == 400
    assert complete_response.json()["detail"] == "Post-trip phases 1 and 2 must be completed before completing the run"


def test_run_end_by_driver_is_allowed_before_posttrip_and_completion_requires_both_phases(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-END-ALLOW")
    run_id = context["run"]["id"]
    end_response = _end_run(client, run_id, driver_id=context["driver"]["id"])
    assert end_response.status_code == 200
    assert end_response.json()["id"] == run_id
    assert end_response.json()["end_time"] is not None

    phase1 = _submit_phase1(client, run_id)
    assert phase1.status_code == 200
    phase2 = _submit_phase2(client, run_id)
    assert phase2.status_code == 200

    complete_response = client.post(f"/runs/{run_id}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["id"] == run_id
    assert complete_response.json()["is_completed"] is True


def test_driver_cannot_replace_photo_after_phase_completion(client, db_engine):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P1-LOCK")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200
    response = _submit_phase1(client, run_id)
    assert response.status_code == 200

    locked_response = _submit_phase1(client, run_id)
    assert locked_response.status_code == 400
    assert locked_response.json()["detail"] == "Post-Trip Phase 1 is already completed and photo replacement is locked"

    with Session(db_engine) as db:
        photo_rows = db.query(PostTripPhoto).filter(PostTripPhoto.run_id == run_id).all()
        assert len(photo_rows) == 1


def test_pre_phase_retake_replacement_updates_existing_photo_cleanly(client, db_engine):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-P1-RETAKE")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200

    with Session(db_engine) as db:
        inspection = PostTripInspection(
            run_id=run_id,
            bus_id=context["bus"]["id"],
            route_id=context["route"]["id"],
            driver_id=context["driver"]["id"],
            phase1_completed=False,
            phase2_completed=False,
            phase2_status="not_started",
        )
        db.add(inspection)
        db.flush()

        old_relative_path = "posttrip/run_{}/phase1/phase1_rear_to_front_existing.jpg".format(run_id)
        old_absolute_path = Path(settings.MEDIA_ROOT) / old_relative_path
        old_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        old_absolute_path.write_bytes(_make_test_image("existing.jpg", (200, 10, 10))[1])

        photo = PostTripPhoto(
            posttrip_inspection_id=inspection.id,
            run_id=run_id,
            phase="phase1",
            photo_type="phase1_rear_to_front",
            file_path=old_relative_path,
            mime_type="image/jpeg",
            file_size_bytes=old_absolute_path.stat().st_size,
            source="camera",
            captured_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(photo)
        db.commit()
        photo_id = photo.id

    response = _submit_phase1(client, run_id)
    assert response.status_code == 200

    with Session(db_engine) as db:
        photo_rows = db.query(PostTripPhoto).filter(PostTripPhoto.run_id == run_id).all()
        assert len(photo_rows) == 1
        assert photo_rows[0].id == photo_id
        assert photo_rows[0].file_path != old_relative_path
        assert not (Path(settings.MEDIA_ROOT) / old_relative_path).exists()
        assert (Path(settings.MEDIA_ROOT) / photo_rows[0].file_path).exists()


def test_posttrip_output_includes_photo_metadata(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-OUTPUT")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200
    assert _submit_phase1(client, run_id).status_code == 200
    assert _submit_phase2(client, run_id).status_code == 200

    response = client.get(f"/runs/{run_id}/posttrip")

    assert response.status_code == 200
    body = response.json()
    assert "photos" in body
    assert len(body["photos"]) == 3
    first = body["photos"][0]
    assert {"id", "phase", "photo_type", "file_path", "mime_type", "file_size_bytes", "source", "captured_at"} <= set(first.keys())


def test_posttrip_phase2_requires_description_for_non_clear_status(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-VALIDATE")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200
    assert _submit_phase1(client, run_id).status_code == 200

    response = _submit_phase2(client, run_id, exterior_status="major", exterior_description=None)

    assert response.status_code == 422
    assert "exterior_description is required" in response.text


def test_posttrip_major_defect_alert_is_created_once_and_is_per_run(client, db_engine):
    context = _create_started_run_ready_for_posttrip(client, route_number="POSTTRIP-MAJOR")
    run_id = context["run"]["id"]
    assert _end_run(client, run_id).status_code == 200
    assert _submit_phase1(client, run_id).status_code == 200

    first = _submit_phase2(client, run_id, exterior_status="major", exterior_description="Damaged body panel")
    second = _submit_phase2(client, run_id, exterior_status="major", exterior_description="Damaged body panel")

    assert first.status_code == 200
    assert second.status_code == 400

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
    assert _end_run(client, run_id).status_code == 200
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
    assert _end_run(client, run_id).status_code == 200
    assert _submit_phase1(client, run_id).status_code == 200

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
