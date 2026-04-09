# SBT

## Project Overview
SBT is a school bus operations backend built with FastAPI, SQLAlchemy, Alembic, and Jinja templates.

The current implementation includes:

- route, run, stop, and student management
- planned run scheduling with required `scheduled_start_time` and `scheduled_end_time`
- flexible runtime stop execution
- bus-level pre-trip inspections
- run-start pre-trip enforcement
- dispatch alert persistence for pre-trip conditions
- route primary bus and active bus control

## Core Features

### Flexible Run Execution
- Runtime stop handling remains flexible
- `POST /runs/{run_id}/arrive_stop` updates the actual runtime location
- `POST /runs/{run_id}/next_stop` remains a compatibility helper
- pickup and dropoff actions still depend on the current actual stop

### Pre-Trip Inspection
- One pre-trip is allowed per bus per day
- The database links pre-trips by `bus_id`
- The current API remains backward-compatible with user-facing `bus_number` and `license_plate`
- Pretrip create/correct accepts `bus_id` (preferred) or `bus_number` (legacy compatibility). At least one is required.
- Pre-trip input supports:
  - `driver_name`
  - `inspection_date`
  - `inspection_time`
  - `odometer`
  - `inspection_place`
  - `use_type` (`school_bus` or `charter`)
  - `fit_for_duty` (`yes` or `no`)
  - `no_defects`
  - `defects`
  - `signature`
- `no_defects = true` requires an empty defect list
- `no_defects = false` requires at least one defect row
- Defects are stored as nested rows with severity `minor` or `major`
- Pre-trips support create, read, list, and correction flows
- Corrections preserve `original_payload`

### Run Start Enforcement
- `POST /runs/start` validates the route's active bus
- Run start is blocked when:
  - no pre-trip exists for the active bus for today
  - `fit_for_duty = no`
  - any defect on today's pre-trip has severity `major`
- Run start is allowed when:
  - today's pre-trip exists for the active bus
  - `fit_for_duty = yes`
  - defects are empty or minor-only
- Early run start is not blocked by time-of-day rules in the start endpoint itself
- `POST /runs/start` still requires the run to already have stops and runtime student assignments

### Route Bus Control
- `Route.bus_id` remains a compatibility-facing bus pointer
- `Route.primary_bus_id` stores the default/base bus
- `Route.active_bus_id` stores the current operational bus
- `Route.clearance_note` stores an optional note when restoring the primary bus
- `assign_bus` sets the active bus and seeds the primary bus when the route has no primary bus yet
- `set_primary_bus` changes the default/base bus without forcing an active replacement when one already exists
- `set_active_bus` switches the operational bus while preserving the route's primary bus
- `restore_primary_bus` switches the active bus back to the primary bus
- Downstream run-start pre-trip checks use the route's active bus

### Dispatch Alerts
- Alert records are stored in `DispatchAlert`
- `backend/utils/pretrip_alerts.py` handles pre-trip alert creation, dedupe, and resolution
- Pre-trip create/correct flows sync alerts for:
  - major defect reported on pre-trip
  - `fit_for_duty = no`
- Missing-pretrip alerts are also supported through the existing run-start side effect
- The repo includes utility support for the 15-minute missing-pretrip window
- The repo does not currently implement a separate autonomous scheduler or background polling loop for that alert path

## Workflow Summary
The current backend flow is:

1. Create buses, routes, runs, stops, and students.
2. Assign the route's primary bus and active bus as needed.
3. Create a pre-trip for the active bus for today.
4. Correct the pre-trip later if dispatch needs to overwrite the submitted values.
5. Create a planned run with `scheduled_start_time` and `scheduled_end_time`.
6. Start the prepared run.
7. The system blocks the start if the active bus has no valid pre-trip for today, if the pre-trip marks `fit_for_duty = no`, or if it contains a major defect.
8. Runtime stop progression continues through the existing flexible stop workflow.

Important runtime meaning:

- `POST /runs/start` starts an existing prepared run only
- it does not create stops
- it does not create students
- it does not create `StudentRunAssignment` rows

## API Highlights

### Pre-Trips
- `POST /pretrips/`
- `GET /pretrips/`
- `GET /pretrips/{id}`
- `GET /pretrips/bus/{bus_id}`
- `GET /pretrips/bus/{bus_id}/today`
- `PUT /pretrips/{id}/correct`

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
  Bus/day inspection header with correction metadata and `original_payload`
- `PreTripDefect`
  Nested defect rows under one inspection
- `DispatchAlert`
  Persistent backend alert record for pre-trip-related enforcement conditions

## Constraints / Rules
- One pre-trip is allowed per bus per day
- Pre-trips are bus-level, not run-level and not driver-level
- The route's active bus is authoritative for run-start validation
- Planned schedule fields are not the same as actual runtime `start_time` and `end_time`
- No separate scheduler-based automation is documented as implemented for the 15-minute missing-pretrip check

## Structure Snapshot
- `app.py`
  FastAPI bootstrap, middleware, lifespan DB setup, and router registration
- `backend/models/`
  SQLAlchemy models including bus, route, run, pretrip, and dispatch alerts
- `backend/routers/`
  FastAPI routers for buses, routes, runs, pretrips, attendance, reports, and HTML pages
- `backend/schemas/`
  Pydantic request and response contracts
- `backend/utils/`
  Shared helpers including pre-trip alert logic and runtime assignment helpers
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
