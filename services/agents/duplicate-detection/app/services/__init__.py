"""Internal service layer for the Duplicate Detection Agent.

The service composes the existing repository, comparators, weighted scoring
engine and decision policy. The module itself remains transport-free; the
FastAPI edge lives in ``app/api/`` and calls ``check_detailed()``.

The consolidation service is additive: it persists complaints and applies the
unchanged M3 decision, without re-implementing scoring or policy.
"""

from app.services.consolidation_errors import ConsolidationError
from app.services.consolidation_service import ConsolidationService
from app.services.detection_service import DetectionResult, DuplicateDetectionService

__all__ = [
    "ConsolidationError",
    "ConsolidationService",
    "DetectionResult",
    "DuplicateDetectionService",
]
