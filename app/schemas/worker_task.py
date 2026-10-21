from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)


TaskId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]

WorkerId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TaskAction(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"


class TaskLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    address: str = Field(min_length=1, max_length=500)


class ChecklistDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=250)
    required: bool = True


class WorkerTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: TaskId
    incident_id: str
    assigned_worker_id: WorkerId

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)

    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.ASSIGNED

    location: TaskLocation
    checklist: list[ChecklistDefinition] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    arrival_location_event_id: str | None = None
    completion_location_event_id: str | None = None
    completion_submission_id: str | None = None


class TaskActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: TaskAction
    reason: str | None = Field(default=None, max_length=500)


class WorkerTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task: WorkerTask
    message: str