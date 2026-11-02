from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChecklistStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class ChecklistStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    task_id: str
    assigned_worker_id: str | None = None
    status: ChecklistStatus = ChecklistStatus.PENDING
    note: str | None = Field(default=None, max_length=500)
    updated_at: datetime = Field(default_factory=utc_now)
    # Set when the step last became COMPLETED; None otherwise.
    completed_at: datetime | None = None


class ChecklistStepUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ChecklistStatus
    note: str | None = Field(default=None, max_length=500)