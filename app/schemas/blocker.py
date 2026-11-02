from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.worker_task import TaskStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Format only. The allowed codes come from the BLOCKER_REASON_CODES setting
# because no agreed list exists yet.
ReasonCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50,
                      pattern=r"^[A-Z][A-Z0-9_]*$"),
]

Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


class BlockerStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class BlockerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: ReasonCode
    # Limited to 500 so it fits the note of a blocked checklist step.
    description: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]
    # Optional checklist step that cannot be completed; it is set BLOCKED.
    step_id: str | None = Field(default=None, min_length=1, max_length=100)


class BlockerResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_note: Text | None = None


class BlockerReasonCodeOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str


class BlockerReasonCodesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_codes: list[BlockerReasonCodeOption]


class BlockerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocker_id: str
    task_id: str
    worker_id: str
    step_id: str | None = None
    reason_code: str
    description: str
    status: BlockerStatus = BlockerStatus.OPEN
    # The task returns to this status when the blocker is resolved.
    previous_status: TaskStatus
    reported_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
