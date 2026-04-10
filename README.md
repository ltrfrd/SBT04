# SBT

## Project Overview
SBT is a school bus operations backend built with FastAPI, SQLAlchemy, Alembic, and Jinja templates.

The current implementation includes:

- route, run, stop, and student management
- planned run scheduling with required `scheduled_start_time` and `scheduled_end_time`
- flexible runtime stop execution
- bus-level Pre-Trip Inspection
- per-run Post-Trip Inspection
- run-start safety enforcement from Pre-Trip Inspection
- run-end safety enforcement from Post-Trip Inspection on selected close paths
- route primary bus and active bus control
- persistent dispatch alerts for Pre-Trip Inspection and Post-Trip Inspection conditions

## Core Features

### Flexible Run Execution
- Runtime stop handling remains flexible
- `POST /runs/{run_id}/arrive_stop` updates the actual runtime location
- `POST /runs/{run_id}/next_stop` remains a compatibility helper
- pickup and dropoff actions still depend on the current actual stop

### Pre-Trip Inspection
- One Pre-Trip Inspection is allowed per bus per day
- The database links Pre-Trip Inspections by `bus_id`
- The current API remains backward-compatible with user-facing `bus_number` and `license_plate`
- Pre-Trip Inspection create/correct accepts `bus_id` (preferred) or `bus_number` (legacy compatibility). At least one is required.
- Pre-Trip Inspection input supports:
  - `driver_name`
  - `inspection_date`
  - `inspection_time`
  - `odometer`
  - `inspection_place`
  - `use_type` (`school_bus` or `charter`)
  - `brakes_checked`
  - `lights_checked`
  - `tires_checked`
  - `emergency_equipment_checked`
  - `fit_for_duty` (`yes` or `no`)
  - `no_defects`
  - `defects`
  - `signature`
- Pre-Trip records persist checklist history for brakes, lights, tires, and emergency equipment
- Those checklist fields are currently stored for future use but are not active in the driver workflow UI
- `no_defects = true` requires an empty defect list
- `no_defects = false` requires at least one defect row
- Defects are stored as nested rows with severity `minor` or `major`
- Pre-Trip Inspection supports create, read, list, and correction flows
- Corrections preserve `original_payload`

### Run Start Enforcement
- `POST /runs/start` validates the route's active bus
- Run start is blocked when:
  - no valid Pre-Trip Inspection exists for the active bus for today
  - `fit_for_duty = no`
  - any defect on today's Pre-Trip Inspection has severity `major`
- Run start is allowed when:
  - today's Pre-Trip Inspection exists for the active bus
  - `fit_for_duty = yes`
  - defects are empty or minor-only
- Early run start is not blocked by time-of-day rules in the start endpoint itself
- `POST /runs/start` still requires the run to already have stops and runtime student assignments

### Post-Trip Inspection
- Post-Trip Inspection is stored per run
- Phase 1 checklist includes:
  - no students remaining
  - belongings checked
  - checked sign hung
- Phase 2 checklist includes:
  - full internal recheck
  - checked-to-cleared sign switch
  - rear button triggered
  - exterior status: `clear`, `minor`, or `major`
  - exterior description when `minor` or `major`
- `POST /runs/{run_id}/posttrip/phase1` creates or updates the run's Post-Trip Inspection Phase 1 state
- `POST /runs/{run_id}/posttrip/phase2` updates the same Post-Trip Inspection record and finalizes Phase 2
- `POST /runs/end` and `POST /runs/end_by_driver` require Post-Trip Inspection Phase 2 completion
- `POST /runs/{run_id}/complete` remains legacy-compatible for the current reporting and completion flow
- The existing driver workspace page surfaces the active-run Post-Trip Phase 1 and Phase 2 flow and keeps End Run locked until Phase 2 is complete

### Post-Trip Inspection Decision Layer
- The system persists:
  - `phase2_pending_since`
  - `last_driver_activity_at`
  - `last_known_lat`
  - `last_known_lng`
  - `last_location_update_at`
  - `neglect_flagged_at`
- GPS heartbeat from the existing websocket stream is persisted into the run's Post-Trip Inspection when one exists
- That websocket persistence updates `last_known_lat`, `last_known_lng`, `last_location_update_at`, and `last_driver_activity_at`
- `GET /runs/{run_id}/posttrip` exposes decision fields for the current Post-Trip Inspection state
- Neglect classification is computed from pending time, driver activity, and location activity
- Neglect alerting is currently read-triggered from the GET inspection flow only
- `neglect_flagged_at` is stamped when that read-triggered neglect flow first flags the record
- No scheduler, background job, or autonomous monitoring loop is currently implemented for neglect detection

### Route Bus Control
- `Route.bus_id` remains a compatibility-facing bus pointer
- `Route.primary_bus_id` stores the default/base bus
- `Route.active_bus_id` stores the current operational bus
- `Route.clearance_note` stores an optional note when restoring the primary bus
- `assign_bus` sets the active bus and seeds the primary bus when the route has no primary bus yet
- `set_primary_bus` changes the default/base bus without forcing an active replacement when one already exists
- `set_active_bus` switches the operational bus while preserving the route's primary bus
- `restore_primary_bus` switches the active bus back to the primary bus
- Downstream run-start Pre-Trip Inspection checks use the route's active bus

### Dispatch Alerts
- Alert records are stored in `DispatchAlert`
- `backend/utils/pretrip_alerts.py` handles Pre-Trip Inspection alert creation, dedupe, and resolution
- `backend/utils/posttrip_alerts.py` handles Post-Trip Inspection alert creation, dedupe, and resolution
- Pre-Trip Inspection create/correct flows sync alerts for:
  - major defect reported on Pre-Trip Inspection
  - `fit_for_duty = no`
- Missing Pre-Trip Inspection alerts can occur near scheduled run start through the existing run-start side effect
- Post-Trip Inspection Phase 2 submission syncs the urgent major-defect alert when `exterior_status = major`
- Post-Trip Inspection neglect alerts are triggered only through explicit `GET /runs/{run_id}/posttrip` inspection flow when the decision layer returns `suspected_neglect_ready`
- The repo does not currently implement a scheduler or background polling loop for Pre-Trip Inspection or Post-Trip Inspection monitoring

## Workflow Summary
The current backend flow is:

1. Create buses, routes, runs, stops, and students.
2. Assign the route's primary bus and active bus as needed.
3. Create a Pre-Trip Inspection for the active bus for today.
4. Correct the Pre-Trip Inspection later if dispatch needs to overwrite the submitted values.
5. Create a planned run with `scheduled_start_time` and `scheduled_end_time`.
6. Start the prepared run.
7. The system blocks the start if the active bus has no valid Pre-Trip Inspection for today, if the Pre-Trip Inspection marks `fit_for_duty = no`, or if it contains a major defect.
8. Runtime stop progression continues through the existing flexible stop workflow.
9. Submit Post-Trip Inspection Phase 1 and then Phase 2 for the run.
10. `POST /runs/end` and `POST /runs/end_by_driver` require Post-Trip Inspection Phase 2, while `POST /runs/{run_id}/complete` remains the legacy-compatible completion path.

## Driver Workflow
- The driver workspace page requires a valid bus/day Pre-Trip Inspection before Start Run is unlocked for a planned run
- The driver workspace page can correct the same-day invalid Pre-Trip record inline before Start Run is unlocked again
- The driver workspace currently hides checklist editing and submits stored checklist fields with safe defaults for future compatibility
- The driver workspace page requires Post-Trip Phase 2 before End Run is unlocked for an active run

Important runtime meaning:

- `POST /runs/start` starts an existing prepared run only
- it does not create stops
- it does not create students
- it does not create `StudentRunAssignment` rows

## API Highlights

### Pre-Trip Inspection
- `POST /pretrips/`
- `GET /pretrips/`
- `GET /pretrips/{pretrip_id}`
- `GET /pretrips/bus/{bus_id}/today`
- `PUT /pretrips/{pretrip_id}/correct`

### Post-Trip Inspection
- `POST /runs/{run_id}/posttrip/phase1`
- `POST /runs/{run_id}/posttrip/phase2`
- `GET /runs/{run_id}/posttrip`

### Route Bus Control
- `POST /routes/{route_id}/assign_bus/{bus_id}`
- `POST /routes/{route_id}/set_primary_bus/{bus_id}`
- `POST /routes/{route_id}/set_active_bus/{bus_id}`
- `POST /routes/{route_id}/restore_primary_bus`
- `DELETE /routes/{route_id}/unassign_bus`

### Run Creation And Start
- `POST /runs/`
- `POST /routes/{route_id}/runs`
- `POST /runs/start`

## Data Model Summary
- `Bus`
  Standalone bus record stored with internal `unit_number` and exposed to users as `bus_number`
- `Route`
  Planning container with compatibility `bus_id`, plus `primary_bus_id`, `active_bus_id`, and `clearance_note`
- `Run`
  Planned schedule fields `scheduled_start_time` and `scheduled_end_time`, plus actual runtime `start_time` and `end_time`
- `PreTripInspection`
  Bus/day inspection header with checklist history, correction metadata, and `original_payload`
- `PreTripDefect`
  Nested defect rows under one Pre-Trip Inspection
- `PostTripInspection`
  Per-run Post-Trip Inspection record with Phase 1 / Phase 2 state, activity fields, GPS heartbeat fields, and decision-layer support
- `DispatchAlert`
  Persistent backend alert record for Pre-Trip Inspection and Post-Trip Inspection conditions

## Constraints / Rules
- One Pre-Trip Inspection is allowed per bus per day
- Pre-Trip Inspection is bus-level, not run-level and not driver-level
- Post-Trip Inspection is per run
- The route's active bus is authoritative for run-start validation
- `POST /runs/end` and `POST /runs/end_by_driver` require Post-Trip Inspection Phase 2
- `POST /runs/{run_id}/complete` does not currently enforce Post-Trip Inspection Phase 2
- Planned schedule fields are not the same as actual runtime `start_time` and `end_time`
- No scheduler-based automation is documented as implemented for Pre-Trip Inspection or Post-Trip Inspection monitoring

## Structure Snapshot
- `app.py`
  FastAPI bootstrap, middleware, lifespan DB setup, and router registration
- `backend/models/`
  SQLAlchemy models including bus, route, run, Pre-Trip Inspection, Post-Trip Inspection, and dispatch alerts
- `backend/routers/`
  FastAPI routers for buses, routes, runs, Pre-Trip Inspection, Post-Trip Inspection, attendance, reports, and HTML pages
- `backend/schemas/`
  Pydantic request and response contracts
- `backend/utils/`
  Shared helpers including Pre-Trip Inspection alerts, Post-Trip Inspection alerts, Post-Trip Inspection status evaluation, and runtime assignment helpers
- `backend/templates/`
  Server-rendered UI templates
- `tests/`
  Automated API and behavior coverage

## Running The Project
Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
uvicorn app:app --reload
```

Run the tests:

```bash
pytest -q
```
