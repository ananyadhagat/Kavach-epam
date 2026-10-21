from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceType(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class EvidenceStatus(str, Enum):
    STORED = "STORED"


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    task_id: str
    worker_id: str

    evidence_type: EvidenceType
    storage_key: str

    original_filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)

    status: EvidenceStatus = EvidenceStatus.STORED
    uploaded_at: datetime = Field(default_factory=utc_now)


class EvidenceUploadResponse(BaseModel):
    evidence: EvidenceRecord
    duplicate: bool = False
    message: str