"""HTTP edge for the M3 duplicate-detection contract.

The layer validates the Agent 1 handoff payload, delegates to the
transport-free :class:`~app.services.detection_service.DuplicateDetectionService`,
and maps its decision to the Agent 3 response shape. It contains no similarity
maths, no scoring formula and no second decision implementation.
"""

from app.api.app import create_app
from app.api.mapper import to_m3_response

__all__ = ["create_app", "to_m3_response"]
