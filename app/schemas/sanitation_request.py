from datetime import datetime, timezone
from typing import Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.incident_contract import IncidentRecord
from app.schemas.duplicate_contract import DuplicateResult
from app.schemas.supervisor_contract import SupervisorDecision


class ReplanContext(BaseModel):
    """Context provided when a revision/replanning request is issued."""

    model_config = ConfigDict(extra="ignore")

    previous_plan_id: str = Field(min_length=1)
    replan_reason: str = Field(min_length=1)


class SanitationPlanRequest(BaseModel):
    """Canonical Module 04 input envelope."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0.0"] = "1.0.0"
    event_id: str = Field(min_length=1)
    incident: IncidentRecord
    duplicate_result: DuplicateResult
    supervisor_decision: SupervisorDecision
    replan_context: ReplanContext | None = None


class SanitationRequest(BaseModel):
    """Legacy versioned request for backward compatibility."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0.0"]
    request_id: Union[UUID, str]
    event_id: str = Field(min_length=1)
    complaint_id: str = Field(min_length=1)
    description: str = Field(min_length=5)
    location: str = Field(min_length=1)
    priority: Literal["low", "medium", "high", "critical"]
    estimated_waste_kg: float | None = Field(default=None, ge=0)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include a timezone.")
        return value

    @field_validator("requested_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)
