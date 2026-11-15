"""HTTP clients for the team's downstream KAVACH agents. Each agent is its own
service (copied unchanged into services/agents/<name>, see ORIGIN.md there).

Contracts used (read from each agent's own code):
  Duplicate Detection  POST /internal/v1/consolidation/complaints   (Idempotency-Key required)
      body {complaint_id, description, category, location{latitude,longitude}, reported_at}
      -> {decision NEW|DUPLICATE|REVIEW_REQUIRED, consolidation_status, group_id,
          primary_complaint_id, matched_incident_id, score, reasons, ...}
  Supervisor           POST /api/v1/supervisor/evaluate
      body SupervisorIncidentInput (incident_id UUID, description, category, incident_type,
           severity, location_metadata, duplicate_check)
      -> {supervisor_decision{department, priority P1-P4, decision_status, deadlines},
          routing{next_process, dispatch_eligible}, audit{reason_codes, rationale}}
  Sanitation Planning  POST /api/v1/sanitation/plan   (Idempotency-Key)
      body {event_id, incident, duplicate_result, supervisor_decision}
      -> SanitationPlanResult {plan_id, planning_status, dispatch_eligible, tasks[], ...}
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class AgentResult:
    status: str  # COMPLETED | UNAVAILABLE | FAILED | REJECTED
    data: dict | None = None
    error: str | None = None


class AgentClient:
    def __init__(self, name: str, base_url: str, timeout_s: float, transport: httpx.BaseTransport | None = None) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport  # tests inject a mock transport

    def post(self, path: str, body: dict, *, idempotency_key: str | None = None) -> AgentResult:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
                r = client.post(f"{self.base_url}{path}", json=body, headers=headers)
        except httpx.TimeoutException:
            return AgentResult("UNAVAILABLE", error="TIMEOUT")
        except httpx.HTTPError as exc:
            return AgentResult("UNAVAILABLE", error=type(exc).__name__)
        if r.status_code in (200, 201):
            try:
                data = r.json()
            except ValueError:
                return AgentResult("FAILED", error="INVALID_JSON_RESPONSE")
            return AgentResult("COMPLETED", data=data) if isinstance(data, dict) else AgentResult("FAILED", error="UNEXPECTED_RESPONSE")
        code = _error_code(r)
        if r.status_code in (429, 503, 504) or r.status_code >= 500:
            return AgentResult("UNAVAILABLE", error=code or f"HTTP_{r.status_code}")
        return AgentResult("REJECTED", error=code or f"HTTP_{r.status_code}")

    def healthy(self, path: str = "/health") -> bool:
        try:
            with httpx.Client(timeout=2.0, transport=self._transport) as client:
                return client.get(f"{self.base_url}{path}").status_code < 500
        except httpx.HTTPError:
            return False


def _error_code(r: httpx.Response) -> str | None:
    try:
        detail = r.json().get("detail")
    except (ValueError, AttributeError):
        return None
    if isinstance(detail, dict):
        return str(detail.get("code") or detail.get("reason_code") or detail.get("error") or "")[:80] or None
    return None


@dataclass
class TeamAgents:
    duplicate: AgentClient | None = None
    supervisor: AgentClient | None = None
    sanitation: AgentClient | None = None


def make_team_agents(settings) -> TeamAgents:
    t = settings.agents_timeout_s
    mk = lambda name, url: AgentClient(name, url, t) if url else None  # noqa: E731
    return TeamAgents(duplicate=mk("duplicate_detection", settings.duplicate_detection_url),
                      supervisor=mk("supervisor", settings.supervisor_agent_url),
                      sanitation=mk("sanitation", settings.sanitation_agent_url))
