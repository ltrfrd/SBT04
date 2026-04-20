from .district import District
from .operator import Operator, OperatorRouteAccess
from .yard import Yard
from .yard_supervisor import YardSupervisor
from .dispatcher import Dispatcher
from .driver import Driver
from .bus import Bus
from .school import School
from .student import Student
from .route import Route
from .stop import Stop, StopType
from .run import Run
from .run_verification import RunVerification
from .dispatch import DispatchRecord
from .run_event import RunEvent
from .associations import route_schools, StudentRunAssignment, RouteDriverAssignment
from .student_bus_absence import StudentBusAbsence, StudentBusAbsenceSource
from .school_attendance_verification import SchoolAttendanceVerification  # New school confirmation model
from .pretrip import PreTripInspection, PreTripDefect
from .posttrip import PostTripInspection, PostTripPhoto
from .dispatch_alert import DispatchAlert
__all__ = [
    "Driver",
    "District",
    "Operator",
    "OperatorRouteAccess",
    "Yard",
    "YardSupervisor",
    "Dispatcher",
    "Bus",
    "School",
    "Student",
    "Route",
    "Stop",
    "StopType",
    "Run",
    "RunVerification",
    "DispatchRecord",
    "route_schools",
    "StudentRunAssignment",
    "RouteDriverAssignment",
    "RunEvent",
    "StudentBusAbsence",
    "StudentBusAbsenceSource",
    "SchoolAttendanceVerification",  # Export new model
    "PreTripInspection",
    "PreTripDefect",
    "PostTripInspection",
    "PostTripPhoto",
    "DispatchAlert",
]

