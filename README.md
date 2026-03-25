SBT03 — Project Study Structure 
================================

MIGRATION STATUS (SBT03)
-----------------------
This version is the active development state of the project.

Key change:
- Driver is no longer assigned directly to Route
- Driver ↔ Route is now handled via RouteDriverAssignment

Important rules:
- Requirements are frozen
- Development is done in layers (backend → UI → integration)
- Changes must remain minimal and non-breaking
- Attendance remains strictly run-based
- /reports/... compatibility must NOT break

This migration is being applied without breaking existing attendance and reporting behavior.

1) PROJECT IDENTITY
-------------------
SBT03 is a FastAPI-based school bus operations backend with a small server-rendered frontend.
The project is organized around operational transport entities such as drivers, schools, students,
routes, stops, runs, attendance, dispatch/payroll, and planned student absences.

The codebase is currently in an architectural transition:
- older "report" naming is being replaced by "attendance"
- some files still carry older SBT01/BST/BST01 naming in comments or titles
- compatibility files are kept so older imports continue working

Main technical stack:
- FastAPI for API and server rendering
- SQLAlchemy ORM for database models
- Jinja2 templates for HTML pages
- SQLite by default in development
- Alembic present for migrations
- pytest for testing

Important central files proving this structure:
- app.py initializes the FastAPI app and wires the system together
- database.py defines engine, sessions, and Base
- backend/routers/attendance.py is the active attendance/reporting router
- backend/utils/attendance_generator.py contains the main attendance-building logic
- backend/models/__init__.py shows the core model set exported by the backend

2) HIGH-LEVEL ARCHITECTURE
--------------------------
The project follows a layered pattern, even though some files still blur boundaries.

A. Entry / Infrastructure Layer
   These files boot the app, load settings, connect the database, and register routers.

B. Data Layer (models/)
   SQLAlchemy models define the business entities and relationships:
   driver, school, student, route, stop, run, runtime assignments, run events,
   dispatch/payroll, student planned absences, and school attendance confirmation.

C. API Layer (routers/)
   FastAPI routers expose CRUD and operational endpoints.
   This includes normal domain endpoints and specialized attendance/reporting endpoints.

D. Validation Layer (schemas/)
   Pydantic schemas define request and response shapes.

E. Business Logic Layer (utils/)
   Shared operational logic lives here, especially attendance calculation, auth helpers,
   GPS tools, DB error handling, and planned-absence helpers.

F. Presentation Layer (templates/)
   Jinja pages provide dashboard and school/driver report views.

G. Test Layer (tests/)
   Pytest files validate endpoint behavior, route/stop logic, run progression,
   and attendance/absence integration.

3) ROOT FILES
-------------
app.py
------
Role:
Main application entry point and runtime composition file.

What it represents:
This is the file that turns the codebase into a working FastAPI application.
It loads environment variables, creates the app object, configures middleware,
registers routers, mounts static files, sets up templates, defines websocket behavior,
renders HTML pages, and exposes login/logout and health endpoints. :contentReference[oaicite:0]{index=0}

Main responsibilities:
- loads .env values through dotenv
- creates FastAPI instance
- adds session middleware
- adds CORS middleware
- mounts /static
- configures Jinja templates
- registers routers:
  driver, school, student, route, stop, run, dispatch, attendance,
  student_run_assignment, and the absence router re-exported through attendance
- defines websocket GPS endpoint for live run tracking
- renders dashboard, route report, driver run, and summary report pages
- defines session-based login/logout
- exposes root status endpoint
- directly calls Base.metadata.create_all(bind=engine) at the bottom :contentReference[oaicite:1]{index=1}

Why it matters:
This file is the integration center. If someone wants to know how the project starts,
what endpoints are active, and how the frontend pages connect to backend logic,
this is the first file to read.

Key relation to other files:
- depends on database.py for DB engine/session/Base
- imports backend.models so ORM metadata is known
- imports routers from backend/routers
- uses backend.utils.gps_tools and backend.utils.attendance_generator
- renders templates in backend/templates

database.py
-----------
Role:
Database infrastructure file.

What it represents:
This is the SQLAlchemy foundation of the project.
It centralizes DB connection settings, creates the engine,
creates the session factory, defines the declarative Base,
and exposes get_db() for dependency injection in routes. :contentReference[oaicite:2]{index=2}

Main responsibilities:
- loads DATABASE_URL from environment
- falls back to sqlite:///sbt.db in project root
- configures SQLite check_same_thread=False
- enables SQLite foreign keys via PRAGMA
- defines SessionLocal
- defines Base
- defines get_db() generator dependency :contentReference[oaicite:3]{index=3}

Why it matters:
Every model, route, and business function that touches the DB depends on this file.

alembic.ini
-----------
Role:
Alembic migration config.

What it represents:
This file belongs to schema migration workflow.
It suggests the project intends to use migrations rather than relying only on create_all.

Current architectural note:
Because app.py also calls Base.metadata.create_all(), the project currently has two
schema-management ideas present at once: migration-based and auto-create-based. :contentReference[oaicite:4]{index=4}

requirements.txt
----------------
Role:
Dependency manifest.

What it represents:
Defines the Python packages needed to run the project.

README.md
---------
Role:
Project readme placeholder.

What it represents:
Currently empty, so the repo does not yet have an official human-oriented project overview. :contentReference[oaicite:5]{index=5}

structure.txt
-------------
Role:
Manual repository structure snapshot.

What it represents:
An older exported folder tree.
It is now outdated and includes things that should not usually be documented as project structure,
such as venv and __pycache__. It also reflects an older backend layout where report.py/report_generator.py
were more central than they are now. :contentReference[oaicite:6]{index=6}

4) ALEMBIC FOLDER
-----------------
alembic/env.py
--------------
Role:
Migration environment bootstrapping.

What it represents:
This file wires Alembic into the SQLAlchemy metadata so migrations can be generated or applied.

alembic/versions/
-----------------
Role:
Migration history folder.

What it represents:
Stores individual migration revisions over time.

5) BACKEND PACKAGE
------------------
backend/__init__.py
-------------------
Role:
Backend package initializer.

What it represents:
Marks backend as a Python package and allows imports like backend.models, backend.routers, backend.utils.

backend/config.py
-----------------
Role:
Small app settings holder.

What it represents:
A lightweight settings object used to centralize DEBUG and ENV values.
It is simple, but it establishes a pattern for environment-driven behavior. :contentReference[oaicite:7]{index=7}

Main responsibilities:
- DEBUG boolean
- ENV string
- creates a singleton settings object named settings :contentReference[oaicite:8]{index=8}

Why it matters:
This is where future environment-specific app behavior should grow.

backend/deps/
-------------
Role:
Shared dependency helpers.

What it represents:
A place for dependency-related utilities.
Even if not yet central in the main flow, its presence shows the project is moving toward cleaner dependency organization.

6) MODELS LAYER — backend/models/
---------------------------------
General purpose:
This folder defines the database shape of the application.
The models are the domain vocabulary of the project.

backend/models/__init__.py
--------------------------
Role:
Model export index.

What it represents:
This file tells us what the project considers its core DB entities.
It exports Driver, School, Student, Route, Stop, StopType, Run, Payroll,
RunEvent, route_schools, StudentRunAssignment, StudentBusAbsence,
StudentBusAbsenceSource, and SchoolAttendanceVerification. :contentReference[oaicite:9]{index=9}

Why it matters:
This file gives the clearest high-level picture of the whole domain model.

backend/models/driver.py
------------------------
Role:
Driver entity model.

What it likely represents:
The bus driver as an operational user/resource in the system.
It likely stores identity/contact data and links to runs or routes.

Project function:
Used by driver CRUD, login/session flow, dashboard counts, run ownership,
and route/attendance reporting. app.py queries Driver counts and driver-run views use it. :contentReference[oaicite:10]{index=10}

RouteDriverAssignment
---------------------
Stores driver ownership of a route.

Fields:
- route_id
- driver_id
- is_primary
- start_date
- end_date
- active

Used to resolve which driver is responsible for a route when creating runs.
Note:
Driver is no longer stored directly on Route and is resolved via assignments.

backend/models/school.py
------------------------
Role:
School entity model.

What it likely represents:
The school as an organization node in the transport system.

Project function:
Routes can serve schools, students belong to schools, school reports are grouped by school,
and attendance confirmation is stored per school and run. attendance.py validates school existence
and uses school membership on routes to authorize confirmation. :contentReference[oaicite:11]{index=11}

backend/models/student.py
-------------------------
Role:
Student entity model.

What it likely represents:
A transported student, likely linked to school, route, stop, and runtime assignments.

Project function:
Students are the center of attendance logic, absence logic, school-facing present/absent views,
and assignment-to-run logic. attendance.py and attendance_generator.py repeatedly use Student
to derive school attendance and absence data. :contentReference[oaicite:12]{index=12} :contentReference[oaicite:13]{index=13}

backend/models/route.py
-----------------------
Role:
Route entity model.

What it likely represents:
A bus route definition, including route number, unit number, and driver assignments
through RouteDriverAssignment.
linked schools, child runs, and route-owned logic.

Project function:
Attendance summaries can be route-based, school attendance is grouped by routes,
and runs belong to routes. app.py uses route.router and route report pages. :contentReference[oaicite:14]{index=14} :contentReference[oaicite:15]{index=15}

backend/models/stop.py
----------------------
Role:
Stop entity model.

What it likely represents:
Ordered pickup/dropoff points belonging to route runs.

Project function:
Stops matter for sequence, run progression, attendance per stop, and route report display.
The attendance generator builds stop_totals and route report output from stop sequencing. :contentReference[oaicite:16]{index=16}

backend/models/run.py
---------------------
Role:
Run entity model.

What it represents:
A single operational trip instance such as an AM or PM run.
This is the runtime backbone of the transportation workflow.

Project function:
- attendance is measured per run
- GPS websocket tracking is per run_id
- students are assigned to runs
- schools confirm attendance per run
- run events are attached to runs
- driver active-run page is driven by current run state :contentReference[oaicite:17]{index=17} :contentReference[oaicite:18]{index=18}

backend/models/run_event.py
---------------------------
Role:
Run event history model.

What it represents:
Operational event stream for each run.

Project function:
Attendance classification uses run events, especially STUDENT_NO_SHOW,
to turn runtime event history into school/dispatch-facing attendance states. :contentReference[oaicite:19]{index=19} :contentReference[oaicite:20]{index=20}

backend/models/dispatch.py
--------------------------
Role:
Dispatch/business-side models.

What it represents:
This file includes Payroll, and likely other dispatch/business records.

Project function:
Used by summary reports, payroll summaries, and driver work summaries.
app.py uses dispatch_model.Payroll in summary_report and attendance_generator.py
uses it in driver_summary and payroll_summary. :contentReference[oaicite:21]{index=21} :contentReference[oaicite:22]{index=22}

backend/models/associations.py
------------------------------
Role:
Association and runtime-link models.

What it represents:
Relationship tables plus runtime assignment objects.
The exported names confirm at least:
- route_schools
- StudentRunAssignment :contentReference[oaicite:23]{index=23}

Project function:
- route_schools links routes to schools
- StudentRunAssignment links students to specific runs and stops
- attendance logic uses these assignments as the runtime truth for who belongs on a run

This is one of the most important structural files because it bridges static planning
(routes/schools/students) with live operation (run assignments).

backend/models/student_bus_absence.py
-------------------------------------
Role:
Planned student no-ride model.

What it represents:
Stores a student's declared absence from bus service for a specific date and run type.

Project function:
This is not a runtime no-show.
It is a planned, known absence used to exclude or mark students before operational events happen.
attendance.py exposes absence endpoints, and attendance generation checks it repeatedly. :contentReference[oaicite:24]{index=24} :contentReference[oaicite:25]{index=25}

backend/models/school_attendance_verification.py
------------------------------------------------
Role:
School confirmation model.

What it represents:
Stores school-side confirmation that a school has reviewed/confirmed attendance
for a specific run.

Project function:
This enables separate confirmation per school/run pair, which is important because
one run can involve multiple schools and each school confirms independently.
attendance.py writes and reads this model during mobile school reporting and confirmation. :contentReference[oaicite:26]{index=26}

7) ROUTERS LAYER — backend/routers/
-----------------------------------
General purpose:
This is the API surface of the project.

backend/routers/__init__.py
---------------------------
Role:
Router export index.

What it represents:
This file centralizes router exports for use elsewhere.
It exports driver_router, school_router, student_router, route_router, stop_router,
run_router, dispatch_router, attendance_router, and student_run_assignment_router. :contentReference[oaicite:27]{index=27}

Why it matters:
This is the project’s router map.

backend/routers/driver.py
-------------------------
Role:
Driver API router.

What it likely represents:
CRUD and operational endpoints related to drivers.

How it fits:
Feeds dashboard counts, login/session use cases, driver pages, and possibly driver-route ownership.

backend/routers/school.py
-------------------------
Role:
School API router.

What it likely represents:
School CRUD and school-specific operations.

How it fits:
School attendance pages and confirmation logic rely on school records existing and linking to routes.

backend/routers/student.py
--------------------------
Role:
Student API router.

What it likely represents:
Student CRUD and student record maintenance.

How it fits:
Students are core to run assignments, absences, and school attendance output.

backend/routers/route.py
------------------------
Role:
Route API router.

What it likely represents:
Route creation/update and school assignment operations.

How it fits:
Routes are the bridge between planning and live runs.

backend/routers/stop.py
-----------------------
Role:
Stop API router.

What it likely represents:
Stop CRUD and stop ordering/sequence behavior.

How it fits:
Stop sequence is a major operational concept and is covered heavily by tests.

backend/routers/run.py
----------------------
Role:
Run API router.

What it likely represents:
Run lifecycle endpoints such as starting, progressing, or resolving runs.

How it fits:
Live run behavior, attendance generation, and GPS tracking depend on this layer.

backend/routers/dispatch.py
---------------------------
Role:
Dispatch/business router.

What it likely represents:
Payroll/business-facing operations.

How it fits:
Connected to summary reports and driver work summaries.

backend/routers/student_run_assignment.py
-----------------------------------------
Role:
Runtime student assignment router.

What it represents:
This router manages the link between students and actual runs.
It likely decides which students are considered part of a run at runtime.

Why it matters:
Attendance logic does not operate only on static student-route membership;
it operates on StudentRunAssignment, so this router is crucial to operational reality.

backend/routers/student_bus_absence.py
--------------------------------------
Role:
Planned absence router.

What it likely represents:
Endpoints for declaring or reading planned no-ride days.

Why it matters:
This is the planned-absence API that attendance re-exports under attendance ownership.

backend/routers/attendance.py
-----------------------------
Role:
Active attendance and reporting router.

What it represents:
This is currently the most important specialized router in the project.
It exposes attendance/reporting behavior under the prefix /reports while the codebase
transitions from “report” naming to “attendance.” :contentReference[oaicite:28]{index=28}

Main functions it provides:
- get_driver_attendance(driver_id)
- get_route_attendance(route_id)
- get_run_attendance(run_id)
- get_driver_work_summary(start, end)
- get_date_attendance(target_date)
- get_school_attendance(school_id)
- confirm_school_attendance(school_id, run_id)
- get_absences_by_date(target_date)
- get_absences_by_school(school_id)
- get_absences_by_run(run_id)
- get_school_attendance_by_date(school_id, target_date)
- get_school_mobile_attendance(school_id)
- update_school_status(payload) :contentReference[oaicite:29]{index=29}

What this router means architecturally:
It is the application layer for school-facing and dispatch-facing attendance views.
It combines:
- pure reporting
- school mobile page rendering
- school-side confirmation persistence
- school-side row updates
- absence visibility

Why it matters:
If a person wants to understand the live “attendance module” in SBT03,
this is the first backend file to study after app.py.

backend/routers/report.py
-------------------------
Role:
Legacy compatibility router.

What it represents:
It simply re-exports the attendance router so older imports still work
while the rename is in progress. :contentReference[oaicite:30]{index=30}

Why it matters:
It proves the rename is incomplete but controlled.

backend/routers/new changeges SBT01.txt
---------------------------------------
Role:
Loose note file inside code folder.

What it represents:
Probably a development scratch/note artifact from earlier work.
It is not part of the running architecture and should not stay in the router package long term.

8) SCHEMAS LAYER — backend/schemas/
-----------------------------------
General purpose:
These files define Pydantic request/response structures and API validation boundaries.

backend/schemas/__init__.py
---------------------------
Role:
Schema package export point.

backend/schemas/driver.py
-------------------------
Role:
Driver request/response validation.

backend/schemas/school.py
-------------------------
Role:
School request/response validation.

backend/schemas/student.py
--------------------------
Role:
Student request/response validation.

backend/schemas/route.py
------------------------
Role:
Route request/response validation.

backend/schemas/stop.py
-----------------------
Role:
Stop request/response validation.

backend/schemas/run.py
----------------------
Role:
Run request/response validation.

backend/schemas/dispatch.py
---------------------------
Role:
Payroll/dispatch request/response validation.

backend/schemas/student_bus_absence.py
--------------------------------------
Role:
Planned absence request/response validation.

backend/schemas/student_run_assignment.py
-----------------------------------------
Role:
Runtime student assignment request/response validation.

Why the schemas folder matters:
This layer separates ORM/database structure from public API payloads.
That makes the project safer, more maintainable, and easier to test.

9) UTILS LAYER — backend/utils/
-------------------------------
General purpose:
Shared business logic and support helpers.

backend/utils/__init__.py
-------------------------
Role:
Utility package initializer.

backend/utils/attendance_generator.py
-------------------------------------
Role:
Attendance business-logic engine.

What it represents:
This is the main computation file for attendance summaries and operational status transformation.
It contains functions that take database objects and produce report-ready summaries. :contentReference[oaicite:31]{index=31}

Most important functions:
- driver_summary(db, driver_id)
- route_summary(db, route_id)
- payroll_summary(db, start, end)
- generate_attendance(db, attendance_type, ...)
- generate_report (compatibility alias)
- classify_student_attendance(assignment, events, absence_lookup)
- run_attendance_summary(db, run, assignments, events, absence_lookup)
- date_summary(db, start, end)
- normalize_school_status(status)
- school_summary(db, school_id) :contentReference[oaicite:32]{index=32}

What this file does conceptually:
It converts raw operational data into human-facing attendance views.

Examples:
- driver_summary gives overall driver work-related aggregates
- route_summary serializes route, schools, stops, students, and run counts
- classify_student_attendance translates assignment state + run events + planned absences
  into statuses such as planned_absent, picked_up, dropped_off, no_show, expected
- run_attendance_summary groups student and stop attendance for one run
- school_summary collapses operational states into school-facing present/absent
  and attaches school confirmation state per run :contentReference[oaicite:33]{index=33}

Architectural significance:
This is supposed to be the business layer behind the attendance router.

Important current weakness:
It also contains router-like code and transition leftovers, so it is not cleanly separated yet. :contentReference[oaicite:34]{index=34}

backend/utils/report_generator.py
---------------------------------
Role:
Legacy compatibility utility.

What it represents:
It re-exports attendance_generator helpers under the older “report” naming
so old imports do not break during migration. :contentReference[oaicite:35]{index=35}

Why it matters:
It is a transition bridge, not a true independent logic layer anymore.

backend/utils/student_bus_absence.py
------------------------------------
Role:
Planned absence helper logic.

What it represents:
A focused helper file that knows how to answer:
- does this student have a bus absence for this run?
- how can a run-assignment query exclude planned-absent students? :contentReference[oaicite:36]{index=36}

Main functions:
- has_student_bus_absence(student_id, run, db)
- apply_run_absence_filter(query, run) :contentReference[oaicite:37]{index=37}

Why it matters:
This is the core “planned no-ride” support logic used by attendance computations.

backend/utils/auth.py
---------------------
Role:
Authentication/session helpers.

What it likely represents:
Functions used by app.py such as:
- get_current_driver
- login_driver
- logout_driver

Why it matters:
It powers the driver session flow.

backend/utils/gps_tools.py
--------------------------
Role:
GPS helper logic.

What it represents:
Operational real-time tracking support for active runs.

How app.py uses it:
- validate_gps(lat, lng)
- get_current_stop_progress(db, run_id, lat, lng)
- get_approaching_alerts(db, run_id, lat, lng) :contentReference[oaicite:38]{index=38}

Why it matters:
This file powers the websocket-based live run tracking.

backend/utils/db_errors.py
--------------------------
Role:
Database error handling helper.

What it likely represents:
Reusable DB exception normalization or helper utilities for cleaner route logic.

10) TEMPLATES LAYER — backend/templates/
----------------------------------------
General purpose:
Server-rendered HTML pages for human users.

backend/templates/dashboard.html
--------------------------------
Role:
Dashboard page.

What it represents:
A summary/admin-like landing page that shows counts of drivers, schools, routes,
students, and active runs. app.py renders it from /dashboard. :contentReference[oaicite:39]{index=39}

backend/templates/driver_run.html
---------------------------------
Role:
Driver operational page.

What it represents:
Displays the driver's active or pending run, route, stops, and today’s context.
Rendered by app.py at /driver_run/{driver_id}. :contentReference[oaicite:40]{index=40}

backend/templates/route_report.html
-----------------------------------
Role:
Route report page.

What it represents:
Displays route attendance/report details with route data and driver name.
Rendered by app.py at /route_report/{route_id}. :contentReference[oaicite:41]{index=41}

backend/templates/summary_report.html
-------------------------------------
Role:
Summary/payroll page.

What it represents:
Displays payroll-style summary over a date range.
Rendered by app.py at /summary_report. :contentReference[oaicite:42]{index=42}

backend/templates/school_mobile_report.html
-------------------------------------------
Role:
School mobile attendance page.

What it represents:
A school-facing mobile report view for reviewing route/run attendance
and performing school-side confirmation and present/absent checks.

Why it matters:
This is the practical UI surface for the current attendance workflow.
attendance.py renders it using report data from attendance_generator.generate_attendance(...). :contentReference[oaicite:43]{index=43}

11) FRONTEND FOLDER
-------------------
frontend/index.html
-------------------
Role:
Separate frontend placeholder or legacy static page.

What it represents:
A standalone frontend artifact outside the server-rendered Jinja flow.
At present, the project’s active frontend behavior appears to be primarily in backend/templates,
so this file looks secondary or experimental.

12) TESTS LAYER — tests/
------------------------
General purpose:
The test suite shows what the project considers critical behavior.

tests/conftest.py
-----------------
Role:
pytest fixtures and shared test setup.

What it represents:
Common initialization for tests.

tests/test_all.py
-----------------
Role:
Broad integration/regression test file.

What it represents:
A catch-all test area for multiple modules or workflows.

tests/test_api_surface.py
-------------------------
Role:
Endpoint/API surface verification.

What it represents:
Checks that expected APIs exist and behave with the correct outer contract.

tests/test_run_absence_integration.py
-------------------------------------
Role:
Run + planned absence integration test.

What it represents:
Verifies that planned student absences interact correctly with run logic and attendance.

tests/test_run_next_stop.py
---------------------------
Role:
Next-stop behavior test.

What it represents:
Checks logic that determines which stop is current/next during live run progression.

tests/test_run_progress.py
--------------------------
Role:
Run progression test.

What it represents:
Verifies state transitions over the life of a run.

tests/test_running_board.py
---------------------------
Role:
Operational board test.

What it represents:
Likely validates live operational visibility of runs/students/stops.

tests/test_stops_edge_cases.py
------------------------------
Role:
Stop logic edge-case test.

What it represents:
Ensures stop handling does not break on unusual or boundary scenarios.

tests/test_stops_sequence.py
----------------------------
Role:
Stop ordering test.

What it represents:
Validates stable sequence/order behavior for stops.

13) HOW THE MAIN FILES RELATE TO EACH OTHER
-------------------------------------------
The core runtime relationship is:

app.py
  -> initializes FastAPI
  -> uses database.py
  -> registers routers
  -> renders templates
  -> exposes websocket GPS and login/session pages

database.py
  -> provides Base, engine, SessionLocal, get_db

models/
  -> define persistent entities and relationships

schemas/
  -> validate API payloads around those entities

routers/
  -> expose CRUD and operational endpoints for those entities

attendance.py
  -> special application router
  -> calls attendance_generator and absence helpers
  -> reads/writes SchoolAttendanceVerification
  -> renders school_mobile_report.html

attendance_generator.py
  -> transforms model data into summaries
  -> classifies attendance
  -> builds school/date/run/route/driver/payroll reports

student_bus_absence.py helper
  -> supports attendance classification by planned absence status

templates/
  -> human-facing pages that visualize backend data

tests/
  -> validate core operational behavior

14) WHAT THE PROJECT IS REALLY DOING FUNCTIONALLY
-------------------------------------------------
In plain project terms, SBT03 is trying to solve these workflows:

1. Domain setup
   - manage drivers
   - manage schools
   - manage students
   - manage routes
   - manage stops
   - manage runs

2. Runtime operation
   - assign students to active runs
   - track live GPS progress
   - know which stop is next
   - record run events such as no-show

3. Attendance logic
   - combine runtime assignments, run events, and planned absences
   - produce route, run, date, driver, and school attendance summaries
   - convert detailed operations into school-facing present/absent views

4. School-facing workflow
   - school opens mobile report
   - sees grouped routes and runs
   - reviews student statuses
   - confirms attendance for that school and run
   - optionally updates school-side student status rows

5. Business/admin workflow
   - dashboard counts
   - payroll summary
   - driver work summaries

15) MOST IMPORTANT FILES TO STUDY FIRST
---------------------------------------
If someone is studying the repo from zero, read in this order:

1. app.py
2. database.py
3. backend/models/__init__.py
4. backend/routers/attendance.py
5. backend/utils/attendance_generator.py
6. backend/utils/student_bus_absence.py
7. backend/routers/report.py and backend/utils/report_generator.py
8. backend/templates/school_mobile_report.html
9. tests related to run and absence integration

That order gives the clearest mental map of the system.

16) CURRENT PROJECT STATE IN ONE SENTENCE
-----------------------------------------
SBT03 is a transport-operations backend whose core is already functional around drivers,
routes, runs, attendance, and school confirmation, but the codebase is still midway through
a rename-and-cleanup phase where attendance has replaced report as the main application layer.

SBT03 — Recommended Cleanup Roadmap
===================================

GOAL
----
Clean the repo without breaking current behavior.
The priority is not “rewrite everything.”
The priority is:
1. stabilize current attendance flow
2. remove architectural confusion
3. make the repo easier to understand
4. prepare the project for safer future development

PRINCIPLE
---------
Do cleanup in layers:
- first fix real bugs
- then fix structure
- then fix naming
- then improve docs
- then improve security and deployment readiness

==================================================
PHASE 1 — FIX REAL BUGS FIRST
==================================================

1. Fix the broken "run" branch in attendance_generator.generate_attendance()
---------------------------------------------------------------------------
Problem:
In backend/utils/attendance_generator.py, generate_attendance() has a branch:

    if attendance_type == "run" and ref_id:
        return run_attendance_summary(db, ref_id)

But run_attendance_summary() actually expects:
    db, run, assignments, events, absence_lookup

So this branch is incorrect and can fail if used. :contentReference[oaicite:0]{index=0}

What to do:
- either remove the "run" branch entirely if it is unused
- or rewrite it properly so it loads:
  - run
  - assignments
  - events
  - absence_lookup
  and only then calls run_attendance_summary()

Why this is first:
This is a true correctness problem, not just style.

2. Fix the duplicate run attendance endpoint logic inside attendance_generator.py
--------------------------------------------------------------------------------
Problem:
At the bottom of backend/utils/attendance_generator.py there is another
@get("/run/{run_id}") style function that should not be living in a utility file. :contentReference[oaicite:1]{index=1}

It also does this:
    "student_count": len(attendance)

But attendance there is the dictionary returned by run_attendance_summary(),
so len(attendance) counts dictionary keys, not students. :contentReference[oaicite:2]{index=2}

What to do:
- delete that duplicate route function from attendance_generator.py
- keep the real run attendance endpoint only in backend/routers/attendance.py
- if you need a helper, keep only pure helper functions in the utils file

Why this matters:
This is both a bug and a layering problem.

3. Fix school attendance by date filtering
------------------------------------------
Problem:
In backend/routers/attendance.py, get_school_attendance_by_date()
filters runs with:

    Run.start_time < (target_date + timedelta(days=1))

but it does not add a lower bound like:

    Run.start_time >= target_date at 00:00

So it can include older runs before the requested date. :contentReference[oaicite:3]{index=3}

What to do:
Use a full-day datetime range:
- day_start = datetime.combine(target_date, time.min)
- day_end = datetime.combine(target_date, time.max)

Then filter:
- Run.start_time >= day_start
- Run.start_time <= day_end

Why this matters:
This is a report accuracy problem.

4. Fix the swallowed .order_by() in get_absences_by_run()
---------------------------------------------------------
Problem:
In backend/routers/attendance.py, the comment at the end of the date filter line
appears to swallow the intended .order_by(...) continuation. :contentReference[oaicite:4]{index=4}

What to do:
Rewrite that query cleanly, one clause per line, for example:
- .filter(...)
- .filter(...)
- .order_by(StudentBusAbsence.id.asc())
- .all()

Why this matters:
It avoids silent bugs and makes the query readable.

==================================================
PHASE 2 — CLEAN LAYER BOUNDARIES
==================================================

5. Make attendance.py the only attendance router file
-----------------------------------------------------
Problem:
Right now attendance routing logic is split conceptually across:
- backend/routers/attendance.py
- backend/utils/attendance_generator.py

But utils should not define routers or endpoint handlers. :contentReference[oaicite:5]{index=5} :contentReference[oaicite:6]{index=6}

What to do:
Keep this rule:

A. backend/routers/attendance.py
   only endpoint handlers, request parsing, validation, and response assembly

B. backend/utils/attendance_generator.py
   only pure business logic / summary builders

C. backend/utils/student_bus_absence.py
   only planned-absence helper logic

Why this matters:
This is the single biggest structure improvement in the repo.

6. Remove router imports from the utils layer
---------------------------------------------
Problem:
attendance_generator.py imports router-related material and even imports:
- backend.routers.student_bus_absence
- APIRouter
- HTTPException
- Depends
- get_db
and defines router = APIRouter(...) inside a utility file. :contentReference[oaicite:7]{index=7}

What to do:
Delete all router-specific imports and APIRouter setup from attendance_generator.py.

Why this matters:
A utility module should not behave like a router module.

7. Remove self-import / recursive-style imports in attendance_generator.py
--------------------------------------------------------------------------
Problem:
attendance_generator.py imports attendance_generator from backend.utils
inside itself. :contentReference[oaicite:8]{index=8}

What to do:
- remove self-import
- call local functions directly inside the same file

Why this matters:
It reduces confusion and prevents circular-import style mistakes.

==================================================
PHASE 3 — COMPLETE THE REPORT → ATTENDANCE RENAME
==================================================

8. Keep compatibility files only as thin bridges
------------------------------------------------
Current status:
- backend/routers/report.py just re-exports attendance.router
- backend/utils/report_generator.py just re-exports attendance_generator helpers :contentReference[oaicite:9]{index=9} :contentReference[oaicite:10]{index=10}

This is fine temporarily.

What to do:
Short-term:
- keep them as compatibility shims
- add one clear comment at top saying they are temporary bridges

Later:
- remove them only after all imports in the project are switched to attendance naming

Why this matters:
It lets you clean safely without breaking callers.

9. Standardize naming across comments and titles
------------------------------------------------
Problem:
The repo currently mixes:
- SBT03
- SBT02
- SBT01
- BST
- BST01
- report
- attendance :contentReference[oaicite:11]{index=11} :contentReference[oaicite:12]{index=12} :contentReference[oaicite:13]{index=13} :contentReference[oaicite:14]{index=14}

What to do:
Choose one standard and apply it consistently.

Recommended standard:
- Project name in comments: SBT03
- Module name: Attendance
- Compatibility comments may mention "legacy report naming"

Where to update:
- app.py header and root response text
- database.py header
- config.py header
- top comments in routers and utils
- compatibility files

Why this matters:
This is low risk and immediately improves readability.

==================================================
PHASE 4 — CLEAN PROJECT ORGANIZATION
==================================================

10. Replace structure.txt with the new real structure
-----------------------------------------------------
Problem:
Current structure.txt is outdated and includes venv/__pycache__ noise. :contentReference[oaicite:15]{index=15}

What to do:
Replace it with the clearer study-style structure we already drafted.

Why this matters:
Anyone opening the repo gets a usable project map.

11. Add a real README.md
------------------------
Problem:
README.md is empty. :contentReference[oaicite:16]{index=16}

What to include:
- what SBT03 is
- current stack
- module overview
- how to run locally
- active architecture
- note that attendance is the current reporting layer
- folder overview
- current project status

Why this matters:
This is the main human entry point for the repo.

12. Remove or move "new changeges SBT01.txt"
--------------------------------------------
Problem:
There is a loose text file inside backend/routers. It does not belong in production code structure.

What to do:
- move it to docs/notes/ if still useful
- otherwise delete it

Why this matters:
It reduces noise and makes the routers folder professional.

13. Check whether backend/templates/static actually exists
----------------------------------------------------------
Problem:
app.py mounts:
    /static -> backend/templates/static
but the current repo view does not clearly show that folder. :contentReference[oaicite:17]{index=17}

What to do:
- verify the folder exists
- if it does not exist:
  - create it
  - or update mount path
  - or remove the mount until needed

Why this matters:
A wrong static mount can break startup.

==================================================
PHASE 5 — IMPROVE CODE READABILITY
==================================================

14. Normalize import sections in all major files
------------------------------------------------
Problem:
Some files have duplicated imports, mixed import order, and repeated imported names,
especially app.py and attendance_generator.py. :contentReference[oaicite:18]{index=18} :contentReference[oaicite:19]{index=19}

What to do:
Use a standard pattern in each file:
- standard library
- third-party
- local application imports

Then remove duplicates.

Why this matters:
It makes each file easier to scan.

15. Keep comments useful, not noisy
-----------------------------------
Problem:
Some comments are good, but some are too repetitive or explain obvious code line by line.

What to do:
Keep:
- section headers
- business-rule comments
- comments explaining why something exists

Reduce:
- comments that only restate the code
- repeated separator lines when not needed

Why this matters:
Too many comments can hide the real logic.

16. Separate “business rules” from “display formatting”
-------------------------------------------------------
Best example:
In attendance_generator.py, some logic is operational:
- planned_absent
- no_show
- picked_up
- dropped_off
- expected

Then school_summary collapses those into:
- present
- absent via normalize_school_status() :contentReference[oaicite:20]{index=20}

What to improve:
Keep this distinction very explicit:
- operational attendance state
- school-facing display state

Why this matters:
This is one of the core business concepts of the whole project.

==================================================
PHASE 6 — SAFETY / SECURITY / DEPLOYMENT CLEANUP
==================================================

17. Strengthen login
--------------------
Problem:
The current /login only accepts driver_id and logs that driver in. :contentReference[oaicite:21]{index=21}

What to do:
For local testing:
- keep it if needed, but mark it clearly as dev-only

For real deployment:
- add actual authentication
- or protect behind debug mode
- or require secret/token/password

Why this matters:
Current auth is too weak beyond development.

18. Tighten CORS
----------------
Problem:
app.py uses:
- allow_origins=["*"]
- allow_credentials=True :contentReference[oaicite:22]{index=22}

What to do:
Move to explicit allowed origins for production.

Why this matters:
This is a basic deployment safety improvement.

19. Choose one schema authority
-------------------------------
Problem:
The repo has Alembic, but app.py still calls Base.metadata.create_all(bind=engine). :contentReference[oaicite:23]{index=23}

What to do:
Choose one of these models:

Option A:
- keep create_all for fast local dev only
- use Alembic for shared/prod schema changes

Option B:
- stop using create_all entirely
- use Alembic everywhere

Why this matters:
Mixed schema strategy causes confusion.

==================================================
PHASE 7 — TESTING CLEANUP
==================================================

20. Add tests specifically for attendance transition behavior
-------------------------------------------------------------
Recommended new tests:
- school confirmation saved independently per school and run
- school attendance by date only returns that exact date
- absences by run are ordered correctly
- generate_attendance("run", ...) works or is removed cleanly
- school_summary correctly builds present/absent from full roster
- compatibility imports report.py and report_generator.py still work

Why this matters:
These are the exact areas currently most fragile.

21. Add one focused test file for attendance module integrity
-------------------------------------------------------------
Suggested file:
- tests/test_attendance_module_integrity.py

Cover:
- router endpoints
- generator outputs
- confirmation persistence
- school-facing status normalization

Why this matters:
Attendance is now the heart of the reporting layer.

==================================================
BEST EXECUTION ORDER
==================================================

Order to actually perform cleanup:

STEP 1
Fix the four real bugs:
- generate_attendance run branch
- duplicate run route in attendance_generator.py
- school date filtering
- swallowed order_by in absences by run

STEP 2
Remove router code from attendance_generator.py

STEP 3
Clean imports and self-imports in attendance_generator.py

STEP 4
Standardize naming comments to SBT03 / Attendance

STEP 5
Replace structure.txt and write README.md

STEP 6
Move/remove stray text file in routers

STEP 7
Verify static mount path

STEP 8
Add targeted attendance tests

STEP 9
Later, improve auth, CORS, and schema strategy

==================================================
WHAT NOT TO DO YET
==================================================

Do not:
- rewrite the whole repo at once
- remove compatibility files immediately
- rename every endpoint path immediately
- refactor all routers together in one big step
- change business logic and architecture in the same pass

Reason:
The project already has working parts.
The safest cleanup is incremental cleanup.

==================================================
MOST IMPORTANT CLEANUP TARGET
==================================================

If only one file is cleaned first, it should be:

backend/utils/attendance_generator.py

Because that file currently contains:
- core business logic
- duplicate endpoint logic
- router setup
- self-import confusion
- report-to-attendance transition leftovers :contentReference[oaicite:24]{index=24}

That is the highest-value cleanup point in the entire repo.