"""Team agents after Incident Intelligence:

    Duplicate Detection (Yash Dadlani)  ->  Supervisor (Karanveer Singh Malhotra)
                                        ->  Sanitation Planning (Namrata Digarse)

Each step maps GeoSatya's saved report (and the earlier agents' real output)
into that agent's own contract, calls it, and stores the result. Results are
advisory: GeoSatya's report, location verification and dispatch are never
changed by them, and an agent that is down or rejects the input only leaves
its status visible for a supervisor to retry.

Tenancy: only public civic reports are sent to the shared duplicate store, so
an event's or organization's private incident can never be matched against,
or revealed to, another workspace.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from geosatya.models import IncidentRow, IntelligenceRow
from geosatya.platform_models import AgentRunRow
from geosatya.scope import same_workspace
from geosatya.services.common import Actor, audit
from geosatya.timeutil import iso, utcnow

SYSTEM = Actor("kavach-agents", "SYSTEM", "KAVACH team agents")
AGENTS = ("DUPLICATE_DETECTION", "SUPERVISOR", "SANITATION", "VERIFICATION")
OWNERS = {"DUPLICATE_DETECTION": "Yash Dadlani", "SUPERVISOR": "Karanveer Singh Malhotra", "SANITATION": "Namrata Digarse"}
P_TO_LEVEL = {"P1": "CRITICAL", "P2": "HIGH", "P3": "MEDIUM", "P4": "LOW"}
SEVERITY_FALLBACK = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
# GeoSatya / Intelligence type -> (Sanitation category, incident type, template)
SANITATION_TYPES = {
    "BIN_OVERFLOW": ("WASTE_OVERFLOW", "BIN_OVERFLOW", "BIN_OVERFLOW_RESPONSE"),
    "GARBAGE_PILE": ("WASTE_OVERFLOW", "GARBAGE_PILE", "GARBAGE_PILE_REMOVAL"),
    "WASTE_SPILL": ("HAZARD_OR_SPILL", "WASTE_SPILL", "SPILL_RESPONSE"),
    "PUBLIC_TOILET": ("FACILITY_CLEANING", "DIRTY_PUBLIC_TOILET", "PUBLIC_TOILET_CLEANING"),
}


def is_public(incident: IncidentRow) -> bool:
    return incident.workspace_id is None or incident.channel == "PUBLIC_PORTAL"


def agent_uuid(incident_id: str) -> str:
    """The Supervisor contract needs a UUID; derive a stable one from the reference."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kavach:{incident_id}"))


def _intel(session, incident) -> IntelligenceRow | None:
    row = session.get(IntelligenceRow, incident.incident_id)
    return row if row is not None and row.status == "COMPLETED" else None


def _save(session, incident, agent, status, *, result=None, request=None, error=None) -> AgentRunRow:
    row = session.get(AgentRunRow, (incident.incident_id, agent))
    if row is None:
        row = AgentRunRow(incident_id=incident.incident_id, agent=agent, attempts=0)
        session.add(row)
    row.status, row.result, row.request, row.error = status, result or {}, request or {}, (error or None) and str(error)[:200]
    row.attempts = (row.attempts or 0) + (status not in ("NOT_CONFIGURED", "NOT_APPLICABLE"))
    row.updated_at = utcnow()
    audit(session, SYSTEM, "AGENT_RESULT", incident.incident_id, agent=agent, status=status, error=row.error)
    return row


# ------------------------------------------------------- 1. duplicates
def duplicate_request(session, incident) -> dict:
    intel = _intel(session, incident)
    # The agent's documented mapping from Agent 1: incident_type unless UNKNOWN, else category.
    category = (intel.incident_type if intel and intel.incident_type and intel.incident_type != "UNKNOWN"
                else intel.category if intel and intel.category else incident.category.upper())
    return {"complaint_id": incident.incident_id, "description": f"{incident.title}. {incident.description}"[:4000],
            "category": category, "location": {"latitude": incident.latitude, "longitude": incident.longitude},
            "reported_at": iso(incident.created_at)}


def run_duplicate(session, client, incident) -> AgentRunRow:
    if client is None:
        return _save(session, incident, "DUPLICATE_DETECTION", "NOT_CONFIGURED")
    if not is_public(incident):
        return _save(session, incident, "DUPLICATE_DETECTION", "NOT_APPLICABLE",
                     error="Private workspace incident: not shared with the public duplicate store")
    body = duplicate_request(session, incident)
    r = client.post("/internal/v1/consolidation/complaints", body, idempotency_key=f"kavach-{incident.incident_id}")
    return _save(session, incident, "DUPLICATE_DETECTION", r.status, result=r.data, request=body, error=r.error)


# ------------------------------------------------------- 2. supervisor
def supervisor_request(session, incident, dup: AgentRunRow | None) -> dict:
    intel = _intel(session, incident)
    body = {
        "incident_id": agent_uuid(incident.incident_id),
        "description": f"{incident.title}. {incident.description}"[:4000],
        "category": (intel.category if intel and intel.category else incident.category.upper()),
        "incident_type": (intel.incident_type if intel and intel.incident_type else incident.category.upper()),
        "severity": (intel.severity if intel and intel.severity else "MEDIUM"),
        "reported_at": iso(incident.created_at),
        "location_metadata": {"latitude": incident.latitude, "longitude": incident.longitude,
                              "locality": incident.landmark or None,
                              # GeoSatya's location checks, not the agent's default of VERIFIED
                              "verification_status": "USER_SELECTED" if incident.location_source == "USER_SELECTED_PIN" else "DEVICE_GPS"},
    }
    if dup is not None and dup.status == "COMPLETED":
        d = dup.result
        matched = d.get("matched_incident_id")
        body["duplicate_check"] = {"decision": d.get("decision", "NEW"), "processing_status": "COMPLETED",
                                   "candidates": [{"matched_incident_id": agent_uuid(matched), "similarity_score": min(1.0, float(d.get("score") or 0)),
                                                   "reason_codes": d.get("reasons")}] if matched else []}
    return body


def run_supervisor(session, client, incident, dup) -> AgentRunRow:
    if client is None:
        return _save(session, incident, "SUPERVISOR", "NOT_CONFIGURED")
    body = supervisor_request(session, incident, dup)
    r = client.post("/api/v1/supervisor/evaluate", body)
    return _save(session, incident, "SUPERVISOR", r.status, result=r.data, request=body, error=r.error)


# ------------------------------------------------------- 3. sanitation
def sanitation_type(session, incident) -> tuple[str, str, str] | None:
    """Only waste incidents have a Sanitation template. The bin/pile split is a
    Kavach adapter rule on the report's words; it is shown as such."""
    intel = _intel(session, incident)
    kind = (intel.incident_type if intel else None) or ""
    text = f"{incident.title} {incident.description}".lower()
    if kind == "WASTE_SPILL" or ("spill" in text and incident.category in ("garbage", "safety_hazard")):
        return SANITATION_TYPES["WASTE_SPILL"]
    if incident.category == "public_toilet":
        return SANITATION_TYPES["PUBLIC_TOILET"]
    if incident.category in ("garbage", "sanitation", "waste_disposal") or kind in ("WASTE_OVERFLOW", "BIN_OVERFLOW", "GARBAGE_PILE", "GARBAGE_DUMP"):
        return SANITATION_TYPES["BIN_OVERFLOW" if re.search(r"\b(dust ?bin|bin|bins)\b", text) else "GARBAGE_PILE"]
    return None


def sanitation_request(session, incident, dup: AgentRunRow | None, sup: AgentRunRow | None, kind) -> dict:
    category, incident_type, template = kind
    started = incident.created_at
    dup_ok = dup is not None and dup.status == "COMPLETED"
    sup_ok = sup is not None and sup.status == "COMPLETED"
    sd = (sup.result or {}).get("supervisor_decision", {}) if sup_ok else {}
    department = sd.get("department") or "SANITATION"
    return {
        "event_id": f"kavach-{incident.incident_id}",
        "incident": {
            "incident_id": incident.incident_id, "complaint_id": incident.incident_id,
            "incident_summary": incident.title, "complaint_text": incident.description,
            "category": category, "incident_type": incident_type, "reported_at": iso(started),
            "location": {"latitude": incident.latitude, "longitude": incident.longitude, "source": incident.location_source,
                         "accuracy_m": incident.location_accuracy_m},
            "location_evidence_summary": {"status": "INCONCLUSIVE" if incident.location_flags else "CONSISTENT",
                                          "reason_codes": list(incident.location_flags or [])},
        },
        "duplicate_result": ({"processing_status": "COMPLETED", "decision": dup.result.get("decision", "NEW"),
                              "matched_incident_id": dup.result.get("matched_incident_id")} if dup_ok
                             else {"processing_status": "UNAVAILABLE", "decision": "REVIEW_REQUIRED"}),
        "supervisor_decision": {
            "decision_id": sd.get("decision_id") or f"KAVACH-NO-SUPERVISOR-{incident.incident_id}",
            # Without a Supervisor result nothing is claimed as approved.
            "decision_status": sd.get("decision_status") or "NEEDS_REVIEW",
            "department": "SANITATION" if "SANITATION" in department.upper() else department,
            "priority": P_TO_LEVEL.get(sd.get("priority"), "MEDIUM"),
            "duplicate_decision": dup.result.get("decision", "NEW") if dup_ok else "REVIEW_REQUIRED",
            "sla": {"started_at": iso(started), "response_due_at": sd.get("response_deadline"),
                    "resolution_due_at": sd.get("resolution_deadline")},
            "action_plan": {"template_id": template, "template_version": "1", "objective": incident.title},
        },
    }


def run_sanitation(session, client, incident, dup, sup) -> AgentRunRow:
    if client is None:
        return _save(session, incident, "SANITATION", "NOT_CONFIGURED")
    kind = sanitation_type(session, incident)
    if kind is None:
        return _save(session, incident, "SANITATION", "NOT_APPLICABLE", error="Not a waste / sanitation incident")
    body = sanitation_request(session, incident, dup, sup, kind)
    # Same input -> same key (a replay); changed upstream results -> a new plan request.
    digest = hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
    r = client.post("/api/v1/sanitation/plan", body, idempotency_key=f"kavach-san-{incident.incident_id}-{digest}")
    return _save(session, incident, "SANITATION", r.status, result=r.data, request=body, error=r.error)


def run_team_agents(session, agents, incident) -> dict:
    """Run all three in order. Each step uses only the previous agents' real output."""
    if agents is None:
        return {}
    rows = {}
    for name, step in (("DUPLICATE_DETECTION", lambda: run_duplicate(session, agents.duplicate, incident)),
                       ("SUPERVISOR", lambda: run_supervisor(session, agents.supervisor, incident, rows.get("DUPLICATE_DETECTION"))),
                       ("SANITATION", lambda: run_sanitation(session, agents.sanitation, incident, rows.get("DUPLICATE_DETECTION"),
                                                             rows.get("SUPERVISOR")))):
        try:
            rows[name] = step()
        except Exception as exc:  # a mapping bug must never lose or block a saved report
            rows[name] = _save(session, incident, name, "FAILED", error=f"ADAPTER_ERROR: {type(exc).__name__}")
    session.flush()
    return rows


# --------------------------------------------------------------- view
def agents_view(session, incident, actor: Actor) -> list[dict]:
    out = []
    for name in AGENTS:
        row = session.get(AgentRunRow, (incident.incident_id, name))
        item = {"agent": name, "owner": OWNERS[name], "status": row.status if row else "NOT_RUN",
                "error": row.error if row else None, "attempts": row.attempts if row else 0,
                "updated_at": iso(row.updated_at) if row else None}
        r = (row.result or {}) if row and row.status == "COMPLETED" else {}
        if name == "DUPLICATE_DETECTION" and r:
            matched = r.get("matched_incident_id") or (r.get("primary_complaint_id") if r.get("primary_complaint_id") != incident.incident_id else None)
            other = session.get(IncidentRow, matched) if matched else None
            visible = other is not None and (actor.role == "SUPERVISOR" and same_workspace(actor.workspace_id, other.workspace_id))
            item["summary"] = {"decision": r.get("decision"), "consolidation_status": r.get("consolidation_status"),
                               "score": r.get("score"), "reasons": r.get("reasons", []),
                               "matched_incident_id": matched if visible else None,
                               "matched_elsewhere": bool(matched and not visible),
                               "duplicates_in_group": r.get("active_duplicate_count")}
        elif name == "SUPERVISOR" and r:
            d, rt, au = r.get("supervisor_decision", {}), r.get("routing", {}), r.get("audit", {})
            item["summary"] = {"department": d.get("department"), "priority": d.get("priority"), "decision_status": d.get("decision_status"),
                               "ward": d.get("ward_or_route"), "response_deadline": d.get("response_deadline"),
                               "resolution_deadline": d.get("resolution_deadline"), "next_process": rt.get("next_process"),
                               "dispatch_eligible": rt.get("dispatch_eligible"), "reason_codes": au.get("reason_codes", []),
                               "rationale": au.get("rationale"), "mode": (r.get("llm_response") or {}).get("mode")}
        elif name == "SANITATION" and r:
            item["summary"] = {"plan_id": r.get("plan_id"), "planning_status": r.get("planning_status"),
                               "dispatch_eligible": r.get("dispatch_eligible"), "hold_reason_codes": r.get("hold_reason_codes", []),
                               "template": (r.get("template") or {}).get("template_id"), "objective": r.get("objective"),
                               "tasks": [{"sequence": t.get("sequence"), "title": t.get("title"), "minutes": (t.get("estimated_duration") or {}).get("minutes"),
                                          "resources": [x.get("resource_code") for x in t.get("required_resources", [])],
                                          "criteria": t.get("completion_criteria", [])} for t in r.get("tasks", [])],
                               "adapter_note": "Bin / pile / spill type chosen by a Kavach rule on the report's words."}
        elif name == "VERIFICATION" and r:
            req = row.request or {}
            item["summary"] = {"completion_id": req.get("completion_id"), "attempt": req.get("attempt"),
                               "verification_status": r.get("verification_status"), "score": r.get("verification_score"),
                               "confidence": r.get("verification_confidence"), "score_status": r.get("score_status"),
                               "remarks": r.get("remarks", []), "reason_codes": r.get("reason_codes", []),
                               "failed_requirements": r.get("failed_requirement_ids", []),
                               "alignment": (r.get("alignment_finding") or {}).get("status"),
                               "before_photos": req.get("before_photos"), "after_photos": req.get("after_photos"),
                               "gps_passed_on": req.get("gps_passed_on"),
                               "mode": "Offline (no AI vision)" if r.get("vision_model_version", "").startswith("mock") else r.get("vision_model_version")}
        out.append(item)
    return out



# ------------------------------------------------------- 4. verification
OWNERS["VERIFICATION"] = "MrBadDrip"


def verification_inputs(session, settings, categories, completion) -> tuple[dict, dict]:
    """GeoSatya completion -> the Verification agent's task and submission dicts."""
    from geosatya.models import EvidenceRow, MediaRow, TaskRow
    from geosatya.services.common import get_limits
    task = session.get(TaskRow, completion.task_id)
    incident = session.get(IncidentRow, completion.incident_id)
    requirements = requirements_for(session, categories, incident)
    agent_task = {"task_id": task.task_id,
                  "requirements": [{k: r[k] for k in ("requirement_id", "label", "mandatory", "target_observation")} for r in requirements],
                  "site": {"latitude": task.target_latitude, "longitude": task.target_longitude,
                           "tolerance_m": float(get_limits(session, settings)["geofence_radius_m"])}}
    # The worker's own before photo (taken at the spot) is the best "before"; else the citizen's report photo.
    from sqlalchemy import select
    before = session.scalars(select(MediaRow).where(MediaRow.task_id == task.task_id, MediaRow.role == "BEFORE")
                             .order_by(MediaRow.received_at.desc())).all() or         session.scalars(select_media(MediaRow, incident.incident_id, "REPORT")).all()
    after = session.get(MediaRow, completion.media_id) if completion.media_id else None
    evidence = [{"evidence_id": m.media_id, "type": "BEFORE_IMAGE", "status": "READY", "task_id": task.task_id,
                 "storage_path": m.storage_key, "role": m.role} for m in before[:1]]
    if after is not None:
        evidence.append({"evidence_id": after.media_id, "type": "AFTER_IMAGE", "status": "READY", "task_id": task.task_id,
                         "storage_path": after.storage_key})
    fix = session.get(EvidenceRow, completion.device_evidence_id) if completion.device_evidence_id else None
    location = None  # no usable fix -> the agent says UNAVAILABLE; a SIMULATED fix is never passed as GPS
    if fix is not None and fix.available and fix.mode == "LIVE" and fix.latitude is not None:
        location = {"latitude": fix.latitude, "longitude": fix.longitude, "accuracy_m": fix.accuracy_m or 0.0,
                    "timestamp_valid": fix.received_at is not None}
    from geosatya.platform_models import TaskChecklistRow
    ticked = session.get(TaskChecklistRow, (task.task_id, completion.attempt))
    valid = {r["requirement_id"] for r in requirements}
    # Only ticked steps are sent (as True); an unticked step stays UNKNOWN, never False.
    checklist = {rid: True for rid in (ticked.completed if ticked else []) if rid in valid}
    submission = {"submission_id": completion.completion_id, "task_id": task.task_id, "evidence": evidence,
                  "location": location, "checklist": checklist}
    return agent_task, submission


def requirements_for(session, categories, incident) -> list[dict]:
    """The steps for a job: the Sanitation plan's tasks if one exists, else the
    category's worker instructions. Shared by the worker checklist and Verification."""
    san = session.get(AgentRunRow, (incident.incident_id, "SANITATION"))
    plan_tasks = (san.result or {}).get("tasks") if san is not None and san.status == "COMPLETED" else None
    # target_observation is always set explicitly: the agent gives the bare ids STEP-01..03 built-in
    # waste meanings, which must never attach to unrelated steps. None = no visual check for that step.
    if plan_tasks:
        return [{"requirement_id": t.get("task_code") or f"SAN-{t.get('sequence')}", "label": t.get("title") or t.get("task_name"),
                 "mandatory": True, "source": "SANITATION_PLAN", "target_observation": SANITATION_OBSERVATIONS.get(t.get("task_code"))}
                for t in plan_tasks if t.get("title") or t.get("task_name")]
    steps = (categories.get(incident.category) or {}).get("instructions") or []
    return [{"requirement_id": f"{incident.category.upper()}-{i:02d}", "label": st, "mandatory": True, "source": "CATEGORY",
             "target_observation": None} for i, st in enumerate(steps, 1)]


# What the Verification agent's vision can confirm after each Sanitation step (its own vocabulary).
SANITATION_OBSERVATIONS = {"REMOVE_WASTE": "scattered_waste", "CLEAN_AREA": "scattered_waste", "CHECK_PATH_CLEAR": "path_obstructed"}


def select_media(MediaRow, incident_id, role):
    from sqlalchemy import select
    return select(MediaRow).where(MediaRow.incident_id == incident_id, MediaRow.role == role).order_by(MediaRow.media_id)


def run_verification(session, settings, categories, verifier, completion) -> AgentRunRow:
    incident = session.get(IncidentRow, completion.incident_id)
    if verifier is None:
        return _save(session, incident, "VERIFICATION", "NOT_CONFIGURED")
    try:
        agent_task, submission = verification_inputs(session, settings, categories, completion)
        result = verifier.verify(agent_task, submission)
    except Exception as exc:  # the agent or the mapping failing never affects GeoSatya's own verdict
        return _save(session, incident, "VERIFICATION", "FAILED", error=f"{type(exc).__name__}: {exc}"[:200])
    request = {"completion_id": completion.completion_id, "attempt": completion.attempt,
               "before_photos": sum(e["type"] == "BEFORE_IMAGE" for e in submission["evidence"]),
               "after_photos": sum(e["type"] == "AFTER_IMAGE" for e in submission["evidence"]),
               "gps_passed_on": submission["location"] is not None, "requirements": [r["label"] for r in agent_task["requirements"]],
               "before_source": ("WORKER" if any(e["type"] == "BEFORE_IMAGE" and e.get("role") == "BEFORE" for e in submission["evidence"])
                                 else "REPORT" if submission["evidence"] and submission["evidence"][0]["type"] == "BEFORE_IMAGE" else None),
               "steps_ticked": len(submission["checklist"]), "steps_total": len(agent_task["requirements"])}
    return _save(session, incident, "VERIFICATION", "COMPLETED", result=result, request=request)
