# ===========================================================
# backend/routers/web_pages.py - FleetOS Web Page Router
# -----------------------------------------------------------
# HTML-rendered page endpoints extracted from app bootstrap
# ===========================================================

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from database import get_db
from backend.models import (
    dispatch as dispatch_model,
    driver as driver_model,
    pretrip as pretrip_model,
    posttrip as posttrip_model,
    route as route_model,
    run as run_model,
    school as school_model,
    student as student_model,
)
from backend.models.operator import Operator, OperatorRouteAccess
from backend.models.yard import Yard
from backend.models.associations import RouteDriverAssignment, StudentRunAssignment
from backend.utils import reports_generator
from backend.utils.operator_scope import get_operator_context
from backend.utils.operator_scope import get_operator_scoped_driver_or_404
from backend.utils.operator_scope import get_operator_scoped_route_or_404
from backend.utils.driver_workspace import _build_route_workspace
from backend.utils.planning_scope import accessible_route_filter, accessible_school_filter, accessible_student_filter
from backend.utils.route_driver_assignment import get_route_driver_name


templates = Jinja2Templates(directory="backend/templates")
router = APIRouter()


# -----------------------------------------------------------
# DASHBOARD PAGE
# -----------------------------------------------------------
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Renders admin dashboard summary with record counts."""
    counts = {
        "driver_count": (
            db.query(driver_model.Driver)
            .join(driver_model.Driver.yard)
            .filter(Yard.operator_id == operator.id)
            .count()
        ),
        "school_count": db.query(school_model.School).filter(accessible_school_filter(operator.id)).count(),
        "route_count": db.query(route_model.Route).filter(accessible_route_filter(operator.id)).count(),
        "student_count": db.query(student_model.Student).filter(accessible_student_filter(operator.id)).count(),
        "run_count": db.query(run_model.Run).join(route_model.Route, route_model.Route.id == run_model.Run.route_id).filter(accessible_route_filter(operator.id)).filter(run_model.Run.end_time.is_(None)).count(),
    }
    return templates.TemplateResponse(
        request,                                              # Request first (prevents deprecation warning)
        "dashboard.html",                                     # Template name
        counts,                                               # Context dict (request auto-injected)
    )


# -----------------------------------------------------------
# ROUTE REPORTS PAGE
# -----------------------------------------------------------
@router.get("/route_report/{route_id}", response_class=HTMLResponse)
def route_report(
    route_id: int,
    request: Request,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Shows route-specific reports summary including driver name and route details."""
    route_data = reports_generator.route_summary(db, route_id, operator_id=operator.id)
    if "error" in route_data:
        raise HTTPException(status_code=404, detail=route_data["error"])

    route = get_operator_scoped_route_or_404(
        db=db,
        route_id=route_id,
        operator_id=operator.id,
        required_access="read",
    )
    driver_name = get_route_driver_name(route) if route else None
    return templates.TemplateResponse(
        request,                                              # New Starlette signature: request first
        "route_report.html",                                  # Template name
        {
            "request": request,
            "route": route,
            "route_data": route_data,
            "driver_name": driver_name or "Unassigned",
        },
    )


# -----------------------------------------------------------
# - Driver run workspace page
# - Render route-first route, run, and run-review navigation
# -----------------------------------------------------------
@router.get("/driver_run/{driver_id}", response_class=HTMLResponse)
def driver_run_view(
    driver_id: int,
    request: Request,
    route_id: int | None = None,
    run_id: int | None = None,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Render the route-first driver workspace."""
    current_driver = get_operator_scoped_driver_or_404(
        db=db,
        driver_id=driver_id,
        operator_id=operator.id,
        detail="Driver not found",
    )

    # -----------------------------------------------------------
    # - Load active run
    # - Preserve live-run context without forcing navigation
    # -----------------------------------------------------------
    active_run = (
        db.query(run_model.Run)
        .options(joinedload(run_model.Run.route))
        .filter(run_model.Run.driver_id == driver_id)
        .join(route_model.Route, route_model.Route.id == run_model.Run.route_id)
        .filter(route_model.Route.operator_id == operator.id)
        .filter(run_model.Run.start_time.is_not(None))
        .filter(run_model.Run.end_time.is_(None))
        .first()
    )                                                        # Current active run for live workspace context

    # -----------------------------------------------------------
    # - Load assigned routes
    # - Preload route, run, stop, and rider details for the workspace
    # -----------------------------------------------------------
    available_routes = (
        db.query(route_model.Route)
        .options(
            joinedload(route_model.Route.bus),               # Current assigned bus display data
            joinedload(route_model.Route.active_bus),        # Current operational bus display data
            joinedload(route_model.Route.schools),           # Route header school list
            joinedload(route_model.Route.driver_assignments).joinedload(RouteDriverAssignment.driver),  # Assigned driver display
            joinedload(route_model.Route.runs).joinedload(run_model.Run.stops),  # Run -> stop hierarchy
            joinedload(route_model.Route.runs).joinedload(run_model.Run.student_assignments).joinedload(StudentRunAssignment.student).joinedload(student_model.Student.school),  # Run -> stop -> student hierarchy
            joinedload(route_model.Route.runs).joinedload(run_model.Run.student_assignments).joinedload(StudentRunAssignment.stop),  # Assignment stop grouping
        )
        .filter(route_model.Route.driver_assignments.any(and_(
            RouteDriverAssignment.driver_id == driver_id,
            RouteDriverAssignment.active.is_(True),
        )))
        .filter(
            (route_model.Route.operator_id == operator.id)
            | route_model.Route.operator_access.any(OperatorRouteAccess.operator_id == operator.id)
        )
        .order_by(route_model.Route.route_number.asc(), route_model.Route.id.asc())
        .all()
    )                                                        # Driver-selectable route workspace choices

    # -----------------------------------------------------------
    # - Resolve selected route
    # - Keep route selection explicit for flexible route-first browsing
    # -----------------------------------------------------------
    selected_route = None                                    # Keep route selection explicit for route-first browsing
    if route_id is not None:
        selected_route = next((route for route in available_routes if route.id == route_id), None)

    # -----------------------------------------------------------
    # - Build selected workspace
    # - Include selected run review state when present
    # -----------------------------------------------------------
    workspace = _build_route_workspace(selected_route, run_id) if selected_route else None
    active_pretrip = None                                    # Optional current selected-route pre-trip state for no-active-run UI
    if selected_route and workspace:
        route_bus = selected_route.active_bus or selected_route.bus
        if route_bus is not None:
            active_pretrip = (
                db.query(pretrip_model.PreTripInspection)
                .options(joinedload(pretrip_model.PreTripInspection.defects))
                .filter(pretrip_model.PreTripInspection.bus_id == route_bus.id)
                .filter(pretrip_model.PreTripInspection.inspection_date == datetime.now().date())
                .first()
            )                                                # Today's pre-trip for the selected route's active bus

            issue_description = None
            if active_pretrip and active_pretrip.defects:
                issue_description = "; ".join(
                    defect.description
                    for defect in active_pretrip.defects
                    if defect.description
                ) or None

            has_major_defect = bool(
                active_pretrip
                and any(defect.severity == "major" for defect in active_pretrip.defects)
            )
            workspace["pretrip_id"] = active_pretrip.id if active_pretrip else None
            workspace["pretrip_exists"] = active_pretrip is not None
            workspace["pretrip_fit_for_duty"] = (
                active_pretrip.fit_for_duty == "yes" if active_pretrip else None
            )
            workspace["pretrip_issue_description"] = issue_description
            workspace["pretrip_date"] = (
                active_pretrip.inspection_date.isoformat() if active_pretrip else None
            )
            workspace["pretrip_is_valid"] = bool(
                active_pretrip
                and active_pretrip.fit_for_duty == "yes"
                and not has_major_defect
            )
        else:
            workspace["pretrip_id"] = None
            workspace["pretrip_exists"] = False
            workspace["pretrip_fit_for_duty"] = None
            workspace["pretrip_issue_description"] = None
            workspace["pretrip_date"] = None
            workspace["pretrip_is_valid"] = False
    active_posttrip = None                                   # Optional initial post-trip state for active run UI
    if workspace and workspace.get("active_run"):
        active_posttrip = (
            db.query(posttrip_model.PostTripInspection)
            .filter(posttrip_model.PostTripInspection.run_id == workspace["active_run"]["id"])
            .first()
        )                                                    # Seed initial UI without changing post-trip business rules

    return templates.TemplateResponse(
        request,                                              # Request must be first
        "driver_run.html", {
            "request": request,
            "driver_id": driver_id,
            "driver_name": current_driver.name,
            "available_routes": available_routes,
            "selected_route_id": selected_route.id if selected_route else None,
            "workspace": workspace,
            "active_run_id": active_run.id if active_run else None,
            "active_route_id": active_run.route_id if active_run else None,
            "active_posttrip": active_posttrip,
            "selected_run_id": run_id,
            "today": datetime.now().date().isoformat(),
        }
    )


# -----------------------------------------------------------
# DISPATCH REPORTS SUMMARY PAGE
# -----------------------------------------------------------
@router.get("/summary_report", response_class=HTMLResponse)
def summary_report(
    request: Request,
    start: date = None,
    end: date = None,
    db: Session = Depends(get_db),
    operator: Operator = Depends(get_operator_context),
):
    """Shows dispatch reports summary between given dates."""
    end = end or date.today()
    start = start or end
    records = (
        db.query(dispatch_model.DispatchRecord)
        .join(driver_model.Driver, driver_model.Driver.id == dispatch_model.DispatchRecord.driver_id)
        .join(driver_model.Driver.yard)
        .filter(Yard.operator_id == operator.id)
        .filter(dispatch_model.DispatchRecord.work_date.between(start, end))
        .all()
    )
    total_drivers = len({r.driver_id for r in records})
    approved_days = sum(1 for r in records if r.approved)
    pending_days = len(records) - approved_days
    total_charter_hours = sum(float(r.charter_hours or 0) for r in records)

    return templates.TemplateResponse(
        request,                                              # Updated argument order
        "summary_report.html",                                # Template name
        {
            "request": request,
            "records": records,
            "start_date": start,
            "end_date": end,
            "total_drivers": total_drivers,
            "approved_days": approved_days,
            "pending_days": pending_days,
            "total_charter_hours": round(total_charter_hours, 2),
        },
    )

