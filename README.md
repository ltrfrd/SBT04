# SBT

## Overview
SBT is a workflow-first school bus operations backend built on FastAPI, SQLAlchemy, Alembic, and Jinja templates. The repository is organized around a simple layered operator flow:

Route -> Run -> Stop -> Student

This is not a rewrite. The protected runtime and attendance engine stays in place while the setup flow becomes more explicit and context-driven.

## Preferred Workflow
The intended operator path is:

1. Create a route
2. Assign schools to the route
3. Assign a driver to the route
4. Assign a bus to the route
5. Create runs inside the route
6. Create stops inside the run
7. Add students from stop context

Preferred context-first endpoints:

- `POST /routes/{route_id}/runs`
- `POST /runs/{run_id}/stops`
- `POST /runs/{run_id}/stops/{stop_id}/students`
- `POST /runs/{run_id}/stops/{stop_id}/students/bulk`

These endpoints reduce repeated manual IDs in the normal workflow:

- route context creates runs
- run context creates stops
- stop context creates students in explicit stop context
- stop-context student creation creates the internal `StudentRunAssignment`

Core workflow rule:

- runtime assignment truth is explicit and stop-based
- no runtime assignment exists without stop context
- assignment creation is stop-context only through `POST /runs/{run_id}/stops/{stop_id}/students`
- `/runs/start` does not create students
- `/runs/start` does not create stops
- `/runs/start` does not auto-create `StudentRunAssignment` rows

## Runtime And Maintenance Flow
After the setup hierarchy exists, real usage should continue from route and run context:

1. Driver selects an assigned route
2. Driver reviews the route's prepared runs
3. Driver starts and operates the selected run through `/runs/start`
4. Runtime views read the already prepared stop and student structure from that run

Current `/runs/start` meaning:

- operational runtime endpoint only
- starts an existing prepared run by `run_id`
- prepared run required before start succeeds
- prepared run means stops already exist on the run
- prepared run means at least one runtime student assignment already exists on the run
- does not create students
- does not create stops
- does not create `StudentRunAssignment` rows

Maintenance and compatibility remain separate from the normal setup path:

- assignment creation is stop-context only through `POST /runs/{run_id}/stops/{stop_id}/students`
- contextual remove is stop-context only through `DELETE /runs/{run_id}/stops/{stop_id}/students/{student_id}` and removes the student from that run-stop planning context without deleting the student record
- `PUT /students/{student_id}/assignment` is an intentional maintenance endpoint for corrections and controlled moves
- `DELETE /students/{student_id}` is full student deletion from the system and is not the normal run-stop workflow remove action
- `StudentRunAssignment` acts as the runtime + planning bridge between the student record and the selected run/stop context
- `POST /student-run-assignments/` is blocked and returns guidance to use stop-context student creation
- `DELETE /student-run-assignments/{id}` is blocked and returns guidance to use the canonical stop-context delete endpoint
- `GET /student-run-assignments/{run_id}` and `GET /student-run-assignments/?student_id=...` remain compatibility read views
- `POST /runs/` is legacy compatibility
- `POST /stops/` is legacy compatibility
- `POST /students/` is secondary compatibility

## Current Backend Rules
The active SBT backend surface follows these rules:

- `school_code` is removed from the working model and API surface
- `school_id` remains the internal and visible school reference
- school `address` is optional
- `run_type` remains named `run_type` for compatibility
- run labels are normalized on write
- stop types support `PICKUP`, `DROPOFF`, `SCHOOL_ARRIVE`, and `SCHOOL_DEPART`
- school stops can store `stop.school_id`
- stop order is controlled by `sequence`
- route-driver assignment is route-level and explicit
- one active route-driver assignment is used for operational run start
- `StudentRunAssignment` is the explicit runtime mapping between student, run, and stop
- Bus is now a standalone entity with its own CRUD and detail surface
- `Route.bus_id` is an optional current bus assignment
- legacy route bus-like fields remain in place for compatibility:
  - `route.unit_number`
  - `route.capacity`
  - `route.operator`
- read surfaces can prefer assigned bus values and fall back to legacy route values when no bus is assigned

## Protected Engine
The internal runtime engine remains authoritative:

- `StudentRunAssignment` stays
- dispatch behavior stays
- attendance behavior stays
- reporting behavior stays
- compatibility endpoints stay where intentionally supported

Operators should not need to work directly with `StudentRunAssignment` during normal planning, but the compatibility router still exists for advanced or internal use.

## Main Backend Areas
Configuration and workflow:

- `backend/routers/route.py`
- `backend/routers/run.py`
- `backend/routers/stop.py`
- `backend/routers/student.py`

Application bootstrap and extracted UI/session layers:

- `app.py` is bootstrap-focused and now uses FastAPI lifespan for startup initialization
- DB table initialization runs inside lifespan instead of import-time startup side effects
- `app.py` keeps the `get_db` compatibility export used by tests
- `backend/routers/web_pages.py` contains the server-rendered page routes
- `backend/routers/auth.py` contains the session/auth endpoints
- `backend/routers/ws.py` contains the GPS WebSocket endpoint
- `backend/utils/driver_workspace.py` contains the route-first driver workspace helpers

Bus rollout and compatibility layers:

- `backend/models/bus.py`
- `backend/schemas/bus.py`
- `backend/routers/bus.py`
- routes can optionally point to a current bus through `Route.bus_id`
- route-first read surfaces now expose assigned bus values when present
- route-first read surfaces still fall back to `route.unit_number`, `route.capacity`, and `route.operator` when no bus is assigned

Protected runtime and reporting:

- `backend/routers/run.py`
- `backend/routers/attendance.py`
- `backend/routers/report.py`
- `backend/utils/attendance_generator.py`
- `backend/utils/report_generator.py`

Explicit runtime mapping and compatibility:

- `backend/models/associations.py` defines `RouteDriverAssignment` and `StudentRunAssignment`
- `backend/routers/student_run_assignment.py` exposes read-only assignment lookup endpoints while direct create/delete mutation paths are blocked
- `backend/routers/student.py` keeps the direct student create compatibility surface and the intentional maintenance move endpoint, but the preferred assignment flow is stop-context student creation

School mobile attendance flow:

- `/reports/school/{school_id}/mobile` renders `school_attendance_routes.html`
- `/reports/school/{school_id}/mobile/route/{route_id}` renders `school_attendance_runs.html`
- `/reports/school/{school_id}/mobile/run/{run_id}` renders `school_mobile_report.html`
- attendance template rendering uses the current `TemplateResponse(request, template_name, context)` signature

## Structure Snapshot
- `app.py` bootstrap and lifespan setup
- `backend/models/` SQLAlchemy models including bus, route, run, stop, student, and associations
- `backend/routers/` API and HTML routers
- `backend/schemas/` request/response contracts
- `backend/templates/` server-rendered UI templates
- `backend/utils/` shared workflow, attendance, GPS, and auth helpers
- `tests/` API surface and behavior protection

Core models:

- `backend/models/route.py`
- `backend/models/run.py`
- `backend/models/stop.py`
- `backend/models/student.py`
- `backend/models/associations.py`

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

## Notes
- The main live UI is still primarily template-driven through `backend/templates/`.
- The `frontend/` folder exists as a separate React/Vite scaffold.
- Workflow improvements should remain additive and backward compatible.
- Tests are green against the current behavior, so docs should be read as describing the live repo rather than an intermediate migration plan.
