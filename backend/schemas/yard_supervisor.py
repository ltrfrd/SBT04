from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class YardSupervisorBase(BaseModel):
    yard_id: int
    name: str
    email: EmailStr
    phone: Optional[str] = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name is required")
        return normalized


class YardSupervisorCreate(YardSupervisorBase):
    model_config = ConfigDict(extra="forbid")


class YardSupervisorUpdate(BaseModel):
    yard_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("name is required")
        return normalized


class YardSupervisorOut(YardSupervisorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
