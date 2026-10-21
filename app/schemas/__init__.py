"""Pydantic request/response schemas for the Duplicate Detection Agent.

These models are the transport-free contracts agreed in Phase 1
(``docs/duplicate_detection/api_contract.md``). They are re-exported here for
convenient imports.
"""

from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import (
    Decision,
    DuplicateDetectionResponse,
    SignalResult,
    SignalStatus,
)

__all__ = [
    "Complaint",
    "Location",
    "Decision",
    "SignalStatus",
    "SignalResult",
    "DuplicateDetectionResponse",
]
