# KAVACH Module 04 — Contract Comparison & Integration Checklist

**Document Status**: `PENDING_CONFIRMATION`  
**Purpose**: Pre-integration contract checklist to verify field names, enums, null semantics, and behavioral invariants with owning modules prior to end-to-end integration.

---

## 1. Module 01 (Incident Intelligence) → Module 04 (Sanitation Planning)

| Item # | Topic / Field | Module 04 Expected Value / Behavior | Module 01 Confirmed Value | Status |
|---|---|---|---|---|
| M01-01 | Incident Identifier | `incident.incident_id`: String (e.g. `INC-2026-000123`) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-02 | Complaint Traceability | `incident.complaint_id`: String (e.g. `CMP-2026-000123`) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-03 | Taxonomy Category | `incident.category`: Uppercase string (`WASTE_OVERFLOW`, `FACILITY_CLEANING`, `HAZARD_OR_SPILL`) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-04 | Taxonomy Incident Type | `incident.incident_type`: Uppercase string (`BIN_OVERFLOW`, `GARBAGE_PILE`, `DIRTY_PUBLIC_TOILET`, `WASTE_SPILL`) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-05 | Timestamp Serialization | `incident.reported_at`: ISO-8601 string with mandatory timezone offset (`+05:30` or `Z`) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-06 | Physical Measurements | `estimated_waste_kg` and `affected_area_sqm`: Float or `null` (never `0` to represent unknown) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-07 | Environmental Facts | `path_obstructed`, `hazard_detected`: Tri-state boolean (`true`, `false`, `null`) | [Pending from M01 team] | `PENDING_CONFIRMATION` |
| M01-08 | Media References | `incident.media`: Array of opaque storage references (no file downloads by M04) | [Pending from M01 team] | `PENDING_CONFIRMATION` |

---

## 2. Module 02 (Duplicate Detection) → Module 04 (Sanitation Planning)

| Item # | Topic / Field | Module 04 Expected Value / Behavior | Module 02 Confirmed Value | Status |
|---|---|---|---|---|
| M02-01 | Processing Status | `duplicate_result.processing_status`: Must be `"COMPLETED"` to proceed | [Pending from M02 team] | `PENDING_CONFIRMATION` |
| M02-02 | Duplicate Decision Enum | `duplicate_result.decision`: `"NEW"`, `"DUPLICATE"`, or `"REVIEW_REQUIRED"` | [Pending from M02 team] | `PENDING_CONFIRMATION` |
| M02-03 | Retrieval Status | `duplicate_result.retrieval.status`: Must be `"COMPLETE"`. Incomplete retrieval blocks planning with `CANNOT_ASSUME_NEW_INCIDENT` | [Pending from M02 team] | `PENDING_CONFIRMATION` |
| M02-04 | Duplicate Linkage | `duplicate_result.matched_incident_id`: Provided when decision is `DUPLICATE` | [Pending from M02 team] | `PENDING_CONFIRMATION` |

---

## 3. Module 03 (Supervisor) → Module 04 (Sanitation Planning)

| Item # | Topic / Field | Module 04 Expected Value / Behavior | Module 03 Confirmed Value | Status |
|---|---|---|---|---|
| M03-01 | Evaluation Status Gate | `supervisor_decision.evaluation_status`: Must be `"COMPLETED"`. Incomplete status blocks planning | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-02 | Decision Status Gate | `supervisor_decision.decision_status`: Must be `"APPROVED_TO_PROCEED"`. `"PENDING_APPROVAL"` and `"NEEDS_REVIEW"` hold plan | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-03 | Department Scope | `supervisor_decision.department`: Must be `"SANITATION"` | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-04 | Priority Enum | `supervisor_decision.priority`: `"LOW"`, `"MEDIUM"`, `"HIGH"`, or `"CRITICAL"` | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-05 | Routing Resolution | `supervisor_decision.routing.status`: Must be `"RESOLVED"`; facility and location IDs propagated | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-06 | SLA Deadlines | `supervisor_decision.sla`: `started_at`, `response_due_at`, `resolution_due_at`. M04 preserves timestamps verbatim without resetting | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-07 | Authoritative Template | `action_plan.template_id` & `template_version`: M04 looks up exact approved template from registry without silent substitution | [Pending from M03 team] | `PENDING_CONFIRMATION` |
| M03-08 | Required Actions Cross-Check | `action_plan.required_actions`: Every authorized action must match a valid task rule in the template | [Pending from M03 team] | `PENDING_CONFIRMATION` |

---

## 4. Module 04 (Sanitation Planning) → Module 05 (Dispatch)

| Item # | Topic / Field | Module 04 Output Guarantees | Module 05 Expected Ingestion Contract | Status |
|---|---|---|---|---|
| M04-01 | Eligibility Gating | Work package emitted via `/handoff` only when `dispatch_eligible == true` and `planning_status == "PLAN_READY"` | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
| M04-02 | Worker Assignment Boundary | `assigned_worker_id == null` strictly. M04 never assigns candidates | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
| M04-03 | Availability Boundary | `availability_confirmed == false` strictly. M04 never confirms live availability | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
| M04-04 | Assignment State | `assignment_status == "UNASSIGNED"` strictly | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
| M04-05 | Task Execution State | All tasks have `status == "NOT_STARTED"` strictly. M04 never marks in-progress | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
| M04-06 | Work Package Structure | Structured `tasks[]`, `resource_demand`, `duration_estimate`, `safety_constraints` | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
| M04-07 | Replan Traceability | When replanned, `previous_plan_id` and `replan_reason` are explicitly linked; prior plan preserved | [Pending confirmation with M05] | `PENDING_CONFIRMATION` |
