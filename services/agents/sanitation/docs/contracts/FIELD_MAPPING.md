# Module 04 Field Mapping & Schema Traceability

**Status**: `PENDING_CONFIRMATION` (Mapped against Master Plan specification; awaiting owner-approved schema verification).

---

## 1. Upstream Module 01 (Incident Intelligence) → Module 04

| Source Field | Expected Type | Required? | Module 04 Field | Missing / Null Semantics | Integration Verification Status |
|---|---|---|---|---|---|
| `incident.incident_id` | `str` | Yes | `context.incident_id` | Required; fails validation (422) if missing | `PENDING_CONFIRMATION` |
| `incident.complaint_id` | `str` | Yes | `context.complaint_id` | Required; preserved for citizen audit traceability | `PENDING_CONFIRMATION` |
| `incident.category` | `str` | Yes | `context.category` | Normalized uppercase; checked against template `allowed_categories` | `PENDING_CONFIRMATION` |
| `incident.incident_type` | `str` | Yes | `context.incident_type` | Normalized uppercase; checked against template `allowed_incident_types` | `PENDING_CONFIRMATION` |
| `incident.reported_at` | `datetime` (ISO-8601) | Yes | SLA start reference | Must be timezone-aware; fails 422 if naive | `PENDING_CONFIRMATION` |
| `incident.location` | `LocationData` | Yes | `plan.routing` | Facility/location identifiers propagated | `PENDING_CONFIRMATION` |
| `incident.estimated_waste_kg` | `float` | No | `context.estimated_waste_kg` | Preserved as `None`. If missing: `QUANTITY_NOT_MEASURED`, plan becomes `PRELIMINARY_PLAN` | `PENDING_CONFIRMATION` |
| `incident.affected_area_sqm` | `float` | No | `context.affected_area_sqm` | Preserved as `None`. If missing: `AFFECTED_AREA_NOT_MEASURED` | `PENDING_CONFIRMATION` |
| `incident.path_obstructed` | `bool` | No | `context.path_obstructed` | Tri-state logic: `True` adds clear task; `None` triggers inspection task; `False` omits task | `PENDING_CONFIRMATION` |
| `incident.hazard_detected` | `bool` | No | `context.hazard_detected` | Tri-state logic: `True` injects hazard escalation safety constraints | `PENDING_CONFIRMATION` |

---

## 2. Upstream Module 02 (Duplicate Detection) → Module 04

| Source Field | Expected Type | Required? | Module 04 Gate | Missing / Null Semantics | Integration Verification Status |
|---|---|---|---|---|---|
| `duplicate_result.processing_status` | `str` | Yes | Gate 3 | Must be `"COMPLETED"`; otherwise `BLOCKED` with `DUPLICATE_PROCESSING_INCOMPLETE` | `PENDING_CONFIRMATION` |
| `duplicate_result.decision` | `DuplicateDecision` | Yes | Gate 5 | Must be `"NEW"`. `"REVIEW_REQUIRED"` holds plan. `"DUPLICATE"` links and blocks plan | `PENDING_CONFIRMATION` |
| `duplicate_result.retrieval.status` | `str` | Yes | Gate 4 | Must be `"COMPLETE"`; otherwise `BLOCKED` with `DUPLICATE_RETRIEVAL_INCOMPLETE` | `PENDING_CONFIRMATION` |
| `duplicate_result.matched_incident_id` | `str | None` | No | Plan linkage | Propagated when decision is `DUPLICATE` | `PENDING_CONFIRMATION` |

---

## 3. Upstream Module 03 (Supervisor Decision) → Module 04

| Source Field | Expected Type | Required? | Module 04 Gate | Missing / Null Semantics | Integration Verification Status |
|---|---|---|---|---|---|
| `supervisor_decision.decision_id` | `str` | Yes | Idempotency / Audit | Required for audit trail and idempotency hash | `PENDING_CONFIRMATION` |
| `supervisor_decision.evaluation_status` | `str` | Yes | Gate 1 | Must be `"COMPLETED"`; otherwise `BLOCKED` with `SUPERVISOR_EVALUATION_INCOMPLETE` | `PENDING_CONFIRMATION` |
| `supervisor_decision.decision_status` | `SupervisorDecisionStatus` | Yes | Gate 2 | Must be `"APPROVED_TO_PROCEED"`. `"PENDING_APPROVAL"` → `BLOCKED`; `"NEEDS_REVIEW"` → `NEEDS_REVIEW` | `PENDING_CONFIRMATION` |
| `supervisor_decision.department` | `str` | Yes | Gate 9 | Must be `"SANITATION"`; otherwise `TEMPLATE_DEPARTMENT_MISMATCH` | `PENDING_CONFIRMATION` |
| `supervisor_decision.priority` | `str` | Yes | Gate 9 & Crew | Normalized to `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`; selects crew demand rule | `PENDING_CONFIRMATION` |
| `supervisor_decision.routing.status` | `str` | Yes | Gate 6 | Must be `"RESOLVED"`; otherwise `ROUTING_UNRESOLVED` | `PENDING_CONFIRMATION` |
| `supervisor_decision.sla` | `SLAInfo` | Yes | Duration preservation | Must be timezone-aware; preserved verbatim without extending clocks | `PENDING_CONFIRMATION` |
| `supervisor_decision.action_plan.template_id` | `str` | Yes | Gate 7 & 8 | Registry lookup key; must exist and be enabled | `PENDING_CONFIRMATION` |
| `supervisor_decision.action_plan.template_version` | `str` | Yes | Gate 7 & 8 | Registry lookup version; defaults to `"1"` | `PENDING_CONFIRMATION` |
| `supervisor_decision.action_plan.required_actions` | `list[str]` | No | Gate 10 | Cross-checked against template task codes | `PENDING_CONFIRMATION` |

---

## 4. Module 04 → Downstream Module 05 (Dispatch)

| Module 04 Field | Emitted Type | Boundary Invariant | Ownership Boundary | Integration Verification Status |
|---|---|---|---|---|
| `plan_id` | `str` | Stable ID (replan versioned `-R{n}`) | M04 owns work package definition | `PENDING_CONFIRMATION` |
| `dispatch_eligible` | `bool` | Must be `True` for handoff | Gate enforced: M05 evaluates eligible plans only | `PENDING_CONFIRMATION` |
| `assigned_worker_id` | `None` | **STRICT INVARIANT: Must be `None`** | Worker selection belongs to M05 | `PENDING_CONFIRMATION` |
| `assignment_status` | `Literal["UNASSIGNED"]` | **STRICT INVARIANT: Must be `UNASSIGNED`** | Assignment state machine belongs to M05 | `PENDING_CONFIRMATION` |
| `availability_confirmed` | `Literal[False]` | **STRICT INVARIANT: Must be `False`** | Resource reservation belongs to M05 | `PENDING_CONFIRMATION` |
| `tasks[].status` | `SanitationTaskStatus` | **STRICT INVARIANT: All `NOT_STARTED`** | Field execution belongs to M06 | `PENDING_CONFIRMATION` |
