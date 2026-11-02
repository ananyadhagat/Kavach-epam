from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompletionClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[str] = Field(min_length=2)
    completion_location_event_id: str | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_unique_references(self):
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Duplicate evidence IDs are not allowed")

        return self


class CompletionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: str
    task_id: str
    worker_id: str

    checklist_step_ids: list[str]
    evidence_ids: list[str]
    completion_location_event_id: str | None = None
    notes: str | None = None

    submitted_at: datetime = Field(default_factory=utc_now)
    # Same value as the task status. Verification happens downstream.
    status: str = "COMPLETION_SUBMITTED"