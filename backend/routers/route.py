from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db

from backend.models.associations import RouteDriverAssignment
from backend.models.driver import Driver
from backend.models.route import Route
from backend.models.school import School
from backend.models import run as run_model
from backend.models import student as student_model
from backend.models.associations import StudentRunAssignment
from backend.schemas.route import (
    RouteCreate,
    RouteDetailOut,
    RouteDetailRunOut,
    RouteDetailStopOut,
    RouteDetailStudentOut,
    RouteDriverAssignmentCreate,
    RouteDriverAssignmentOut,
    RouteOut,
    RouteSchoolOut,
)
from backend.utils.route_driver_assignment import resolve_route_driver_assignment
from datetime import datetime, timezone

router = APIRouter(prefix="/routes", tags=["Routes"])


# -----------------------------------------------------------
# - Route serializer
# - Return stable route summary payloads with assignment context
# -----------------------------------------------------------
def _serialize_route(route: Route) -> RouteOut:
    active_driver_id = None  # Default when no active driver resolves
    active_driver_name = None  # Default when no active driver resolves

    try:
        active_assignment = resolve_route_driver_assignment(route)  # Resolve current route driver
        active_driver_id = active_assignment.driver_id  # Resolved driver identifier
        active_driver_name = active_assignment.driver.name if active_assignment.driver else None  # Resolved driver name
    except ValueError:
        pass  # Leave unresolved route driver fields empty

    runs_count = len(route.runs)  # Total runs linked to this route
    active_runs_count = sum(  # Count only active operational runs
        1
        for run in route.runs
        if run.start_time is not None and run.end_time is None
    )
    total_stops_count = sum(len(run.stops) for run in route.runs)  # Count all stops across route runs
    total_students_count = len({  # Count distinct runtime students across all route runs
        assignment.student_id
        for run in route.runs
        for assignment in run.student_assignments
    })

    return RouteOut(
        id=route.id,
        route_number=route.route_number,
        unit_number=route.unit_number,
        school_ids=[school.id for school in sorted(route.schools, key=lambda school: (school.name, school.id))],
        school_names=[school.name for school in sorted(route.schools, key=lambda school: (school.name, school.id))],
        schools_count=len(route.schools),
        active_driver_id=active_driver_id,
        active_driver_name=active_driver_name,
        runs_count=runs_count,
        active_runs_count=active_runs_count,
        total_stops_count=total_stops_count,
        total_students_count=total_students_count,
    )


# -----------------------------------------------------------
# - Route detail serializer
# - Return the full nested route detail payload
# -----------------------------------------------------------
def _serialize_route_detail(route: Route) -> RouteDetailOut:
    active_driver_id = None  # Default when no active driver resolves
    active_driver_name = None  # Default when no active driver resolves

    try:
        active_assignment = resolve_route_driver_assignment(route)  # Resolve current route driver
        active_driver_id = active_assignment.driver_id  # Resolved driver identifier
        active_driver_name = active_assignment.driver.name if active_assignment.driver else None  # Resolved driver name
    except ValueError:
        pass  # Leave unresolved route driver fields empty

    ordered_runs = sorted(  # Keep detail output stable and newest-first
        route.runs,
        key=lambda run: (run.start_time or datetime.min, run.id),
        reverse=True,
    )

    serialized_runs = []  # Final run detail rows

    for run in ordered_runs:
        ordered_stops = sorted(  # Stable stop order per run
            run.stops,
            key=lambda stop: (
                stop.sequence if stop.sequence is not None else 999999,
                stop.id,
            ),
        )

        stop_student_counts = {}  # stop_id -> runtime student count
        for assignment in run.student_assignments:
            if assignment.stop_id is None:
                continue
            stop_student_counts[assignment.stop_id] = stop_student_counts.get(assignment.stop_id, 0) + 1

        serialized_stops = [
            RouteDetailStopOut(
                stop_id=stop.id,
                sequence=stop.sequence,
                type=stop.type.value if hasattr(stop.type, "value") else str(stop.type),
                name=stop.name,
                address=stop.address,
                planned_time=stop.planned_time,
                student_count=stop_student_counts.get(stop.id, 0),
            )
            for stop in ordered_stops
        ]

        ordered_assignments = sorted(  # Stable student order by assigned stop then row id
            run.student_assignments,
            key=lambda assignment: (
                assignment.stop.sequence if assignment.stop and assignment.stop.sequence is not None else 999999,
                assignment.student.name if assignment.student else "",
                assignment.id,
            ),
        )

        serialized_students = []
        for assignment in ordered_assignments:
            if not assignment.student:
                continue

            serialized_students.append(
                RouteDetailStudentOut(
                    student_id=assignment.student.id,
                    student_name=assignment.student.name,
                    school_id=assignment.student.school_id,
                    school_name=assignment.student.school.name if assignment.student.school else None,
                    school_code=assignment.student.school.school_code if assignment.student.school else None,
                    stop_id=assignment.stop_id,
                    stop_sequence=assignment.stop.sequence if assignment.stop else None,
                    stop_name=assignment.stop.name if assignment.stop else None,
                )
            )

        serialized_runs.append(
            RouteDetailRunOut(
                run_id=run.id,
                run_type=run.run_type,
                start_time=run.start_time,
                end_time=run.end_time,
                driver_id=run.driver_id,
                driver_name=run.driver.name if run.driver else None,
                is_planned=run.start_time is None,
                is_active=run.start_time is not None and run.end_time is None,
                is_completed=run.is_completed,
                stops=serialized_stops,
                students=serialized_students,
            )
        )

    return RouteDetailOut(
        id=route.id,
        route_number=route.route_number,
        unit_number=route.unit_number,
        schools=[
            RouteSchoolOut(
                school_id=school.id,
                school_name=school.name,
                school_code=school.school_code,
            )
            for school in sorted(route.schools, key=lambda school: (school.name, school.id))
        ],
        active_driver_id=active_driver_id,
        active_driver_name=active_driver_name,
        driver_assignments=[
            RouteDriverAssignmentOut(
                id=assignment.id,
                route_id=assignment.route_id,
                driver_id=assignment.driver_id,
                driver_name=assignment.driver.name if assignment.driver else None,
                active=assignment.active,
            )
            for assignment in sorted(
                route.driver_assignments,
                key=lambda assignment: (not assignment.active, assignment.id),
            )
        ],
        runs=serialized_runs,
    )

# -----------------------------------------------------------
# - Create route without driver assignment
# - Document duplicate route_number conflict in Swagger
# -----------------------------------------------------------
@router.post(
    "/",                                                          # Keep route collection path stable
    response_model=RouteOut,                                     # Successful response model
    summary="Create route",                                      # Clear Swagger title
    description=(                                                # Explain real route creation flow
        "Create a route without assigning a driver. "
        "Driver assignment is handled separately. "
        "Route numbers must be unique."
    ),
    response_description="Created route",                        # Swagger success text
    responses={
        409: {                                                   # Duplicate route_number response
            "description": "Route number already exists",
            "content": {
                "application/json": {
                    "example": {"detail": "Route number already exists"}
                }
            },
        }
    },
)
def create_route(route: RouteCreate, db: Session = Depends(get_db)):
    payload = route.model_dump(exclude_unset=True)               # Read validated route payload
    school_ids = payload.pop("school_ids", [])                   # Separate school assignment ids

    existing_route = (
        db.query(Route)
        .filter(Route.route_number == payload["route_number"])   # Enforce unique route number only
        .first()
    )
    if existing_route:
        raise HTTPException(
            status_code=409,                                     # Conflict for duplicate route number
            detail="Route number already exists",
        )

    db_route = Route(**payload)                                  # Create route after uniqueness check
    db.add(db_route)                                             # Add route to session
    db.flush()                                                   # Allocate route id before school linking

    if school_ids:
        db_route.schools = db.query(School).filter(School.id.in_(school_ids)).all()  # Attach requested schools

    db.commit()                                                  # Persist route and optional schools
    db.refresh(db_route)                                         # Reload committed route
    return _serialize_route(db_route)                            # Return route summary


# -----------------------------------------------------------
# - List routes
# - Return route summaries for navigation and selection
# -----------------------------------------------------------
@router.get(
    "/",
    response_model=List[RouteOut],
    summary="List routes",
    description="Return lightweight route summaries with school, driver, run, stop, and student counts for navigation.",
    response_description="Route summary list",
)
def get_routes(db: Session = Depends(get_db)):
    routes = (
        db.query(Route)
        .options(
            selectinload(Route.schools),                         # Load school summary fields
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),  # Load active driver context
            selectinload(Route.runs).selectinload(run_model.Run.stops),  # Load stop counts per run
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments),  # Load runtime student counts
        )
        .order_by(Route.route_number.asc(), Route.id.asc())      # Keep route list stable
        .all()
    )
    return [_serialize_route(route) for route in routes]         # Return summary collection

# -----------------------------------------------------------
# - Get route detail
# - Return full nested route details for one selected route
# -----------------------------------------------------------
@router.get(
    "/{route_id}",
    response_model=RouteDetailOut,
    summary="Get route detail",
    description="Return one route with nested schools, driver assignments, runs, stops, and runtime student details.",
    response_description="Route detail",
)
def get_route(route_id: int, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(
            selectinload(Route.schools),                         # Include linked schools
            selectinload(Route.driver_assignments).selectinload(RouteDriverAssignment.driver),  # Include driver assignments
            selectinload(Route.runs).selectinload(run_model.Run.driver),  # Include run driver data
            selectinload(Route.runs).selectinload(run_model.Run.stops),  # Include run stops
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.stop),  # Include assigned runtime stops
            selectinload(Route.runs).selectinload(run_model.Run.student_assignments).selectinload(StudentRunAssignment.student).selectinload(student_model.Student.school),  # Include assigned students and schools
        )
        .filter(Route.id == route_id)                           # Match requested route id
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")  # Validate route exists

    return _serialize_route_detail(route)                       # Return full route detail payload


# -----------------------------------------------------------
# - Update route
# - Modify one route while preserving uniqueness rules
# -----------------------------------------------------------
@router.put("/{route_id}", response_model=RouteOut)
def update_route(route_id: int, route_in: RouteCreate, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(
            joinedload(Route.schools),
            joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver),
        )
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    update_data = route_in.model_dump(exclude_unset=True)
    school_ids = update_data.pop("school_ids", None)
    # -----------------------------------------------------------
    # - Protect route_number uniqueness on update
    # - Exclude current route from duplicate detection
    # -----------------------------------------------------------
    new_route_number = update_data.get("route_number")                              # Proposed route number from request

    if new_route_number and new_route_number != route.route_number:                 # Check only when route number changes
        existing_route = (
            db.query(Route)
            .filter(Route.route_number == new_route_number)                         # Find matching route number
            .filter(Route.id != route_id)                                           # Exclude current route
            .first()
        )

        if existing_route:                                                          # Duplicate route number found
            raise HTTPException(
                status_code=409,
                detail="Route number already exists",
            )
    for key, value in update_data.items():
        setattr(route, key, value)

    if school_ids is not None:
        route.schools = db.query(School).filter(School.id.in_(school_ids)).all()

    db.commit()
    db.refresh(route)
    return _serialize_route(route)


# -----------------------------------------------------------
# - Delete route
# - Remove one route by id
# -----------------------------------------------------------
@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(route_id: int, db: Session = Depends(get_db)):
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    db.delete(route)
    db.commit()
    return None


# -----------------------------------------------------------
# - List route schools
# - Return the schools linked to one route
# -----------------------------------------------------------
@router.get("/{route_id}/schools", response_model=List[dict])
def get_route_schools(route_id: int, db: Session = Depends(get_db)):
    route = db.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    return [{"id": s.id, "name": s.name, "address": s.address} for s in route.schools]
# -----------------------------------------------------------
# - Assign driver to route
# - Enforce one active driver per route
# -----------------------------------------------------------
def _assign_driver_to_route(
    route: Route,
    driver_id: int,
    db: Session,
) -> RouteDriverAssignment:

    driver = db.get(Driver, driver_id)                           # Validate driver exists
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    # -----------------------------------------------------------
    # Deactivate all current active assignments
    # -----------------------------------------------------------
    active_assignments = (
        db.query(RouteDriverAssignment)
        .filter(RouteDriverAssignment.route_id == route.id)
        .filter(RouteDriverAssignment.active.is_(True))
        .all()
    )

    for assignment in active_assignments:
        assignment.active = False                                # Only one active driver allowed

    # -----------------------------------------------------------
    # Create new active assignment
    # -----------------------------------------------------------
    new_assignment = RouteDriverAssignment(
        route_id=route.id,
        driver_id=driver_id,
        active=True,
    )

    db.add(new_assignment)
    db.flush()

    return new_assignment

# -----------------------------------------------------------
# - Assign one active driver to a route
# - Swagger should describe the real assignment workflow
# -----------------------------------------------------------
@router.post(
    "/{route_id}/assign_driver/{driver_id}",                     # Route + driver selected from path
    response_model=RouteDriverAssignmentOut,                     # Return the activated assignment
    summary="Assign active driver to route",                     # Clear Swagger title
    description=(                                                # Explain exact SBT03 behavior
        "Assign a driver to a route as the single active assignment. "
        "If another active driver assignment already exists for the route, "
        "it is automatically deactivated. No request body is required."
    ),
    response_description="The newly active route-driver assignment",  # Swagger response text
)
def assign_driver_to_route(
    route_id: int,
    driver_id: int,
    db: Session = Depends(get_db),
):

    route = (
        db.query(Route)
        .options(joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver))
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    assignment = _assign_driver_to_route(route, driver_id, db)

    db.commit()
    db.refresh(assignment)

    return RouteDriverAssignmentOut(
        id=assignment.id,
        route_id=assignment.route_id,
        driver_id=assignment.driver_id,
        driver_name=assignment.driver.name if assignment.driver else None,
        active=assignment.active,
    )

# -----------------------------------------------------------
# - List driver assignments for one route
# - Show which assignment is currently active
# -----------------------------------------------------------
@router.get(
    "/{route_id}/drivers",                                       # Read assignments for one route
    response_model=List[RouteDriverAssignmentOut],               # Return assignment collection
    summary="List route driver assignments",                     # Clear Swagger title
    description=(                                                # Explain what the list represents
        "Return all driver assignments for the route, including which one is "
        "currently active."
    ),
    response_description="Route driver assignment list",         # Swagger response text
)
def get_route_drivers(route_id: int, db: Session = Depends(get_db)):
    route = (
        db.query(Route)
        .options(joinedload(Route.driver_assignments).joinedload(RouteDriverAssignment.driver))
        .filter(Route.id == route_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    return [
        RouteDriverAssignmentOut(
            id=assignment.id,
            route_id=assignment.route_id,
            driver_id=assignment.driver_id,
            driver_name=assignment.driver.name if assignment.driver else None,
            active=assignment.active,
        )
        for assignment in route.driver_assignments
    ]


# -----------------------------------------------------------
# - Unassign driver from route
# - Deactivate active assignments for one route and driver
# -----------------------------------------------------------
@router.delete("/{route_id}/unassign_driver/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_driver_from_route(route_id: int, driver_id: int, db: Session = Depends(get_db)):
    assignments = (
        db.query(RouteDriverAssignment)
        .filter(RouteDriverAssignment.route_id == route_id)
        .filter(RouteDriverAssignment.driver_id == driver_id)
        .filter(RouteDriverAssignment.active.is_(True))
        .all()
    )
    if not assignments:
        raise HTTPException(status_code=404, detail="Active route-driver assignment not found")

    # -----------------------------------------------------------
    # - Deactivate assignment
    # - No date tracking needed in current model
    # -----------------------------------------------------------
    for assignment in assignments:
        assignment.active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
