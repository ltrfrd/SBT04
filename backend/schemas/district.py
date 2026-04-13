from pydantic import BaseModel, ConfigDict


class DistrictCreate(BaseModel):
    name: str
    contact_info: str | None = None


class DistrictOut(DistrictCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class DistrictSummaryOut(BaseModel):
    district_id: int
    schools_count: int
    routes_count: int
    students_count: int
