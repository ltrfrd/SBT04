# SBT - School Bus Transport and Operations System

## Overview
SBT is a workflow-first bus operations backend built on FastAPI, SQLAlchemy, Alembic, and Jinja templates. The repository is organized around a simple operator flow:

Route -> Run -> Stop -> Student

This is not a rewrite. The protected runtime engine stays in place while the setup flow becomes simpler and more context-driven.

## Preferred Workflow
The intended operator path is:

1. Create a route
2. Assign schools to the route
3. Assign a driver to the route
4. Create runs inside the route
5. Create stops inside the run
6. Add students from stop context

Preferred context-first endpoints:

- `POST /routes/{route_id}/runs`
- `POST /runs/{run_id}/stops`
- `POST /runs/{run_id}/stops/{stop_id}/students`
- `POST /runs/{run_id}/stops/{stop_id}/students/bulk`

These endpoints reduce repeated manual IDs in the normal workflow:

- route context creates runs
- run context creates stops
- stop context creates students
- `StudentRunAssignment` is created internally

## Runtime And Maintenance Flow
After the setup hierarchy exists, real usage should continue from route and run context:

1. Driver selects an assigned route
2. Driver reviews the route's prepared runs
3. Driver starts and operates the selected run
4. Runtime views read the prepared stop and student structure from that run

Maintenance and compatibility remain separate from the normal setup path:

- `PUT /students/{student_id}/assignment` is a correction / reassignment endpoint
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

Protected runtime and reporting:

- `backend/routers/run.py`
- `backend/routers/attendance.py`
- `backend/routers/report.py`
- `backend/utils/attendance_generator.py`
- `backend/utils/report_generator.py`

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
