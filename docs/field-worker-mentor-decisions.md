# KAVACH Field Worker — Mentor Decision Sheet

**Purpose:** Resolve the remaining cross-module decisions in one mentor/team
review. This is a decision aid, not an approved API or implementation
contract.

**Evidence labels:** **VERIFIED** describes repository behavior.
**RECOMMENDATION** is a proposal for approval only. Every decision below is
**OPEN**; no decision or mentor approval was found in the inspected repository
sources.

**Review note:** No mentor decisions were supplied with this task or recorded
in the inspected documents. Existing Field Worker behavior is included as
context, not presented as an integration decision.

**Implementation update (2026-10-30):** The local worker API now implements
accept/reject decisions for assigned tasks at the user's direction. This
code change does not convert the still-open Dispatch ownership/handoff
recommendation below into a cross-module approval or integration contract.

**Workflow update (2026-10-28):** Checklist steps are no longer part of the
current worker workflow. Sections 5 and 6 below describe retained legacy
checklist access and historical completion data, not lifecycle requirements.
New completion requests do not include checklist step IDs; new response
records expose an empty legacy `checklist_step_ids` field.

## 1. Dispatch-to-Field-Worker assignment handoff

**VERIFIED current behavior:** The Field Worker `WorkerTask` schema has
`task_id`, `incident_id`, `assigned_worker_id`, `title`, `description`,
`priority`, `status`, `location` (`latitude`, `longitude`, `address`),
the legacy checklist definition field, timestamps, and Field Worker
location/submission references. Task and worker IDs are strings up to 100 characters. Dispatch
implementation, an assignment ingress route, and a cross-module payload
contract are absent. A worker may accept or reject an owned `ASSIGNED` task
locally, but Dispatch delivery, reassignment, and cancellation are not
integrated. `TaskRepository.add_task` inserts
only, rejects an existing task ID, and has no assignment update or cancel
operation.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Handoff payload and transport | A. Dispatch writes an approved shared task record. B. Dispatch delivers an assignment through a separately approved integration channel. In either case, approve the mapping of Dispatch fields to the existing `WorkerTask` fields; do not assume every current field is already supplied by Dispatch. | **RECOMMENDATION:** Choose one authoritative producer-to-consumer path and document a field-by-field mapping before implementation. This avoids separate, drifting representations. | Dispatch + Field Worker | **OPEN** |
| Canonical task and worker IDs | A. Use Dispatch's canonical task/worker IDs directly as `task_id`/`assigned_worker_id`. B. Approve an explicit stable mapping from Dispatch IDs to Field Worker IDs. | **RECOMMENDATION:** Prefer direct canonical IDs if their format and lifecycle fit the existing 100-character string fields; otherwise approve the mapping and its owner. | Dispatch + identity owner + Field Worker | **OPEN** |
| Assignment decision and receipt | A. Treat the worker's local accept/reject as the authoritative decision. B. Treat Dispatch's decision as authoritative and use Field Worker acknowledgement only as receipt. | **RECOMMENDATION:** Align the local decision with Dispatch's approved assignment contract before production integration; keep receipt/delivery acknowledgement separate if operationally needed. Current routes allow worker decisions but do not synchronize them to Dispatch. | Dispatch + Field Worker | **OPEN** |
| Duplicate delivery | A. Identical repeat deliveries are idempotent; conflicting repeats are surfaced for reconciliation. B. Reject every duplicate and rely on producer retry policy outside Field Worker. | **RECOMMENDATION:** Approve idempotent handling for an identical assignment and explicit conflict handling for changed content. Current insertion rejects an existing ID and is not idempotent. | Dispatch + Field Worker | **OPEN** |
| Assignment updates and cancellation | A. Permit only defined pre-execution updates; require an explicit process once work has started. B. Treat all changes/cancellations as a new assignment lifecycle while retaining the original record/history. | **RECOMMENDATION:** Define update/cancel rules by execution state before connecting Dispatch; do not overwrite worker progress, evidence, or completion history implicitly. | Dispatch + Field Worker | **OPEN** |

## 2. Blocker handling

**VERIFIED current behavior:** `BlockerReport` accepts a formatted
`reason_code`, a description (1–500 characters), and optional `step_id`.
Allowed codes come from `BLOCKER_REASON_CODES`; development has explicitly
non-approved examples `DEV_ACCESS`, `DEV_EQUIPMENT`, and `OTHER`. An explicitly empty
list returns `503`, and a code outside a configured list returns `422`.
Production reporting remains disabled unless a list is configured and
`BLOCKER_REASON_CODES_APPROVED=true`; this flag is a deployment gate, not
proof that the vocabulary was mentor-approved. One open blocker per task is
enforced. `GET /operator/blockers`
lists open blockers; `POST /operator/tasks/{task_id}/unblock` takes an
optional resolution note. Both operator routes use demo operator
authentication, unavailable in production. Unblock records the operator ID
and note and returns the task to its previous status. No polling/event
delivery agreement exists.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Approved reason-code list | A. Use a centrally owned, versioned allow-list with a free-text description for context. B. Allow free-text reasons without a code allow-list. | **RECOMMENDATION:** Approve a controlled shared list and owner; keep the description for detail. Do not enable reports with invented codes. | Dispatch/operations + Field Worker | **OPEN** |
| Blocker notification/discovery | A. Dispatch polls an approved open-blocker view. B. A durable event/notification path signals blocker changes, with a defined recovery mechanism. | **RECOMMENDATION:** Choose the smallest operationally supportable mechanism and define freshness, retry, duplicate, pagination, and recovery semantics. The existing list is unpaged and has no acknowledgement/event behavior. | Dispatch + Field Worker | **OPEN** |
| Unblock authority | A. Dispatch alone may resolve blockers. B. Dispatch and specifically authorized Supervisor roles may resolve them. | **RECOMMENDATION:** Allow only approved operational roles, with distinct identities and auditable actor attribution; worker credentials must not grant unblock access. | Dispatch/operations + shared-auth owner | **OPEN** |
| Communicating the unblock decision | A. An authorized operator resolves through the existing Field Worker operator flow, which records actor and optional note. B. Dispatch records its decision in its own system and communicates it through a separately approved integration, with Field Worker state updated through the agreed path. | **RECOMMENDATION:** Make the decision, responsible actor, and resolution note traceable in the authoritative workflow; agree which system owns the final state change before integration. No production Dispatch-to-Field-Worker route is established. | Dispatch + Field Worker | **OPEN** |

## 3. Shared authentication

**VERIFIED current behavior:** Worker and operator routes use separate
development Bearer tokens that resolve to configured fixed IDs. Task access
compares the resulting worker ID to `assigned_worker_id`. The worker row has
an `is_active` field, but the demo dependency does not map a credential to a
worker row or check active status. Production startup is refused until shared
authentication is integrated.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Identity provider and validation boundary | A. Field Worker validates credentials through the KAVACH-approved identity provider. B. An approved trusted platform boundary validates them and supplies a verifiable identity to Field Worker. | **RECOMMENDATION:** Select the existing KAVACH identity architecture and document who validates credentials and what trust boundary applies. The repository does not establish a provider, token format, or claims contract. | Shared-auth/identity owner + platform security | **OPEN** |
| Worker identity mapping | A. The authenticated canonical worker ID is the same value Dispatch stores in `assigned_worker_id` and the `workers` key. B. An approved mapping resolves the authenticated subject to that stored ID. | **RECOMMENDATION:** Prefer one canonical identifier; otherwise specify mapping ownership, uniqueness, lifecycle, unknown-worker handling, and inactive-worker handling. | Shared-auth/identity + Dispatch + Field Worker | **OPEN** |
| Operator roles and permissions | A. Use one operational role for blocker discovery and resolution. B. Define separate Dispatch and Supervisor permissions for viewing, resolving, and recording blocker decisions. | **RECOMMENDATION:** Approve least-privilege permissions by operation, and record the authenticated actor rather than a fixed demo operator. | Shared-auth/identity + Dispatch/operations | **OPEN** |
| Development versus production | A. Keep demo credentials strictly local/test and require approved shared auth in production. B. Use shared auth in all environments with separately approved test identities. | **RECOMMENDATION:** Retain demo-only credentials in development/test if useful; production must fail closed without approved shared auth. No production bypass should be introduced. | Shared-auth/identity + Field Worker | **OPEN** |

## 4. GPS exceptions

**VERIFIED current behavior:** Location states are `CAPTURED`,
`UNAVAILABLE`, and `INACCURATE`. Captured fixes require finite in-range
coordinates and positive accuracy; readings worse than the configured
threshold (default 100m) are recorded as inaccurate without coordinates.
Arrival and completion events may be recorded as unavailable/inaccurate, but
a captured arrival is required to start and captured arrival plus completion
location are required for completion submission. Invalid input returns
`422`; unsupported task state returns `409`. No exception path or exception
audit record exists.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Unavailable GPS, inaccurate reading, or failed capture | A. Continue requiring a captured fix; retry or defer work/submission when unavailable or inaccurate. B. Allow an authorized exception under an approved policy when capture cannot meet requirements. | **RECOMMENDATION:** Keep current strict behavior until policy owners approve any exception and its distinct handling. Define failed capture separately from a successfully recorded `UNAVAILABLE` event. | Product/operations + Field Worker; Dispatch consulted | **OPEN** |
| Exception authority and audit evidence | A. No exceptions. B. Permit an exception approved by a designated role, with the original capture outcome and decision retained for audit. | **RECOMMENDATION:** If exceptions are approved, require attributable approval, reason, time, related task/event, and retained original reading state; do not reinterpret a failed/unavailable reading as captured. | Operations/compliance + shared-auth + Field Worker | **OPEN** |
| Accuracy threshold and use | A. Keep the current configurable threshold as Field Worker policy. B. Set a shared KAVACH threshold/policy owner and version it for all consuming modules. | **RECOMMENDATION:** Identify one policy owner and ensure all clients interpret the same accuracy limit; no new threshold is proposed here. | Product/operations + Field Worker | **OPEN** |

## 5. Legacy multi-worker checklist access

**VERIFIED current behavior:** Each checklist step stores
`assigned_worker_id`; omitted ownership defaults to the task's primary
worker. Both checklist reads and updates first require the caller to own the
task. Updates additionally require the caller to own the step and the task
to be `IN_PROGRESS`. Therefore a secondary step owner cannot currently read
the checklist or update their assigned step using these routes.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Step ownership and task membership | A. Checklist owners must always equal the primary task worker. B. Dispatch may assign steps to named task-crew members distinct from the primary worker. | **RECOMMENDATION:** Explicitly choose whether multi-worker execution is in scope; do not accept secondary owners in assignment data unless access rules are approved. | Dispatch/crew owner + Field Worker | **OPEN** |
| Read and update permissions | A. Only the primary worker can read/update all steps. B. Crew members may read task/checklist context while only the assigned step owner (and defined privileged roles) can update a step. | **RECOMMENDATION:** If crews are supported, define task membership, read scope, step-owner update scope, privileged override, and revocation as a single authorization contract. | Dispatch/crew owner + shared-auth + Field Worker | **OPEN** |
| Owner differs from primary worker | A. Reject or normalize the assignment so step owner equals primary worker. B. Preserve the secondary owner and authorize via approved crew membership. | **RECOMMENDATION:** Do not silently normalize an explicitly assigned owner. Either reject it before task creation or support it only after the crew authorization contract is implemented. | Dispatch + Field Worker | **OPEN** |

## 6. Completion-to-Verification handoff

**VERIFIED current behavior:** Completion submission accepts at least two
unique evidence IDs, an optional completion-location event ID, optional
notes, and a required `Idempotency-Key`. Validation requires same-task/
primary-worker evidence containing BEFORE and AFTER images, and captured
arrival/completion locations. Checklist status, references, and evidence
freshness relative to checklist completion are not requirements. The
submission and task status become `COMPLETION_SUBMITTED`.
Same idempotency key and same body returns the original submission; same key
with a different body returns `409`. No verifier read path, acknowledgement,
verification outcome, rejection, or rework flow is present. The schema allows
only one completion submission per task.

The worker request fields are `evidence_ids`,
`completion_location_event_id`, and `notes`, plus the `Idempotency-Key`
header. The successful response's `submission` fields are `submission_id`,
`task_id`, `worker_id`, `checklist_step_ids`, `evidence_ids`,
`completion_location_event_id`, `notes`, `submitted_at`, and `status`.
New submissions return an empty `checklist_step_ids`; the field and persisted
step-link structure remain for historical compatibility.
Evidence bytes are not embedded; the evidence IDs refer to persisted records.
**No Verification Agent acknowledgement contract exists in the source**:
acknowledgement meaning, transport, fields, and retry behavior remain OPEN
for team approval; this sheet does not define them. Until that shared
contract exists, Field Worker does not implement rejection or reassignment;
Dispatch retains task assignment/reassignment ownership, while Verification
owns its independent assessment.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Handoff content and evidence access | A. Verification consumes the persisted submission and its referenced checklist, evidence, and location records through an approved shared-data boundary. B. An approved delivery carries a submission reference and the verifier retrieves the associated records through an agreed mechanism. | **RECOMMENDATION:** Keep the persisted submission as the auditable source and grant the verifier least-privilege access to exactly the referenced records. Approve field mapping and evidence access before delivery; no verifier payload or endpoint is defined here. | Verification Agent + Field Worker + data/security owners | **OPEN** |
| Delivery acknowledgement and retry | A. Durable handoff is acknowledged by the verifier, with retry/reconciliation for unacknowledged submissions. B. The verifier discovers pending submissions from an approved shared source and records its processing state there. | **RECOMMENDATION:** Require a durable, observable acknowledgement or equivalent reconciliation so submission delivery cannot be silently lost or duplicated. | Verification Agent + Field Worker | **OPEN** |
| Findings and verification outcome | A. The verifier returns structured findings for each submission. B. The verifier returns an overall decision with a narrative finding. | **RECOMMENDATION:** Agree the minimum findings, evidence references, actor, timestamps, and decision semantics; do not add status names until status ownership is settled. | Verification Agent + product/operations | **OPEN** |
| Rejection, rework, reassignment, and resubmission | A. Reopen the existing task/submission for rework. B. Preserve each submitted claim as immutable history and authorize a distinct rework/resubmission lifecycle, including any worker reassignment. | **RECOMMENDATION:** Preserve prior claims and findings; explicitly define who authorizes rework, whether assignment can change, how new evidence is linked, and how repeat submissions remain identifiable/idempotent. Current one-submission-per-task storage must be reconciled with the approved choice. | Verification Agent + Dispatch + Field Worker | **OPEN** |

## 7. Database integration

**VERIFIED current behavior:** PostgreSQL is the only supported backend.
Source migrations are linear from `0001` to `0002`; startup requires the
database revision to equal the source head. Models include workers, tasks,
checklist steps, evidence, location events, completion records,
idempotency records, and blockers. The Field Worker repository owns local
insert/query methods, but no shared KAVACH schema ownership agreement is
documented. A test fixture migrates and truncates its configured database;
no test or database was run/accessed for this decision sheet. The reported
live revisions of `kavach_test` and `kavach` remain unverified.

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Canonical shared schema and ownership | A. Field Worker owns its task-execution tables while shared IDs/contracts are governed centrally. B. A named KAVACH data owner governs a shared schema and module boundaries, with Field Worker owning only approved execution tables. | **RECOMMENDATION:** Name a canonical schema owner and table-level owners before direct database integration; explicitly document who may write each shared record. | KAVACH data/platform owner + Dispatch + Field Worker | **OPEN** |
| Identifier and migration ownership | A. Dispatch owns assignment identity and migrations for assignment records; Field Worker owns execution records. B. One designated data team owns shared-table migrations with module review/approval. | **RECOMMENDATION:** Keep assignment identity authoritative in Dispatch and execution history authoritative in Field Worker, with a single named migration process for shared schema changes. | KAVACH data/platform owner + module leads | **OPEN** |
| Integration sequence | A. Approve API/event contracts first, then implement the boundary without shared-table writes. B. Approve shared-schema ownership and ID mapping first, then implement database integration. | **RECOMMENDATION:** Decide the ownership/boundary model before building either path; validate it in staging before production rollout. | KAVACH data/platform owner + Dispatch + Field Worker | **OPEN** |
| Migration and destructive-test approval | A. Each migration or destructive test requires explicit target-specific database-owner approval and a verified recovery plan. B. Allow routine automation only for explicitly disposable, isolated test databases under documented safeguards. | **RECOMMENDATION:** Require explicit approval for every non-disposable target and restrict destructive test automation to verified disposable PostgreSQL databases. Never use a test fixture against a shared or production database. | Database owner + test/platform owner | **OPEN** |

## 8. API/status compatibility

**VERIFIED current behavior:** Field Worker uses `ACCEPTED`,
`IN_PROGRESS`, `PAUSED`, `BLOCKED`, and `COMPLETION_SUBMITTED` in its
execution path. `ASSIGNED` and `REJECTED` remain readable legacy/Dispatch
states but are not worker transitions. Blockers use `OPEN`/`RESOLVED`;
checklist steps use `PENDING`/`COMPLETED`/`BLOCKED`; GPS capture uses
`CAPTURED`/`UNAVAILABLE`/`INACCURATE`. Current routes include a demo-only
operator blocker listing/unblock surface. Validation errors and business
errors both use HTTP `422` but have different `detail` JSON shapes. No
approved shared status vocabulary or cross-module error envelope is present.

**Compatibility conflicts cannot be confirmed against a shared contract,
because no approved shared contract was found.** The following are verified
Field Worker behaviors that would conflict with a contract expecting the
opposite; resolve them explicitly rather than assuming either side:

| Verified Field Worker behavior | Potential incompatibility if shared contract expects… | Decision needed |
|---|---|---|
| Inbound task creation and worker decisions are separate: Dispatch ingestion is absent; local worker accept/reject routes support `ASSIGNED` tasks. | Define authoritative handoff, retry, and decision synchronization between Dispatch and Field Worker. | Approve the Dispatch-to-Field-Worker integration contract. |
| Task and worker IDs are strings limited to 100 characters; task inserts require the referenced workers to exist. | Different identifier formats/lengths or eventual worker records. | Approve canonical IDs or an explicit mapping and record-provisioning order. |
| Duplicate task IDs are rejected; there is no assignment update/cancel operation. | At-least-once delivery, mutable assignments, or cancellation updates without reconciliation. | Approve duplicate, update, and cancellation behavior before connecting delivery. |
| Secondary checklist owners cannot access the task through worker routes. | Crew members need to read task/checklist context or update assigned steps. | Approve crew membership and route authorization. |
| Blocker listing/unblock currently use demo operator auth; development example codes are not approved, and production requires an explicitly approved configuration gate. | Production Dispatch polling/resolution or blocker reports without shared auth and an approved reason list. | Approve shared auth, reason codes, and blocker workflow. |
| Start/completion require captured locations; there is no exception workflow. | Work can proceed or be submitted with unavailable/inaccurate/failed GPS. | Approve an exception policy and audit requirements before changing validation. |
| One completion submission per task; `COMPLETION_SUBMITTED` has no reject/rework transition. | Verification may reject and require another worker submission or reassignment. | Approve the verification/rework lifecycle and reconcile persistence constraints. |
| Business and schema-validation `422` responses use different `detail` shapes. | Consumers expect one shared error envelope. | Approve consumer handling or a versioned compatibility change. |

| Decision | Options | Recommendation | Owner | Status |
|---|---|---|---|---|
| Status ownership and mapping | A. Keep Dispatch assignment/offer lifecycle separate from Field Worker execution lifecycle and agree an explicit mapping at the handoff. B. Define one shared cross-module lifecycle vocabulary and change module mappings to it. | **RECOMMENDATION:** Preserve separate ownership boundaries unless the mentor/team has a concrete need for a unified lifecycle; approve mappings before any status transformation. | Dispatch + Field Worker + Verification Agent | **OPEN** |
| Completion/verification compatibility | A. Keep `COMPLETION_SUBMITTED` as the Field Worker submission state and let verification outcomes remain separately owned. B. Replace it with a shared lifecycle after agreement on verification and rework. | **RECOMMENDATION:** Do not treat `COMPLETION_SUBMITTED` as verified; keep it as a submission fact until the Verification Agent contract is approved. Any future status must be agreed, not inferred. | Field Worker + Verification Agent + Dispatch | **OPEN** |
| Legacy states and removed routes | A. Keep `ASSIGNED`/`REJECTED` readable only for legacy records and keep accept/reject solely with Dispatch. B. Remove legacy states only after a separately approved data-compatibility plan. | **RECOMMENDATION:** Retain current compatibility and Dispatch ownership during integration; do not reintroduce Field Worker accept/reject routes. Decide on legacy cleanup separately. | Dispatch + Field Worker | **OPEN** |
| Error and route compatibility | A. Consumers adapt to current route/status/error behavior. B. Approve a shared error envelope and compatibility/versioning policy before consumers depend on it. | **RECOMMENDATION:** Publish current request/response/error behavior and agree versioning before changing it. In particular, account for the two current `422` `detail` shapes and the development-only operator routes. | API/platform owner + Dispatch + Field Worker | **OPEN** |

## Approval table

Fill one row per decision after review. Recommendations above are not
approvals.

| Decision area | Approved option / amendment | Approving owner(s) | Date | Status |
|---|---|---|---|---|
| Dispatch handoff |  |  |  | OPEN |
| Blocker handling |  |  |  | OPEN |
| Shared authentication |  |  |  | OPEN |
| GPS exceptions |  |  |  | OPEN |
| Multi-worker checklist access |  |  |  | OPEN |
| Completion-to-Verification |  |  |  | OPEN |
| Database integration |  |  |  | OPEN |
| API/status compatibility |  |  |  | OPEN |

## Implementation blockers

Implementation remains blocked pending approval of the following
dependencies:

1. Canonical task/worker identity and assignment delivery, duplicate, update,
   and cancellation semantics.
2. Shared authentication and operator authorization in production.
3. Blocker reason-code ownership and Dispatch discovery/resolution workflow.
4. GPS exception policy and audit requirements, if any exceptions are
   permitted.
5. Crew membership and secondary checklist-owner access rules, if
   multi-worker tasks are in scope.
6. Verification handoff, acknowledgement, findings, and rejection/rework
   lifecycle.
7. Shared PostgreSQL schema ownership, migration responsibility, and
   target-specific explicit approval before migration or destructive tests.
8. Cross-module API/status/error compatibility and acceptance sign-off.

## Evidence sources and limits

This decision sheet is based on the
[Field Worker integration contract](./field-worker-integration-contract.md)
and current repository definitions, including `app/schemas/worker_task.py`,
`app/schemas/blocker.py`, `app/schemas/location_event.py`,
`app/schemas/completion.py`, `app/api/worker_task_routes.py`,
`app/api/blocker_routes.py`, `app/api/location_routes.py`,
`app/services/blocker_service.py`,
`app/services/location_capture_service.py`,
`app/services/completion_submission_service.py`,
`app/repositories/task_repository.py`, `app/db/models.py`,
`app/db/database.py`, `app/main.py`, and
`migrations/versions/0002_blockers_step_owners.py`.

The repository does not identify named decision owners, record mentor
approvals, define a Dispatch handoff or Verification Agent contract, establish
the shared authentication provider, establish shared-schema ownership, or
prove live database revisions. Owners above are team/module roles for review,
not identified individuals. Recommendations are not approved contracts.
