# backend/schemas/run.py
from pydantic import BaseModel, ConfigDict
from enum import Enum
from typing import Optional
from datetime import datetime


class RunType(str, Enum):
    AM = "AM"
    MIDDAY = "MIDDAY"
    PM = "PM"
    EXTRA = "EXTRA"


class RunStart(BaseModel):
    driver_id: int
    route_id: int
    run_type: RunType


class RunOut(BaseModel):
    id: int
    driver_id: int
    route_id: int
    run_type: RunType
    start_time: datetime
    end_time: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
