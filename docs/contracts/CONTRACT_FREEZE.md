# Module 04 Contract Freeze & Integration Specification

**Status**: `PENDING_CONFIRMATION` (Awaiting formal schema exchange and fixture validation with Modules 01, 02, 03, and 05).

---

## 1. Upstream & Downstream Integration Status

| Module | Direction | Required Schema Artifact | Current Evidence | Status |
|---|---|---|---|---|
| **Module 01 (Incident Intelligence)** | Upstream → M04 | Canonical Incident Record (`IncidentRecord`) | Local synthetic fixture: `fixtures/module01/synthetic_incident_record.json` | `PENDING_CONFIRMATION` |
| **Module 02 (Duplicate Detection)** | Upstream → M04 | Duplicate Result (`DuplicateResult`) | Local synthetic fixture: `fixtures/module02/synthetic_duplicate_result.json` | `PENDING_CONFIRMATION` |
| **Module 03 (Supervisor Decision)** | Upstream → M04 | Authorized Supervisor Decision (`SupervisorDecision`) | Local synthetic fixture: `fixtures/module03/synthetic_supervisor_decision.json` | `PENDING_CONFIRMATION` |
| **Module 05 (Dispatch)** | M04 → Downstream | Dispatch Work Package (`DispatchWorkPackage`) | Local synthetic fixture: `fixtures/module05/synthetic_dispatch_work_package.json` | `PENDING_CONFIRMATION` |

---

## 2. Module 04 Input Contract (`SanitationPlanRequest`)

Canonical Endpoint: `POST /api/v1/sanitation/plan`

### Structure
- `contract_version`: `Literal["1.0.0"]` (Required)
- `event_id`: Non-empty string (Used as idempotency scope fallback)
- `incident`: `IncidentRecord`
  - `incident_id`: String (e.g. `INC-2026-000123`)
  - `complaint_id`: String (e.g. `CMP-2026-000123`)
  - `category`: Uppercase string (e.g. `WASTE_OVERFLOW`, `FACILITY_CLEANING`, `HAZARD_OR_SPILL`)
  - `incident_type`: Uppercase string (e.g. `BIN_OVERFLOW`, `GARBAGE_PILE`, `DIRTY_PUBLIC_TOILET`, `WASTE_SPILL`)
  - `reported_at`: Timezone-aware ISO-8601 `datetime`
  - `location`: `LocationData` (`facility_id`, `location_id`, coordinates)
  - `estimated_waste_kg`: Optional float (Preserved as `None` if unmeasured; never defaults to 0)
  - `affected_area_sqm`: Optional float (Preserved as `None` if unmeasured)
  - `path_obstructed`: Optional tri-state boolean (`True`, `False`, or `None`)
  - `hazard_detected`: Optional tri-state boolean (`True`, `False`, or `None`)
- `duplicate_result`: `DuplicateResult`
  - `processing_status`: String (Must be `COMPLETED`)
  - `decision`: `DuplicateDecision` (`NEW`, `DUPLICATE`, `REVIEW_REQUIRED`)
  - `retrieval.status`: String (Must be `COMPLETE`)
- `supervisor_decision`: `SupervisorDecision`
  - `decision_id`: Non-empty string
  - `evaluation_status`: String (Must be `COMPLETED`)
  - `decision_status`: `SupervisorDecisionStatus` (`APPROVED_TO_PROCEED`, `PENDING_APPROVAL`, `NEEDS_REVIEW`)
  - `department`: String (Must be `SANITATION`)
  - `priority`: String (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
  - `routing`: `RoutingInfo` (`status` must be `RESOLVED`)
  - `sla`: `SLAInfo` (Timezone-aware timestamps `started_at`, `response_due_at`, `resolution_due_at`)
  - `action_plan`: `ActionPlan` (`template_id`, `template_version`, `objective`, `required_actions`, `constraints`)
- `replan_context`: Optional `ReplanContext` (`previous_plan_id`, `replan_reason`)

---

## 3. Decision Gates & Reasons

Requests are evaluated sequentially through 10 deterministic gates:
1. **Gate 1 (Supervisor Evaluation)**: `evaluation_status == "COMPLETED"`. Failure: `SUPERVISOR_EVALUATION_INCOMPLETE` (`BLOCKED`).
2. **Gate 2 (Supervisor Decision)**: `decision_status == "APPROVED_TO_PROCEED"`. `PENDING_APPROVAL` produces `SUPERVISOR_PENDING_APPROVAL` (`BLOCKED`). `NEEDS_REVIEW` produces `SUPERVISOR_NOT_APPROVED` (`NEEDS_REVIEW`).
3. **Gate 3 (Duplicate Processing)**: `processing_status == "COMPLETED"`. Failure: `DUPLICATE_PROCESSING_INCOMPLETE` (`BLOCKED`).
4. **Gate 4 (Duplicate Retrieval)**: `retrieval.status == "COMPLETE"`. Failure: `DUPLICATE_RETRIEVAL_INCOMPLETE`, `CANNOT_ASSUME_NEW_INCIDENT` (`BLOCKED`).
5. **Gate 5 (Duplicate Outcome)**: `decision == "NEW"`. `REVIEW_REQUIRED` produces `DUPLICATE_REVIEW_HOLD`. `DUPLICATE` produces `DUPLICATE_OF_EXISTING_INCIDENT` (`BLOCKED`).
6. **Gate 6 (Routing)**: `routing.status == "RESOLVED"`. Failure: `ROUTING_UNRESOLVED` (`NEEDS_REVIEW`).
7. **Gate 7 & 8 (Template Registry Lookup)**: Template must exist in registry and be `enabled`. Failure: `TEMPLATE_NOT_FOUND_OR_DISABLED` (`NEEDS_REVIEW`).
8. **Gate 9 (Taxonomy & Priority Compatibility)**: Checks category, incident_type, department, and priority against template. Failure: `TEMPLATE_CATEGORY_MISMATCH`, `TEMPLATE_TYPE_MISMATCH`, `TEMPLATE_DEPARTMENT_MISMATCH`, or `TEMPLATE_PRIORITY_MISMATCH`.
9. **Gate 10 (Action Cross-Check)**: Verifies authorized `required_actions` exist in template. Failure: `SUPERVISOR_REQUIRED_ACTIONS_NOT_IN_TEMPLATE` (`NEEDS_REVIEW`).

---

## 4. Module 04 Output Contract (`SanitationPlanResult`)

### Planning Statuses
- `PLAN_READY`: Fully quantified, validated, no hold reasons. May be evaluated for dispatch.
- `PRELIMINARY_PLAN`: Plan created with safe minimum assumptions, but key measurements are missing (e.g. `QUANTITY_NOT_MEASURED`). `dispatch_eligible = false`.
- `NEEDS_REVIEW`: Upstream conflict, unapproved action, or taxonomy mismatch requiring Supervisor review. `dispatch_eligible = false`.
- `BLOCKED`: Upstream prerequisite not satisfied (pending approval, incomplete evaluation, duplicate, or incomplete duplicate retrieval). `dispatch_eligible = false`.

### Dispatch Eligibility Invariants
`dispatch_eligible == True` is **strictly impossible** unless:
- `planning_status == "PLAN_READY"`
- `hold_reason_codes` is empty
- At least one task is planned
- `routing.status == "RESOLVED"`
- `resource_estimate.availability_confirmed == False`
- All tasks have `status == "NOT_STARTED"`

---

## 5. Downstream Dispatch Handoff (`DispatchWorkPackage`)

Canonical Endpoint: `POST /api/v1/sanitation/handoff`

Module 04 enforces strict lifecycle boundaries on the work package handed to Module 05:
- `assigned_worker_id`: Strictly `None` (Worker selection belongs to Module 05).
- `availability_confirmed`: Strictly `False` (Availability checking belongs to Module 05).
- `assignment_status`: Strictly `"UNASSIGNED"`.
- `tasks[].status`: Strictly `"NOT_STARTED"` (Field execution belongs to Module 06).
- Verification & closure belong to Modules 07 & 08.
