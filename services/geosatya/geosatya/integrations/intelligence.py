"""HTTP client for the KAVACH Incident Intelligence agent.

The agent is a separate FastAPI service (branch `incident-intelligence-agent`,
`POST /api/v1/incidents`, multipart). GeoSatya calls it after a report has
been saved, so an unavailable agent can never lose a report.

Contract used (see that branch's README and src/kavach/api/routes/incidents.py):
  headers  X-Request-ID   stable per GeoSatya incident -> safe retries
           (same id + same payload returns the stored record; a different
           payload returns 409 REQUEST_ID_REUSED)
  form     complaint_text, selected_latitude/longitude, device_latitude/
           longitude, device_accuracy_meters, device_observed_at, images[]
  201      StructuredIncidentRecord (JSON)
  503/429  analysis temporarily unavailable (retryable)
  502      model rejected the request / output invalid
  409      request id reused with a different payload
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class IntelligenceResult:
    status: str  # COMPLETED | UNAVAILABLE | FAILED | CONFLICT
    record: dict | None = None
    error: str | None = None


class IntelligenceClient:
    def __init__(self, base_url: str, timeout_s: float = 8.0, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport  # tests inject a mock transport

    def analyse(self, request_id: str, fields: dict, images: list[tuple[str, bytes, str]]) -> IntelligenceResult:
        files = [("images", (name, data, mime)) for name, data, mime in images]
        data = {k: str(v) for k, v in fields.items() if v is not None}
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
                r = client.post(f"{self.base_url}/api/v1/incidents", data=data, files=files or None,
                                headers={"X-Request-ID": request_id})
        except httpx.TimeoutException:
            return IntelligenceResult("UNAVAILABLE", error="TIMEOUT")
        except httpx.HTTPError as exc:
            return IntelligenceResult("UNAVAILABLE", error=type(exc).__name__)
        if r.status_code in (200, 201):
            try:
                return IntelligenceResult("COMPLETED", record=r.json())
            except ValueError:
                return IntelligenceResult("FAILED", error="INVALID_JSON_RESPONSE")
        code = _error_code(r)
        if r.status_code == 409:
            return IntelligenceResult("CONFLICT", error=code or "REQUEST_ID_REUSED")
        if r.status_code == 429 or (r.status_code >= 500 and r.status_code != 502):
            return IntelligenceResult("UNAVAILABLE", error=code or f"HTTP_{r.status_code}")
        return IntelligenceResult("FAILED", error=code or f"HTTP_{r.status_code}")


def _error_code(r: httpx.Response) -> str | None:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return None
    return detail.get("code") if isinstance(detail, dict) else None
