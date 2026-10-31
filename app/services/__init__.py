"""Internal service layer for the Duplicate Detection Agent.

The service composes the existing repository, comparators, weighted scoring
engine and decision policy. It is deliberately transport-free: the HTTP/API
layer is a separate, deferred integration.
"""

from app.services.detection_service import DuplicateDetectionService

__all__ = ["DuplicateDetectionService"]
