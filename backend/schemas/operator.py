from pydantic import BaseModel, ConfigDict, field_validator


class OperatorUpdate(BaseModel):
    name: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name is required")
        return normalized


class OperatorOut(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)
