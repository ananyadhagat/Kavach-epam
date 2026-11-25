"""Incident Intelligence step: send a saved report to the agent and keep its
output next to (never instead of) what the citizen submitted."""

from __future__ import annotations

from sqlalchemy import select

from geosatya.models import EvidenceRow, IncidentRow, IntelligenceRow, MediaRow
from geosatya.services.common import Actor, audit
from geosatya.timeutil import iso, utcnow

SYSTEM = Actor("incident-intelligence", "SYSTEM", "Incident Intelligence")
# The agent's severity becomes the dispatch priority. Without it, NORMAL.
PRIORITY_OF_SEVERITY = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}


def request_id_for(incident: IncidentRow) -> str:
    """Stable per incident, so a retry is recognised by the agent as the same request."""
    return f"geosatya-{incident.incident_id}"


def priority_of(intel: IntelligenceRow | None) -> str:
    if intel is None or intel.status != "COMPLETED":
        return "NORMAL"
    return PRIORITY_OF_SEVERITY.get(intel.severity or "", "NORMAL")


def build_request(session, storage, incident: IncidentRow) -> tuple[dict, list[tuple[str, bytes, str]]]:
    text = f"{incident.title}. {incident.description}"
    if incident.asset_identifier:
        text += f" (asset {incident.asset_identifier})"
    # GeoSatya's locked incident location is the reported incident location.
    fields = {"complaint_text": text[:5000], "selected_latitude": incident.latitude,
              "selected_longitude": incident.longitude}
    if incident.location_source == "USER_SELECTED_PIN":
        # The pin is the incident location; a device fix, if any, is a separate source.
        device = session.scalar(select(EvidenceRow).where(
            EvidenceRow.incident_id == incident.incident_id, EvidenceRow.task_id.is_(None),
            EvidenceRow.source_type == "DEVICE_GEOLOCATION", EvidenceRow.available.is_(True)))
        if device is not None:
            fields.update(device_latitude=device.latitude, device_longitude=device.longitude,
                          device_accuracy_meters=device.accuracy_m, device_observed_at=iso(device.observed_at))
    images = []
    for m in session.scalars(select(MediaRow).where(MediaRow.incident_id == incident.incident_id,
                                                    MediaRow.role == "REPORT").order_by(MediaRow.received_at)):
        try:
            images.append((f"{m.media_id}.{m.mime_type.split('/')[-1]}", storage.read(m.storage_key), m.mime_type))
        except Exception:  # noqa: BLE001 - a missing file must not block the analysis of the text
            continue
    return fields, images[:4]


def run_intelligence(session, storage, client, incident: IncidentRow) -> IntelligenceRow:
    """Analyse the incident. Never raises for agent failures: the outcome is
    recorded on the row (UNAVAILABLE / FAILED / CONFLICT) and can be retried."""
    row = session.get(IntelligenceRow, incident.incident_id)
    if row is None:
        row = IntelligenceRow(incident_id=incident.incident_id, status="PENDING", request_id=request_id_for(incident),
                              attempts=0, severity_rule_matches=[], clarification_questions=[], missing_information=[])
        session.add(row)
    if row.status == "COMPLETED":
        return row
    if client is None:
        row.status, row.last_error = "NOT_CONFIGURED", None
        session.flush()
        return row

    row.attempts += 1
    row.requested_at = utcnow()
    fields, images = build_request(session, storage, incident)
    result = client.analyse(row.request_id, fields, images)
    row.status, row.last_error = result.status, result.error
    if result.status == "COMPLETED":
        rec = result.record or {}
        loc = (rec.get("location_evidence_summary") or {}).get("check") or {}
        row.external_incident_id = rec.get("incident_id")
        row.category, row.incident_type = rec.get("category"), rec.get("incident_type")
        row.severity, row.severity_reason = rec.get("severity_recommendation"), (rec.get("severity_reason") or "")[:1000]
        row.severity_rule_matches = list(rec.get("severity_rule_matches") or [])
        row.summary = (rec.get("incident_summary") or "")[:600] or None
        row.needs_clarification = bool(rec.get("needs_clarification"))
        row.clarification_questions = list(rec.get("clarification_questions") or [])[:5]
        row.missing_information = list(rec.get("missing_information") or [])[:20]
        row.location_check_status = loc.get("status")
        row.model_info = (rec.get("prompt_version") or "")[:80] or None
        row.completed_at = utcnow()
    audit(session, SYSTEM, "INTELLIGENCE_" + result.status, incident.incident_id, attempt=row.attempts,
          error=result.error, severity=row.severity, category=row.category, incident_type=row.incident_type)
    session.flush()
    return row
