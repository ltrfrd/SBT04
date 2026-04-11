from tests.test_posttrip_feature_alignment import (
    _create_started_run_ready_for_posttrip,
    _submit_phase1,
    _submit_phase2,
)


def _mark_active_run_ready_for_posttrip(client, run_id: int) -> int:
    run_detail = client.get(f"/runs/{run_id}")
    assert run_detail.status_code == 200
    student_id = run_detail.json()["students"][0]["student_id"]

    arrive = client.post(f"/runs/{run_id}/arrive_stop?stop_sequence=1")
    assert arrive.status_code == 200

    pickup = client.post(f"/runs/{run_id}/pickup_student", json={"student_id": student_id})
    assert pickup.status_code == 200

    dropoff = client.post(f"/runs/{run_id}/dropoff_student", json={"student_id": student_id})
    assert dropoff.status_code == 200
    return student_id


def test_driver_workspace_keeps_posttrip_hidden_until_run_is_ready(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="DRV-UI-HIDDEN")
    login = client.post("/login", json={"driver_id": context["driver"]["id"], "pin": "1234"})
    assert login.status_code == 200

    response = client.get(f"/driver_run/{context['driver']['id']}?route_id={context['route']['id']}")
    assert response.status_code == 200

    body = response.text
    assert 'id="postTripPanel"' in body
    assert 'data-posttrip-visible="false"' in body
    assert 'data-posttrip-ready="false"' in body
    assert 'id="endActiveRunButton"' in body
    assert 'data-posttrip-phase2-completed="false"' in body
    assert 'disabled aria-disabled="true"' in body


def test_driver_workspace_shows_posttrip_section_when_run_is_ready(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="DRV-UI-READY")
    _mark_active_run_ready_for_posttrip(client, context["run"]["id"])

    login = client.post("/login", json={"driver_id": context["driver"]["id"], "pin": "1234"})
    assert login.status_code == 200

    response = client.get(f"/driver_run/{context['driver']['id']}?route_id={context['route']['id']}")
    assert response.status_code == 200

    body = response.text
    assert 'data-posttrip-visible="true"' in body
    assert 'data-posttrip-ready="true"' in body
    assert "Post-Trip Inspection" in body
    assert "Complete Phase 1" in body
    assert "Complete Phase 2" in body
    assert f'/runs/{context["run"]["id"]}/posttrip/phase1' in body
    assert f'/runs/{context["run"]["id"]}/posttrip/phase2' in body
    assert 'data-posttrip-phase2-completed="false"' in body


def test_driver_workspace_enables_end_run_after_phase2_completion(client):
    context = _create_started_run_ready_for_posttrip(client, route_number="DRV-UI-COMPLETE")
    _mark_active_run_ready_for_posttrip(client, context["run"]["id"])
    _submit_phase1(client, context["run"]["id"])
    _submit_phase2(client, context["run"]["id"])

    login = client.post("/login", json={"driver_id": context["driver"]["id"], "pin": "1234"})
    assert login.status_code == 200

    response = client.get(f"/driver_run/{context['driver']['id']}?route_id={context['route']['id']}")
    assert response.status_code == 200

    body = response.text
    assert 'data-posttrip-phase2-completed="true"' in body
    assert "Post-Trip completed. End Run is available." in body
    assert 'id="endActiveRunButton"' in body
    assert 'disabled aria-disabled="true"' not in body
