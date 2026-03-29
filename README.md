SBT03 - School Bus Transport Backend
====================================

FROZEN REQUIREMENTS
-------------------
Functional requirements are frozen.

- No endpoint redesign
- No behavior changes unless explicitly approved
- No schema or DB changes unless explicitly required
- Fixes, cleanup, documentation, and alignment must preserve the working system

This rule is intentional and overrides speculative cleanup.


LAYERED RENAME: REPORT -> ATTENDANCE
-----------------------------------
The rename from `report` to `attendance` is intentional and is being done in layers.

- `backend/routers/attendance.py` is the active attendance/reporting router
- `/reports/...` compatibility paths remain intentional and must stay documented
- `backend/routers/report.py` is a compatibility bridge during the transition
- `backend/utils/report_generator.py` is a compatibility bridge during the transition
- Legacy `report` naming may still appear where compatibility is required

This is not a bug. It is the current compatibility strategy for the working system.


What SBT03 Does
---------------
SBT03 is a FastAPI-based school bus operations system. It manages setup, runtime bus execution, attendance computation, school review flows, and reporting-compatible outputs from one integrated backend.

The repo currently includes:

- FastAPI backend
- SQLite development database
- SQLAlchemy ORM models
- Alembic migration support
- Jinja template views
- pytest test suite


Core Operational Model
----------------------
Runs are the core operational unit.

- A route provides the planning context
- A run is the actual operational instance
- Stops belong to runs
- runtime student membership belongs to runs through `StudentRunAssignment`
- run events record live activity such as arrivals, pickups, dropoffs, and no-shows

Runtime truth is based on live run data, not on legacy static assumptions.


Most Important Business Rules
-----------------------------
`StudentRunAssignment` is the runtime source of truth.

- It defines which students are assigned to a run
- It links each student to the stop used for that run
- Attendance, running-board views, and nested run details build from it

Driver ownership is route-based, not stored directly on `Route`.

- `RouteDriverAssignment` is the ownership model
- A route may exist before a driver is assigned
- planned runs may exist before a driver is assigned
- driver resolution matters when a run is started

Run lifecycle is operationally significant.

- planned run = `start_time is NULL` and `end_time is NULL`
- active run = `start_time is NOT NULL` and `end_time is NULL`
- completed run = `end_time is NOT NULL`
- only one active run per driver is allowed at a time

Attendance is computed, not stored as a single source table.

- It is derived from runtime assignments
- It uses run events
- It uses planned bus absences
- It supports school-facing confirmation and review

School confirmation is scoped per school and per run.

- Multiple schools may be tied to a route
- The same route or run context may involve more than one school
- Confirmation state is stored separately for each school/run pair


Main Workflow
-------------
1. Setup

- Create drivers, schools, students, routes, and supporting records
- Associate one or more schools to routes
- Manage route-driver ownership through `RouteDriverAssignment`

2. Assign

- Create or start runs for a route
- Assign students to the active runtime context through `StudentRunAssignment`

3. Operate the run

- Start the run
- Progress through stops
- Record arrivals, pickups, dropoffs, and completion

4. Compute attendance

- Combine runtime assignments, events, and planned absences
- Produce run, route, school, date, and driver-facing attendance outputs

5. School confirmation and reporting

- Review school-specific attendance views
- Apply school-side status updates where allowed
- Confirm attendance per school and per run
- Preserve `/reports/...` compatibility during the layered rename


Key Modules
-----------
`app.py`

- Integration center for the backend
- Registers routers
- wires templates
- exposes route-first driver and attendance views

`database.py`

- SQLAlchemy engine, session, declarative base, and `get_db`

`backend/models/`

- Data layer for drivers, schools, students, routes, runs, stops, events, assignments, absences, and confirmations

`backend/models/associations.py`

- Includes `RouteDriverAssignment`
- Includes `StudentRunAssignment`

`backend/routers/run.py`

- Core run lifecycle and operational endpoints

`backend/routers/attendance.py`

- Active attendance/reporting router
- Keeps `/reports/...` compatibility paths stable during the layered rename

`backend/routers/report.py`

- Compatibility bridge for legacy report naming

`backend/utils/attendance_generator.py`

- Core attendance business-logic file
- Builds the main attendance payloads used by routes and templates

`backend/utils/report_generator.py`

- Compatibility bridge during the layered rename

`backend/templates/`

- Jinja templates for driver, route, school, and summary views

`tests/`

- pytest coverage for API behavior, stop sequencing, run progress, attendance integration, running board logic, and assignment flows


Current API and UI Direction
----------------------------
The active workflow is route-first and run-first.

- routes are selected first
- runs are inspected within route context
- stops are inspected within run context
- students are inspected through runtime assignments

The backend supports both API responses and server-rendered Jinja views from the same operational model.


Attendance and Compatibility Notes
----------------------------------
Attendance naming is now the primary business naming, but compatibility remains part of the current working system.

- `attendance.py` owns active attendance/reporting behavior
- `/reports/...` paths remain intentionally documented and supported
- template and utility layers may still contain legacy report-oriented names where compatibility matters

This layered migration is part of the current architecture as it exists today.


Development Notes
-----------------
- Use Alembic for schema history already present in the repo
- Use pytest to verify behavior
- Keep documentation aligned with the working codebase
- Do not document speculative future architecture


Repository Snapshot
-------------------
- Active project: `SBT03`
- Backend framework: FastAPI
- Dev database: SQLite
- ORM: SQLAlchemy
- Migrations: Alembic
- Templates: Jinja
- Tests: pytest
- Core runtime truth: `StudentRunAssignment`
- Driver ownership model: `RouteDriverAssignment`
- Active attendance router: `backend/routers/attendance.py`
- Compatibility bridges: `backend/routers/report.py`, `backend/utils/report_generator.py`
- Integration center: `app.py`
- Core attendance business logic: `backend/utils/attendance_generator.py`
