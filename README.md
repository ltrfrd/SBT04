# SBT

## Project Overview
SBT is a school bus operations backend built on FastAPI, SQLAlchemy, Alembic, and Jinja templates.

The current implemented system includes:

- route and run management
- flexible runtime stop execution
- pre-trip safety enforcement
- route bus control
- dispatch alerting

## Core Features

### Flexible Run Execution
- The existing runtime stop model remains flexible
- `POST /runs/{run_id}/arrive_stop` updates the actual runtime location
- `POST /runs/{run_id}/next_stop` remains a compatibility helper
- pickup and dropoff actions still depend on the current actual stop

### Pre-Trip Inspection System
- One pre-trip is allowed per bus per day
- Models: `PreTripInspection`, `PreTripDefect`
- User-facing pre-trip input includes:
  - `bus_number`
  - `license_plate`
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
- `no_defects` and defect rows are mutually exclusive
- Corrections overwrite the final values
- Corrections preserve `original_payload`

### Route Bus Management
- `Route.bus_id` remains the compatibility-facing active bus pointer
- `Route.primary_bus_id` stores the default/base bus
- `Route.active_bus_id` stores the current operational bus
- `Route.clearance_note` stores the optional restore note
- Only one active bus exists at a time because `active_bus_id` is a single FK field
- `assign_bus` sets the active bus and seeds the primary bus when it is empty
- The active bus is authoritative for run-start validation
- `restore_primary_bus` switches the active bus back to the primary bus

### Run Scheduling
- Planned fields:
  - `scheduled_start_time`
  - `scheduled_end_time`
- Actual runtime fields remain:
  - `start_time`
  - `end_time`
- Both run creation paths require planned schedule fields:
  - `POST /runs/`
  - `POST /routes/{route_id}/runs`

### Run Start Safety Enforcement
- `POST /runs/start` blocks when:
  - no pre-trip exists for the route's active bus for today
  - `fit_for_duty = no`
  - any pre-trip defect has severity `major`
- `POST /runs/start` allows start when:
  - today's pre-trip exists for the active bus
  - `fit_for_duty = yes`
  - defects are none or minor only

### Dispatch Alerts
- Model: `DispatchAlert`
- Utility: `backend/utils/pretrip_alerts.py`
- Alerts are triggered for:
  - major defect
  - `fit_for_duty = no`
  - missing pre-trip near scheduled run start
- Duplicate unresolved alerts are deduped
- Open alerts are resolved when the triggering condition clears

## Workflow
The implemented flow is:

1. Create and manage buses, routes, runs, stops, and students.
2. Assign or switch the route's active bus.
3. Driver submits a pre-trip using `bus_number` and `license_plate`.
4. Dispatch may correct the pre-trip if needed.
5. Create the run with `scheduled_start_time` and `scheduled_end_time`.
6. Start the run.
7. The system blocks unsafe starts if pre-trip rules fail.
8. The run continues with the existing flexible runtime stop behavior.

Important runtime meaning:

- `POST /runs/start` starts an existing prepared run only
- the run must already have stops and runtime student assignments
- `POST /runs/start` does not create stops
- `POST /runs/start` does not create students
- `POST /runs/start` does not create `StudentRunAssignment` rows

## API Highlights

### Pre-Trips
- `POST /pretrips/`
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
  Planning container with compatibility `bus_id`, `primary_bus_id`, `active_bus_id`, and `clearance_note`
- `Run`
  Planned schedule fields `scheduled_start_time` and `scheduled_end_time`, plus actual runtime `start_time` and `end_time`
- `PreTripInspection`
  Bus/day inspection header with correction metadata and `original_payload`
- `PreTripDefect`
  Nested defect rows under one inspection
- `DispatchAlert`
  Persistent backend alert record for pre-trip enforcement conditions

## Naming Notes
- Users see `bus_number`
- The internal database column remains `Bus.unit_number`
- Internal relationships and route compatibility fields still use `bus_id`
- `unit_number` is not the user-facing API field name
- `bus_id` is not a driver-entered pre-trip input field

## Constraints / Rules
- One pre-trip is allowed per bus per day
- The route's active bus is authoritative for run-start validation
- Planned schedule fields are not the same as actual runtime `start_time` and `end_time`
- Early run start is still allowed when safety checks pass
- No WebSocket feature is currently documented as part of the implemented system

## Structure Snapshot
- `app.py`
  FastAPI bootstrap, middleware, router registration, and lifespan DB setup
- `backend/models/`
  SQLAlchemy models including bus, route, run, pretrip, and dispatch alerts
- `backend/routers/`
  FastAPI routers for buses, routes, runs, pretrips, attendance, and HTML pages
- `backend/schemas/`
  Pydantic request and response contracts
- `backend/utils/`
  Shared helpers including pre-trip alert logic
- `backend/templates/`
  Server-rendered UI templates
- `tests/`
  Automated API and behavior protection

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
