# SBT04 — School Bus Transport and Operations System

## 1. Project Overview
SBT04 is the current workflow-focused evolution of this repository. It keeps the same FastAPI, SQLAlchemy, Jinja template, dispatch, attendance, and reporting backend that already exists in the codebase.

SBT04 is not a backend rewrite. The core engine stays in place. The current work is focused on improving how operators configure and move through the system so setup feels clearer, safer, and more practical without breaking stable behavior.

This repo should be understood as one connected system with three cooperating concerns:

- configuration and setup
- dispatch and run execution
- attendance and reporting

## 2. What Changed In SBT04
The current SBT04 framing is workflow-focused, not engine-focused.

SBT04 shifts the visible operator experience toward:

- route-first setup
- run creation inside the route
- stop creation inside the run
- stop-centric student management
- hiding assignment complexity from the normal operator flow

That change is already reflected in the current backend surface. The run router now includes stop-context student creation endpoints:

- `POST /runs/{run_id}/stops/{stop_id}/students`
- `POST /runs/{run_id}/stops/{stop_id}/students/bulk`

The route-first workflow also includes context creation endpoints for normal operator setup:

- `POST /routes/{route_id}/runs`
- `POST /runs/{run_id}/stops`

This direction is already implemented in the current backend surface and continues to be refined.

Those endpoints create `Student` records and create `StudentRunAssignment` internally so operators do not have to manually manage assignment rows.

## 3. System Workflow
The intended operator workflow in SBT04 is:

Route  
 -> Run  
   -> Stop  
     -> Students

In practical terms, the operator flow is:

1. Create route
2. Open route
3. Create runs inside route
4. Open run
5. Create stops inside run
6. Open stop
7. Add students inside stop
8. Assign schools to route
9. Assign drivers to route

The system should feel route-first, run-first, and stop-centric for student setup.

## 4. Internal Vs Operator Model
SBT04 depends on a clear separation between the operator-facing workflow and the internal runtime engine.

### Operator Layer (Visible)
These are the concepts the system should expose most clearly to operators:

- Routes
- Runs
- Stops
- Students
- Schools by `school_id` and `school_name`
- Route-school assignment
- Route-driver assignment

### Internal Layer (Do Not Expose)
These are still real and important in the backend, but they are not the preferred operator-facing planning objects:

- `StudentRunAssignment`
- pickup and dropoff tracking
- onboard logic
- attendance engine
- running board source data
- runtime state transitions

Warning: operators must not interact with `StudentRunAssignment` directly as the normal workflow. It remains in the codebase because dispatch, pickup, dropoff, onboard status, running board views, and attendance/report generation still depend on it.

The explicit assignment router at `backend/routers/student_run_assignment.py` is still exposed for compatibility and advanced/internal use, but it is no longer the intended operator workflow surface.

⚠️ Direct use of StudentRunAssignment endpoints should be limited to internal logic or advanced/debug use only.


## 5. Frozen Requirements
The following requirements are fixed for SBT04:

- `StudentRunAssignment` stays
- runtime logic stays
- attendance stays
- reports stay
- route-driver assignment stays
- route-school assignment stays
- `school_code` is removed from the working model
- stop types support `PICKUP`, `DROPOFF`, `SCHOOL_ARRIVE`, and `SCHOOL_DEPART`
- backward compatibility is required
- no unnecessary architecture changes
- prefer additive endpoints over destructive redesign

This project is improving workflow, not replacing the existing operating model.

## 6. Layered Architecture
SBT04 is easiest to understand as three layers that share the same application runtime and data model.

### Dispatch Layer (PROTECTED)
The dispatch layer is stable and must not break. It covers:

- run lifecycle
- current stop tracking
- stop progress
- pickup and dropoff actions
- onboard state
- occupancy and running board views
- live run state
- GPS and driver workspace behavior

This layer is centered mainly in:

- `backend/routers/run.py`
- `backend/models/run.py`
- `backend/models/run_event.py`
- `backend/utils/gps_tools.py`
- `backend/utils/route_driver_assignment.py`
- `backend/templates/driver_run.html`

### Attendance Layer (PROTECTED)
The attendance and reporting layer is also stable and must not break. It covers:

- reports
- confirmations
- payroll-style summaries
- date summaries
- route summaries
- school summaries
- absence-aware reporting

This layer is centered mainly in:

- `backend/routers/attendance.py`
- `backend/routers/report.py`
- `backend/models/school_attendance_verification.py`
- `backend/models/student_bus_absence.py`
- `backend/utils/attendance_generator.py`
- `backend/utils/report_generator.py`
- `backend/templates/route_report.html`
- `backend/templates/summary_report.html`
- `backend/templates/school_attendance_routes.html`
- `backend/templates/school_attendance_runs.html`
- `backend/templates/school_mobile_report.html`

`backend/routers/report.py` is a compatibility layer that re-exports the attendance router.

### Configuration Layer (ACTIVE DEVELOPMENT)
The active development focus is configuration and workflow. This covers:

- route setup
- run setup
- stop setup
- student setup
- school assignment to routes
- driver assignment to routes
- stop-context student creation
- bulk stop-context student creation

This layer is centered mainly in:

- `backend/routers/route.py`
- `backend/routers/run.py`
- `backend/routers/stop.py`
- `backend/routers/student.py`
- `backend/models/route.py`
- `backend/models/stop.py`
- `backend/models/student.py`

## 7. Core Data Model
The current codebase follows a practical hierarchy that already matches the intended workflow direction.

### Route
`Route` is the planning container. It holds route identity and the main planning relationships:

- route number
- unit number
- schools assigned to the route
- driver assignments for the route
- runs belonging to the route

### Run
`Run` belongs to a route and acts as the operational unit under that route. It carries:

- route linkage
- optional driver linkage
- run type
- current stop tracking
- completion state
- ordered stops
- runtime student assignments
- run events

### Stop
`Stop` belongs to a run, not directly to a route. It includes:

- `run_id`
- ordered `sequence`
- `type`
- name and address
- planned time
- latitude and longitude

### Student
`Student` is the rider record. In the current model:

- `school_id` is required
- `route_id` is optional
- `stop_id` is optional

The route and stop pointers still exist, but runtime rider-to-run execution is not driven from those fields alone.

### StudentRunAssignment
`StudentRunAssignment` remains the internal engine. It links:

- student
- run
- stop

It also stores runtime state used by the active system:

- actual pickup stop
- actual dropoff stop
- picked up
- dropped off
- onboard state
- school status

This model remains necessary because the dispatch and attendance layers depend on it. It is internal from the workflow point of view, not removed from the architecture.

## 8. Backend Modules
The following modules actually exist in the repo and are part of the current system.

### Models
- `backend/models/route.py`: route planning container
- `backend/models/run.py`: operational run
- `backend/models/stop.py`: ordered stop within a run
- `backend/models/student.py`: rider record
- `backend/models/associations.py`: route-school link table, route-driver assignment, `StudentRunAssignment`
- `backend/models/run_event.py`: run event timeline
- `backend/models/dispatch.py`: payroll persistence
- `backend/models/driver.py`: driver record
- `backend/models/school.py`: school record
- `backend/models/school_attendance_verification.py`: school confirmation state
- `backend/models/student_bus_absence.py`: planned bus absence

### Routers
- `backend/routers/route.py`: route CRUD, route detail, school linkage, route-driver assignment
- `backend/routers/run.py`: run CRUD, lifecycle, state, running board, summary, replay, timeline, stop-context student creation, bulk stop-context student creation
- `backend/routers/stop.py`: stop CRUD, reorder, normalize, validate
- `backend/routers/student.py`: student CRUD and route/school filtered lookup
- `backend/routers/student_run_assignment.py`: explicit assignment CRUD, still exposed for compatibility and advanced/internal use
- `backend/routers/attendance.py`: `/reports` endpoints for route, run, school, confirmations, payroll, summaries, and absence-aware reporting
- `backend/routers/report.py`: compatibility re-export of the attendance router
- `backend/routers/dispatch.py`: dispatch and payroll operations
- `backend/routers/driver.py`: driver CRUD and driver-route lookup
- `backend/routers/school.py`: school CRUD and route assignment
- `backend/routers/student_bus_absence.py`: planned no-ride endpoints

### Schemas
- `backend/schemas/route.py`: route create, summary, detail, and nested route-run-stop-student payloads
- `backend/schemas/run.py`: run create, detail, state, running board, summary, replay, timeline, pickup, and dropoff payloads
- `backend/schemas/stop.py`: stop create, update, reorder, and output schemas
- `backend/schemas/student.py`: student CRUD plus stop-context single and bulk student creation schemas
- `backend/schemas/student_run_assignment.py`: explicit runtime assignment schemas
- `backend/schemas/dispatch.py`, `driver.py`, `school.py`, `student_bus_absence.py`: supporting API contracts for their modules

### Utils
- `backend/utils/attendance_generator.py`: attendance and report aggregation
- `backend/utils/report_generator.py`: compatibility re-export of attendance logic
- `backend/utils/gps_tools.py`: GPS and run progress helpers
- `backend/utils/route_driver_assignment.py`: one-active-driver-per-route helpers
- `backend/utils/student_bus_absence.py`: planned absence filtering
- `backend/utils/auth.py`: session auth helpers
- `backend/utils/db_errors.py`: database error translation helpers

## 9. Frontend Status
The repo contains a separate `frontend/` folder with a React and Vite scaffold. It is real, but it is not the main operator UI today.

The currently active UI surface is still primarily server-rendered through FastAPI and Jinja templates in `backend/templates/`, especially:

- `backend/templates/driver_run.html`
- `backend/templates/route_report.html`
- `backend/templates/summary_report.html`
- `backend/templates/school_attendance_routes.html`
- `backend/templates/school_attendance_runs.html`
- `backend/templates/school_mobile_report.html`

The React frontend currently looks like a scaffold/example path rather than the authoritative live workflow interface.

## 10. Testing
The `tests/` folder protects runtime behavior and API stability while workflow improvements are made.

Current test coverage includes:

- broad API behavior
- route, run, stop, student, and assignment surface expectations
- running board behavior
- run progress and next-stop behavior
- stop ordering and edge cases
- bus absence behavior
- school attendance and confirmation behavior
- stop-context student creation and bulk student creation

Testing matters in SBT04 because the project is intentionally not a rewrite. Workflow improvements must preserve stable dispatch logic, stable attendance/report behavior, and backward-compatible API behavior wherever practical.

## 11. Development Rules
Development in SBT04 should follow a conservative workflow-first approach:

- one step at a time
- no unrelated refactors
- do not break working features
- keep backward compatibility
- prefer additive endpoints over destructive redesign
- keep `StudentRunAssignment` internal to operator thinking
- test after every change
- make documentation match the actual code

## 12. Getting Started
This repo is currently set up as a FastAPI application with SQLAlchemy, Alembic, Jinja templates, and a separate Vite frontend folder.

Install Python dependencies from the repo root:

```bash
pip install -r requirements.txt
```

Run the FastAPI app from the repo root:

```bash
uvicorn app:app --reload
```

Run the test suite from the repo root:

```bash
pytest -q
```

If you inspect the separate frontend scaffold, the folder also contains standard Vite scripts, but the template layer is still the main UI in the current repo.

## 13. Roadmap
The near-term focus should stay narrow and practical:

- stop-level student management
- bulk student creation
- workflow simplification

In this repo, backend support for stop-context student creation and bulk add exists in the run router and continues to be refined. The remaining emphasis is workflow simplification and improved operator-facing integration without changing the protected runtime and attendance layers.
