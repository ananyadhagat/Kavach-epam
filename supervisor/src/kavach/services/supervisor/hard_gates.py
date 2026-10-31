# src/kavach/services/supervisor/hard_gates.py
from __future__ import annotations

import os
from dataclasses import dataclass, field

from kavach.schemas.supervisor import SupervisorIncidentInput
from kavach.services.supervisor.reference_data import (
    DUPLICATE_CONFLICT_THRESHOLD,
    DUPLICATE_OK_STATUSES,
)


@dataclass(frozen=True)
class HardGateResult:
    passed: bool
    reason_codes: list[str] = field(default_factory=list)
    rationale: str = ""
    notes: list[str] = field(default_factory=list)  # non-blocking codes carried into the audit


def require_duplicate_check() -> bool:
    """
    Phase 1 default: duplicate_check is OPTIONAL (the input is just an incident report).
    Set KAVACH_REQUIRE_DUPLICATE_CHECK=true once process 2.0 feeds this agent.
    A duplicate_check that IS supplied is always enforced.
    """
    return os.getenv("KAVACH_REQUIRE_DUPLICATE_CHECK", "false").strip().lower() in {"1", "true", "yes"}


def _duplicate_gate(incident: SupervisorIncidentInput) -> tuple[list[str], list[str]]:
    """Returns (blocking_reasons, notes). A failed retrieval is never treated as NEW."""
    dc = incident.duplicate_check
    if dc is None:
        if require_duplicate_check():
            return ["DUPLICATE_CHECK_MISSING"], []
        return [], ["DUPLICATE_CHECK_NOT_PROVIDED"]

    status = dc.processing_status.strip().upper()
    decision = dc.decision.strip().upper()

    if status not in DUPLICATE_OK_STATUSES:
        return ["DUPLICATE_CHECK_NOT_COMPLETED"], []
    if decision == "NEW":
        if any(c.similarity_score >= DUPLICATE_CONFLICT_THRESHOLD for c in dc.candidates):
            return ["DUPLICATE_CONFLICT"], []
        return [], []
    if decision == "DUPLICATE":
        return ["DUPLICATE_CONFIRMED_NO_NEW_DISPATCH"], []
    if decision == "REVIEW_REQUIRED":
        return ["DUPLICATE_REVIEW_REQUIRED"], []
    return ["DUPLICATE_CHECK_INVALID_DECISION"], []


def run_hard_gates(incident: SupervisorIncidentInput) -> HardGateResult:
    """Deterministic gates executed BEFORE Gemini. Any failure forces NEEDS_REVIEW."""
    reasons, notes = _duplicate_gate(incident)

    if incident.resolved_priority is None:
        reasons.append("UNRECOGNIZED_PRIORITY_OR_SEVERITY")

    if not incident.description or not incident.description.strip():
        reasons.append("MISSING_INCIDENT_DESCRIPTION")

    loc = incident.location_metadata
    ver_status = (loc.verification_status or "VERIFIED").strip().upper()
    if ver_status in {"CONFLICT", "FAILED", "LOCATION_CONFLICT", "SPOOFED"}:
        reasons.append("LOCATION_VERIFICATION_CONFLICT")

    has_coords = loc.latitude is not None and loc.longitude is not None
    has_locality = bool(loc.locality and loc.locality.strip()) or bool(
        loc.ward_hint and loc.ward_hint.strip()
    )
    if not has_coords and not has_locality:
        reasons.append("MISSING_VERIFIABLE_LOCATION")

    if reasons:
        return HardGateResult(
            passed=False,
            reason_codes=reasons,
            notes=notes,
            rationale=(
                f"Pre-evaluation hard gate failed ({', '.join(reasons)}); "
                "routed to review without LLM evaluation."
            ),
        )
    return HardGateResult(passed=True, notes=notes)
