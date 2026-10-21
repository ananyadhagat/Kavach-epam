from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..contracts.v1 import ContractModel, FieldWorkerCompletion


class VerificationRequest(ContractModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str | None = Field(default=None, min_length=3, max_length=80)
    field_worker_completion: FieldWorkerCompletion | None = None

    @model_validator(mode="after")
    def requires_submission_reference(self):
        completion_submission_id = self.field_worker_completion.submission_id if self.field_worker_completion else None
        if not self.submission_id and not completion_submission_id:
            raise ValueError("submission_id is required for verification")
        if self.submission_id and completion_submission_id and self.submission_id != completion_submission_id:
            raise ValueError("submission_id must match the Field Worker completion")
        return self

    @property
    def effective_submission_id(self) -> str:
        if self.submission_id:
            return self.submission_id
        assert self.field_worker_completion and self.field_worker_completion.submission_id
        return self.field_worker_completion.submission_id
