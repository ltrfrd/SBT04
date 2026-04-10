from datetime import date

from tests.test_run_pretrip_enforcement import _create_pretrip_enforced_run


def _login_and_open_workspace(client, context):
    login = client.post("/login", json={"driver_id": context["driver"]["id"]})
    assert login.status_code == 200
    return client.get(f"/driver_run/{context['driver']['id']}?route_id={context['route']['id']}")


def test_driver_workspace_requires_pretrip_before_start_run(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-REQ")

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert "Pre-Trip Inspection" in body
    assert 'data-pretrip-valid="false"' in body
    assert 'data-pretrip-submit-endpoint="/pretrips/"' in body
    assert "Submit Pre-Trip" in body
    assert 'data-pretrip-valid="false"' in body
    assert 'disabled aria-disabled="true"' in body


def test_driver_workspace_valid_pretrip_enables_start_run(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-VALID")

    pretrip = client.post(
        "/pretrips/",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:20:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "yes",
            "no_defects": True,
            "signature": context["driver"]["name"],
            "defects": [],
        },
    )
    assert pretrip.status_code in (200, 201)

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert 'data-pretrip-valid="true"' in body
    assert "Pre-Trip completed" in body
    assert "Bus fit for duty" in body


def test_driver_workspace_invalid_pretrip_keeps_start_locked(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-INVALID")

    pretrip = client.post(
        "/pretrips/",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:25:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "no",
            "no_defects": False,
            "signature": context["driver"]["name"],
            "defects": [{"description": "Brake pressure issue", "severity": "major"}],
        },
    )
    assert pretrip.status_code in (200, 201)

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert 'data-pretrip-valid="false"' in body
    assert "Pre-Trip invalid" in body
    assert "Bus not fit for duty" in body
    assert "Brake pressure issue" in body
    assert 'id="editPreTripButton"' in body
    assert f'data-pretrip-id="{pretrip.json()["id"]}"' in body
    assert f'data-pretrip-correct-endpoint="/pretrips/{pretrip.json()["id"]}/correct"' in body


def test_driver_workspace_invalid_pretrip_exposes_correction_action(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-CORRECT")

    pretrip = client.post(
        "/pretrips/",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:30:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "no",
            "no_defects": False,
            "signature": context["driver"]["name"],
            "defects": [{"description": "Rear light issue", "severity": "major"}],
        },
    )
    assert pretrip.status_code in (200, 201)

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert "Edit Pre-Trip" in body
    assert 'id="cancelPreTripEditButton"' in body
    assert 'data-pretrip-editing="false"' in body


def test_corrected_valid_pretrip_unlocks_start_run_in_workspace(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-UNLOCK")

    pretrip = client.post(
        "/pretrips/",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:35:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "no",
            "no_defects": False,
            "signature": context["driver"]["name"],
            "defects": [{"description": "Initial brake issue", "severity": "major"}],
        },
    )
    assert pretrip.status_code in (200, 201)
    pretrip_id = pretrip.json()["id"]

    corrected = client.put(
        f"/pretrips/{pretrip_id}/correct",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:40:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "yes",
            "no_defects": True,
            "signature": context["driver"]["name"],
            "corrected_by": context["driver"]["name"],
            "defects": [],
        },
    )
    assert corrected.status_code == 200

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert 'data-pretrip-valid="true"' in body
    assert "Pre-Trip completed" in body
    assert "Bus fit for duty" in body


def test_corrected_still_invalid_pretrip_remains_blocked(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-STILL-BLOCKED")

    pretrip = client.post(
        "/pretrips/",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:45:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "no",
            "no_defects": False,
            "signature": context["driver"]["name"],
            "defects": [{"description": "Initial issue", "severity": "major"}],
        },
    )
    assert pretrip.status_code in (200, 201)
    pretrip_id = pretrip.json()["id"]

    corrected = client.put(
        f"/pretrips/{pretrip_id}/correct",
        json={
            "bus_id": context["bus"]["id"],
            "bus_number": context["bus"]["bus_number"],
            "license_plate": context["bus"]["license_plate"],
            "driver_name": context["driver"]["name"],
            "inspection_date": date.today().isoformat(),
            "inspection_time": "06:50:00",
            "odometer": 0,
            "inspection_place": "Driver Workspace",
            "use_type": "school_bus",
            "fit_for_duty": "no",
            "no_defects": False,
            "signature": context["driver"]["name"],
            "corrected_by": context["driver"]["name"],
            "defects": [{"description": "Updated transmission issue", "severity": "major"}],
        },
    )
    assert corrected.status_code == 200

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert 'data-pretrip-valid="false"' in body
    assert "Pre-Trip invalid" in body
    assert "Updated transmission issue" in body
    assert "Edit Pre-Trip" in body


def test_driver_workspace_pretrip_form_exposes_selected_bus_hooks(client):
    context = _create_pretrip_enforced_run(client, route_number="DRV-PRETRIP-HOOKS")

    response = _login_and_open_workspace(client, context)
    assert response.status_code == 200

    body = response.text
    assert f'data-pretrip-bus-id="{context["bus"]["id"]}"' in body
    assert f'data-pretrip-bus-number="{context["bus"]["bus_number"]}"' in body
    assert f'data-pretrip-license-plate="{context["bus"]["license_plate"]}"' in body
    assert 'id="preTripFitForDuty"' in body
    assert 'id="submitPreTripButton"' in body
