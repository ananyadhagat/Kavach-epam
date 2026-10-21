"""Agent 1 -> Agent 2 (Duplicate Detection) handoff.

`build_duplicate_detection_request()` maps a StructuredIncidentRecord onto the request shape shown in
the Duplicate Detection technical design (section 5, "Illustrative input JSON"):

    complaint_id, description, category, location{facility_id, location_id, latitude, longitude},
    reported_at, image_hash

Mapping decisions (PROVISIONAL until the Agent 1 <-> Agent 2 contract is signed off):
- complaint_id  <- incident_id
- description   <- complaint_text (citizen's original words); falls back to incident_summary for old records
- category      <- incident_type when known (Agent 2's example uses "WASTE_OVERFLOW"), else category
- location      <- reported_incident_location only (USER_SELECTED_PIN / FACILITY_REFERENCE).
                   Device GPS is NOT sent as the incident location (the reporter may be remote).
                   facility_id / location_id are null until a facility lookup exists.
- reported_at   <- submitted_at (server receipt time, tz-aware), else created_at
- image_hash    <- perceptual_hash (dHash) of the first accepted image, else null
Extra keys under "kavach_agent1" carry Agent 1 context; Agent 2 may ignore them.

`DuplicateDetectionClient` POSTs that payload to KAVACH_DUPLICATE_DETECTION_URL using only the
standard library. It is optional: if the URL is not configured, no call is made.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from kavach.schemas.incident_intelligence import IncidentType, StructuredIncidentRecord

logger = logging.getLogger(__name__)

HANDOFF_CONTRACT_VERSION = "a1-to-a2-draft-1"


def build_duplicate_detection_request(record: StructuredIncidentRecord) -> dict:
    loc = record.reported_incident_location
    first_hash = next((m.perceptual_hash for m in record.media if m.accepted and m.perceptual_hash), None)
    category = (record.incident_type.value if record.incident_type != IncidentType.UNKNOWN
                else record.category.value)
    reported_at = record.submitted_at or record.created_at
    return {
        "complaint_id": record.incident_id,
        "description": record.complaint_text or record.incident_summary,
        "category": category,
        "location": {
            "facility_id": None,
            "location_id": None,
            "latitude": loc.latitude if loc else None,
            "longitude": loc.longitude if loc else None,
        },
        "reported_at": reported_at.isoformat(),
        "image_hash": first_hash,
        "kavach_agent1": {
            "contract_version": HANDOFF_CONTRACT_VERSION,
            "request_id": record.request_id,
            "category": record.category.value,
            "incident_type": record.incident_type.value,
            "incident_summary": record.incident_summary,
            "severity_recommendation": record.severity_recommendation.value,
            "location_source": (record.location_evidence_summary.reported_location_source.value
                                if record.location_evidence_summary.reported_location_source else None),
            "location_check_status": record.location_evidence_summary.check.status.value,
            "image_sha256": [m.sha256 for m in record.media if m.accepted and m.sha256],
            "image_perceptual_hashes": [m.perceptual_hash for m in record.media if m.accepted and m.perceptual_hash],
            "needs_clarification": record.needs_clarification,
        },
    }


@dataclass
class HandoffResult:
    delivered: bool
    status_code: int | None = None
    error: str | None = None
    response: dict | None = None


class DuplicateDetectionClient:
    def __init__(self, url: str, timeout_seconds: float = 10.0):
        self.url = url
        self.timeout_seconds = timeout_seconds

    def send(self, record: StructuredIncidentRecord) -> HandoffResult:
        body = json.dumps(build_duplicate_detection_request(record)).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310 - configured URL
                raw = resp.read()
                try:
                    parsed = json.loads(raw) if raw else None
                except ValueError:
                    parsed = None
                return HandoffResult(True, resp.status, response=parsed if isinstance(parsed, dict) else None)
        except urllib.error.HTTPError as exc:
            return HandoffResult(False, exc.code, error=f"HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - network/timeout: record stays saved, caller can retry
            return HandoffResult(False, None, error=type(exc).__name__)
