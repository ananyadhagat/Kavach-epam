# Duplicate Detection M2 → M3 → M4 Integration Test Plan

> **Status:** planning artifact. This document describes tests to add and the
> behavior they should verify. It does not change production logic, scoring,
> decision policy, public schemas, thresholds, weights, or field mappings.
>
> **Transport:** the HTTP edge is deferred. This plan verifies the in-process
> pipeline only. No endpoint path or transport contract is asserted here.
>
> **Contract dependencies:** cases marked `[A1-SIGNOFF]` depend on Agent 1's
> final handoff contract; cases marked `[A3-REQ]` depend on Agent 3/Supervisor
> response requirements. Open items are listed in §9.

## 1. Objective

Verify that a complaint can move through the complete duplicate-detection seam:

```text
Agent 1 handoff envelope
        │
        ▼
M2 input adapter ──► Complaint
        │
        ▼
candidate retrieval
        │
        ▼
comparators ──► M3 weighted scoring ──► M4 decision policy
        │
        ▼
DuplicateDetectionResponse ──► Agent 3 / Supervisor
```

The tests should prove three things:

1. Each boundary accepts only the input it is designed to accept.
2. Failures at a boundary are explicit and are not silently converted into a
   business decision.
3. The public response is stable enough for downstream consumption without
   exposing internal ranking details that have not been agreed.

## 2. Scope and non-goals

### In scope

- Agent 1 handoff envelope → `Complaint` via
  [`app/adapters/incident_payload.py`](../../app/adapters/incident_payload.py).
- `Complaint` → `DuplicateDetectionResponse` via
  [`app/services/detection_service.py`](../../app/services/detection_service.py).
- Retrieval through the `ComplaintRepository` contract.
- Comparator results, M3 scoring, and M4 decision gates.
- Public response shape and invariants.
- A provisional downstream-consumption smoke test for Agent 3/Supervisor.

### Out of scope

- Finalizing or expanding shared schemas.
- Defining endpoint paths, HTTP status codes, or transport error mapping.
- Changing or calibrating thresholds, weights, or category/location mappings.
- Real embedding-model, network, database, or vector-store calls in tests.
- Changes to Agent 1 or Agent 3/Supervisor code.
- Declaring current provisional policy values to be final.

## 3. Test levels and ownership

| Level | What it exercises | Owning module |
| --- | --- | --- |
| Adapter contract | Handoff envelope → `Complaint`, including rejection paths | `app/adapters/incident_payload.py`, `app/schemas/complaint.py` |
| Service integration | `Complaint` → retrieval → comparators → engine → policy → response | `app/services/detection_service.py` |
| Policy seam | `CandidateScore` → `DecisionOutcome` ranking, gates, ambiguity | `app/scoring/decision_policy.py` |
| Response contract | `DuplicateDetectionResponse` shape and invariants | `app/schemas/duplicate_response.py` |
| Consumer contract | Response object/serialization consumed by Agent 3/Supervisor | Agent 3/Supervisor, with response schema as the producer boundary |

The service integration tests use deterministic test doubles. They do not load
the embedding model and do not depend on a live repository.

## 4. Dependency markers

| Marker | Meaning | Effect on the test |
| --- | --- | --- |
| `[A1-SIGNOFF]` | Final assertions depend on Agent 1's signed-off handoff contract. The current adapter targets draft `a1-to-a2-draft-1`. | Test may run against the draft, but must not be presented as final contract validation. |
| `[A3-REQ]` | Exact downstream acceptance criteria are not yet provided. | Test is blocked or limited to current response-schema smoke checks; do not invent downstream behavior. |
| `[POLICY-OPEN]` | Current behavior is observable, but the policy question is unresolved. | Assert only current behavior; record the desired behavior as an open question. |
| `[RETRIEVAL-OPEN]` | Production retrieval completeness/failure behavior is unresolved. | Use fake repositories; do not assert production completeness semantics. |
| `[NO-DEP]` | No external contract sign-off is required for the current behavior. | May be implemented and asserted now. |

## 5. Fixture and assertion rules

1. **Handoff fixture.** Build a representative draft handoff envelope with the
   canonical keys the current adapter accepts. The adapter consumes Agent 1's
   handoff envelope, not the raw `StructuredIncidentRecord`; raw upstream field
   names belong only in rejection cases. Include an optional `kavach_agent1`
   context object in at least one case. Deep-copy the payload before calling the
   adapter and assert it was not mutated.
2. **Incoming complaint source.** For cases that claim to cover Agent 1 input,
   construct the incoming `Complaint` through `to_complaint()` rather than
   instantiating it directly. For boundary-specific cases, a direct `Complaint`
   is acceptable and should be stated.
3. **Repository double.** Use a fake `ComplaintRepository` that records
   `exclude_complaint_id`, returns a controlled list, or raises
   `RepositoryError`.
4. **Comparator double.** Use mapping-based fake comparators keyed by candidate
   ID. Each comparator returns a `SignalResult`; at least one case raises an
   exception and one returns a malformed value.
5. **No hardcoded policy values.** Derive expectations from the active
   `Settings` (for example, `settings.thresholds.high`,
   `settings.thresholds.low`, and `settings.tie_margin`) or from the M3 engine
   result. Do not copy current defaults into the integration plan as final
   values.
6. **No invented mappings.** Use the draft fields already accepted by the
   adapter. Do not add raw upstream fields, new response fields, or endpoint
   paths in test setup.
7. **Public assertions first.** Assert the public `DuplicateDetectionResponse`
   unless the case explicitly says it is a policy-seam test. Internal candidate
   ranking is not part of the current public contract.
8. **Determinism.** Run candidate-order variants with the same candidate set and
   assert the same public outcome. Record comparator call counts so an
   accidental extra comparison is visible.
9. **Worktree safety.** Tests must not commit, push, or rewrite unrelated files.
   This plan is documentation-only until the team agrees to implement the
   cases.

## 6. Case matrix

| ID | Scenario | Primary owner | Dependency | Existing evidence |
| --- | --- | --- | --- | --- |
| IT-01 | Valid Agent 1 handoff accepted end to end | Adapter + schema + service | `[A1-SIGNOFF]` | `test_full_handoff_payload_maps_to_complaint`, `test_kavach_agent1_context_is_ignored` |
| IT-02 | Adapter rejects malformed/ambiguous input before retrieval | Adapter + schema | `[A1-SIGNOFF]` | `test_raw_or_ambiguous_upstream_field_is_rejected`, validation tests |
| IT-03 | Empty retrieval is complete and yields `NEW` | Repository + service + policy | `[NO-DEP]`, `[RETRIEVAL-OPEN]` note | `test_empty_repository_returns_new` |
| IT-04 | Strong duplicate through the full pipeline | Comparators + engine + policy + service | `[NO-DEP]` | `test_clear_duplicate_returns_duplicate` |
| IT-05 | Review-required due to a disqualifying contradiction | Decision policy + service | `[NO-DEP]` | `test_explicit_contradiction_blocks_duplicate` |
| IT-06 | No-match with weak but sufficient evidence | Engine + policy + service | `[NO-DEP]` | `test_low_scoring_candidate_returns_new` |
| IT-07 | Repository failure propagates; never becomes `NEW` | Repository + service | `[NO-DEP]` | `test_repository_failure_propagates_and_is_never_new` |
| IT-08 | Comparator failure is isolated as an `ERROR` signal | Service + comparator + engine | `[POLICY-OPEN]` | `test_comparator_exception_becomes_error_signal` |
| IT-09 | Multiple candidates, deterministic ordering, ambiguity | Service + policy + engine | `[NO-DEP]`; `[A3-REQ]` if ranking is exposed later | `test_multiple_candidates_select_the_highest_score`, ordering tests |
| IT-10 | Response contract smoke test across decisions | Response schema + service | `[NO-DEP]` for shape; `[A3-REQ]` for consumption | Decision-policy response adaptation tests |
| IT-11 | Agent 3/Supervisor consumes the response | Agent 3/Supervisor + response schema | `[A3-REQ]` — blocked | None yet |

## 7. Detailed case specifications

### IT-01 — Valid Agent 1 handoff accepted end to end

**Input setup**

- Build a draft handoff envelope with:
  - a non-empty `complaint_id`;
  - a non-blank description;
  - a category;
  - a location containing either identifiers or a complete coordinate pair;
  - a timezone-aware `reported_at`;
  - optional `image_hash`;
  - optional `kavach_agent1` context.
- Call `to_complaint(payload)`.
- Pass the resulting `Complaint` to `DuplicateDetectionService.check()` with an
  empty fake repository and recording comparators.

**Expected behavior**

- `to_complaint()` returns a `Complaint`; no envelope or field validation error.
- The complaint ID and accepted optional values are preserved according to the
  current draft adapter behavior.
- `kavach_agent1` is dropped; it is not forwarded as a complaint field.
- The input payload is not mutated.
- The service accepts the `Complaint`, calls retrieval once with the complaint ID
  as `exclude_complaint_id`, and returns a response echoing that ID.
- With an empty repository, the response is `NEW` with no match and no score.
- The test must not assert final fallback semantics (text source, timestamp
  source, category source, location source, or image selection) until Agent 1
  signs off.

**Owning module**

`app/adapters/incident_payload.py` and `app/schemas/complaint.py`; the service
is the compatibility consumer.

**Dependency / status**

`[A1-SIGNOFF]`. This case can run against draft `a1-to-a2-draft-1`, but its
assertions are draft-contract evidence, not final contract validation.

**Existing evidence**

`tests/test_incident_payload_adapter.py`:
`test_full_handoff_payload_maps_to_complaint`,
`test_kavach_agent1_context_is_ignored`,
`test_kavach_agent1_is_optional`,
`test_minimal_payload_only_requires_complaint_id`,
`test_adapter_does_not_mutate_the_input_payload`.

### IT-02 — Adapter rejects malformed or ambiguous input before retrieval

**Input setup**

Use the valid handoff fixture as the control, then apply one mutation at a time.

| Mutation | Expected exception | Required assertion |
| --- | --- | --- |
| Payload is not a mapping | `IncidentPayloadError` | Message states a mapping is required; no `Complaint` is built. |
| Raw/ambiguous upstream key is added: `incident_id`, `complaint_text`, `incident_summary`, `created_at`, `submitted_at`, `incident_type`, `request_id`, or `image_ref` | `IncidentPayloadError` | Offending key appears in `unsupported_fields` and in the message. |
| Unknown top-level key is added | `IncidentPayloadError` | The key is rejected rather than silently ignored. |
| HTTP-only block such as `options` or `candidates` is added | `IncidentPayloadError` | The block is reported as unsupported. |
| `complaint_id` is missing, blank, or above the schema limit | Pydantic `ValidationError` | Field-level validation fails. |
| `reported_at` is naive or unparsable | Pydantic `ValidationError` | No timezone is guessed. |
| Only one coordinate is supplied | Pydantic `ValidationError` | Coordinates must be supplied together. |
| Coordinate is out of range, or location has an unknown field | Pydantic `ValidationError` | Invalid location is rejected. |
| A field exceeds its schema length limit | Pydantic `ValidationError` | Length validation is enforced. |
| Optional string is blank/whitespace-only | No exception | The value normalizes to `None`, not an invented value. |

**Expected behavior**

- Envelope-level problems raise `IncidentPayloadError`; field-level problems
  raise Pydantic `ValidationError`.
- Failure occurs before the service is called. No repository retrieval,
  comparator call, decision, or response is produced.
- The adapter never silently falls back from a rejected raw/ambiguous key.
- The blank-optional-string control remains valid and is not treated as a
  failure.

**Owning module**

`app/adapters/incident_payload.py` and `app/schemas/complaint.py`.

**Dependency / status**

`[A1-SIGNOFF]`. In particular, final unknown-field rejection policy and final
acceptance/rejection of raw upstream keys require Agent 1 agreement.

**Existing evidence**

`tests/test_incident_payload_adapter.py` includes validation tests for missing
and invalid IDs, timestamps, coordinates, location fields, field lengths,
unsupported fields, HTTP-only fields, and the blank-optional normalization
control.

### IT-03 — Empty retrieval is complete and yields `NEW`

**Input setup**

- Use a valid `Complaint`, preferably produced by the adapter.
- Fake repository returns an empty list.
- Recording comparators are configured.
- Add a second variant where the repository returns only the incoming complaint
  itself.

**Expected behavior**

- Retrieval is called once with the incoming ID as `exclude_complaint_id`.
- No comparator is called.
- The service passes `RetrievalStatus.COMPLETE` to the decision policy; an
  empty successful result is not a failure.
- Response: `decision=NEW`, `matched_incident_id=None`, `score=None`,
  `signals={}`, and `reasons` contains `NO_ELIGIBLE_CANDIDATES`.
- The response echoes the incoming `complaint_id`.

**Owning module**

`app/repositories/base.py` (contract), `app/services/detection_service.py`
(orchestration), `app/scoring/decision_policy.py` (empty-retrieval decision).

**Dependency / status**

`[NO-DEP]` for the fake-repository behavior. `[RETRIEVAL-OPEN]`: production
retrieval completeness and failure classification are not finalized, so the
test must not claim that all production empty results are complete.

**Existing evidence**

`tests/test_detection_service.py::test_empty_repository_returns_new`;
self-only handling is covered by
`test_self_candidate_is_skipped_even_if_repository_returns_it`.

### IT-04 — Strong duplicate through the full pipeline

**Input setup**

- Incoming complaint produced by the adapter from a valid handoff envelope.
- Fake repository returns one eligible candidate with a distinct ID.
- Fake comparators return a strong result for all four core signals
  (`text`, `location`, `category`, `time`). Reuse the deterministic
  `_strong_signals()` fixture from the existing service tests, or derive
  equivalent values that clear the configured evidence gates.
- The candidate must not be the incoming complaint.

**Expected behavior**

- The engine produces a numeric score for the candidate.
- The decision policy returns `DUPLICATE`.
- `matched_incident_id` is the candidate ID.
- `score` is non-null, in `[0, 1]`, and at or above the configured high
  threshold; assert against `settings.thresholds.high`, not a literal.
- `reasons` contains `SCORE_ABOVE_HIGH_THRESHOLD`.
- `signals` contains the core signals with `AVAILABLE` status and scores.
- Each configured comparator is called exactly once for the candidate.
- The response validates as `DuplicateDetectionResponse`.

**Owning module**

Comparators, `app/scoring/engine.py`, `app/scoring/decision_policy.py`, and
`app/services/detection_service.py`; the adapter owns the incoming conversion.

**Dependency / status**

`[NO-DEP]` for the pipeline behavior. `[A1-SIGNOFF]` applies only to the
handoff payload used to create the incoming complaint.

**Existing evidence**

`tests/test_detection_service.py::test_clear_duplicate_returns_duplicate`.

### IT-05 — Review-required due to a disqualifying contradiction

**Input setup**

- Incoming complaint from the adapter or a direct valid `Complaint`.
- One candidate with otherwise strong evidence, but its location signal carries
  an explicit conflict (for example, `details["conflict"] is True` with a
  conflict code), or the candidate is supplied to the policy seam with an
  explicit contradiction code.
- Ensure the candidate passes the minimum-evidence and core-anchor gates so the
  contradiction gate, not an evidence-sufficiency gate, determines the outcome.

**Expected behavior**

- Decision is `REVIEW_REQUIRED`.
- `matched_incident_id` is `None`; no match is asserted.
- `score` is the leading candidate's ranking score (non-null in the current
  implementation) and equals the M3 result for that candidate; it is not a
  probability.
- `reasons` contains `CONTRADICTION_LOCATION_MISMATCH` (or the relevant
  contradiction code).
- The contradiction details are preserved in the returned signals.
- The public response does not identify the leading candidate for review; do not
  add or assert a candidate field.

**Owning module**

`app/scoring/decision_policy.py` (contradiction gate and review outcome);
`app/services/detection_service.py` (response mapping); comparators provide the
conflict details.

**Dependency / status**

`[NO-DEP]` for current behavior. Policy thresholds and gates remain
provisional; derive expectations from `Settings` and the policy result.

**Existing evidence**

`tests/test_detection_service.py::test_explicit_contradiction_blocks_duplicate`
and the contradiction cases in `tests/test_decision_policy.py`.

### IT-06 — No-match with weak but sufficient evidence

**Input setup**

- Incoming valid `Complaint`.
- One candidate with all four core signals `AVAILABLE`, but with a combined
  weighted score below the configured low threshold.
- The candidate must still pass the evidence gates (minimum available signals,
  core anchor, and corroboration). A candidate that fails those gates is a
  review case, not a no-match case.
- Reuse the deterministic `_weak_signals()` fixture from the existing service
  tests, or derive equivalent values from the configured floors.

**Expected behavior**

- Decision is `NEW`.
- `matched_incident_id` is `None`.
- `score` is `None`; a below-threshold candidate does not produce a public
  match score.
- `reasons` contains `SCORE_BELOW_LOW_THRESHOLD`.
- The best candidate's signals are still returned for auditability.
- Retrieval is complete, so no retrieval-incomplete reason appears.

**Owning module**

`app/scoring/engine.py`, `app/scoring/decision_policy.py`, and
`app/services/detection_service.py`.

**Dependency / status**

`[NO-DEP]` for current behavior. If provisional policy defaults change, the
fixture may no longer be a no-match case; the test must re-derive the expected
decision from the configured gates and thresholds.

**Existing evidence**

`tests/test_detection_service.py::test_low_scoring_candidate_returns_new`.

### IT-07 — Repository failure propagates and is never `NEW`

**Input setup**

- Valid incoming `Complaint`.
- Fake repository raises `RepositoryError` from `list_candidates()`.
- Add contract-violation variants: returns a non-iterable, or returns an
  iterable containing a non-`Complaint` object.

**Expected behavior**

- `RepositoryError` propagates to the caller.
- No `DuplicateDetectionResponse` is produced.
- No comparator is called.
- The service never converts retrieval failure into `NEW`, `REVIEW_REQUIRED`, or
  `DUPLICATE`.
- Transport-level error mapping remains the future edge's responsibility and is
  not asserted here.

**Owning module**

`app/repositories/base.py` and `app/services/detection_service.py`.

**Dependency / status**

`[NO-DEP]`. The HTTP error contract and endpoint path are out of scope.

**Existing evidence**

`tests/test_detection_service.py::test_repository_failure_propagates_and_is_never_new`;
candidate-contract violations are covered by the service's defensive tests.

### IT-08 — Comparator failure is isolated as an `ERROR` signal

**Input setup**

- Valid incoming `Complaint` and one eligible candidate.
- One comparator raises an exception (for example, the text comparator).
- Other comparators return strong or controlled results.
- Add a malformed-result variant where a comparator returns something other
  than a `SignalResult`.

**Expected behavior**

- The service completes and returns a `DuplicateDetectionResponse`; the
  comparator exception does not escape.
- The failing signal has `status=ERROR`, `score=None`, and a reason beginning
  with `SIGNAL_ERROR_` (currently `SIGNAL_ERROR_TEXT` for the text comparator).
- Error details identify the failure type without inventing a similarity score.
- The scoring engine excludes the `ERROR` signal from the weighted numerator and
  denominator; it is not treated as zero.
- Other signals remain available and are scored normally.
- With strong remaining evidence, the current pipeline can still return
  `DUPLICATE`; assert the decision produced by the configured policy rather than
  assuming an `ERROR` always forces a particular decision.

**Owning module**

`app/services/detection_service.py` (exception isolation),
`app/comparators/base.py` (signal contract), and `app/scoring/engine.py`
(non-available signal handling); the decision policy consumes the result.

**Dependency / status**

`[POLICY-OPEN]`: whether an `ERROR` signal should force `REVIEW_REQUIRED`
instead of allowing `NEW` when other evidence is weak is still pending mentor
approval. The test should record current behavior and not encode a final policy
answer.

**Existing evidence**

`tests/test_detection_service.py::test_comparator_exception_becomes_error_signal`,
`test_embedding_error_is_preserved_and_not_treated_as_zero`, and
`test_embedding_error_can_still_return_new_with_weak_other_evidence`.

### IT-09 — Multiple candidates, deterministic ordering, and ambiguity

**Input setup**

- Incoming valid `Complaint`.
- Three eligible candidates:
  - A: strong evidence;
  - B: moderate evidence;
  - C: weak evidence.
- Repository returns them in a non-ranked order (for example, C, B, A).
- Run a second variant with the same candidates in a different order.
- Add an ambiguity variant with two candidates whose top scores differ by less
  than `settings.tie_margin`.
- Add defensive subcases where the repository includes the incoming complaint
  or duplicate candidate IDs.

**Expected behavior**

- The service compares each eligible candidate exactly once per configured
  comparator; no candidate is skipped or compared twice.
- Candidate A wins on score; the public response is `DUPLICATE` with
  `matched_incident_id=A`.
- The same candidate set in a different repository order produces the same
  decision, matched ID, score, and reasons.
- Self candidates are excluded before comparison.
- Duplicate candidate IDs keep the first record and do not cause a second
  comparison.
- For the ambiguity variant, the policy returns `REVIEW_REQUIRED` with
  `AMBIGUOUS_TIED_CANDIDATES`; `matched_incident_id` is `None`.
- The current public response does not expose the ranked candidate list. Verify
  ranking and tie ordering through `DecisionPolicy.decide()` and its
  `DecisionOutcome.candidates` only; do not add a public field for this test.

**Owning module**

`app/services/detection_service.py` (eligible-candidate selection and call
counts), `app/scoring/decision_policy.py` (ranking, tie-breakers, ambiguity),
and `app/scoring/engine.py` (per-candidate scores).

**Dependency / status**

`[NO-DEP]` for current internal behavior. If Agent 3/Supervisor later requires
ranked candidates in the response, that is a separate `[A3-REQ]` contract change
and must not be smuggled into this test.

**Existing evidence**

`tests/test_detection_service.py::test_multiple_candidates_select_the_highest_score`,
`test_self_candidate_is_skipped_even_if_repository_returns_it`,
`test_duplicate_candidate_ids_keep_the_first_record_and_compare_once`; ordering
and ambiguity coverage in `tests/test_decision_policy.py`.

### IT-10 — Response contract smoke test across decisions

**Input setup**

- Collect responses produced by IT-03 (`NEW`), IT-04 (`DUPLICATE`), IT-05 or
  IT-09 (`REVIEW_REQUIRED`).
- Serialize each response with the project's normal Pydantic JSON mode.

**Expected behavior**

- The response contains only the currently exposed fields: `complaint_id`,
  `decision`, `matched_incident_id`, `score`, `signals`, and `reasons`.
- `decision` is one of `DUPLICATE`, `REVIEW_REQUIRED`, or `NEW`.
- `DUPLICATE` has a non-null `matched_incident_id` and a non-null `score`.
- `NEW` has a null `matched_incident_id` and null `score`.
- `REVIEW_REQUIRED` has a null `matched_incident_id` in the current
  representation; its score may be the leading candidate's ranking score.
- Every non-`AVAILABLE` signal has a null score.
- `score`, when present, is finite and within `[0, 1]`.
- `reasons` is a list of strings; unknown reason codes are additive and must not
  be rejected by the producer.
- Serialization round-trips without adding undocumented fields.
- The test does not require `candidates`, `policy_version`, `request_id`, or any
  other deferred block.

**Owning module**

`app/schemas/duplicate_response.py` and `app/services/detection_service.py`.

**Dependency / status**

`[NO-DEP]` for the current shape. `[A3-REQ]` applies to whether this shape is
sufficient for downstream use.

**Existing evidence**

Decision-policy response-adaptation tests and schema validation tests.

### IT-11 — Agent 3/Supervisor consumes the response

**Input setup**

- Use the same response objects and JSON payloads as IT-10.
- Do not create a fake endpoint path or a new shared schema.

**Expected behavior (provisional smoke only)**

- Agent 3/Supervisor can receive the response object or its JSON form.
- It can read `decision`, `matched_incident_id`, `score`, `signals`, and
  `reasons`.
- The response documents `score` as a ranking score; consumer assertions must
  not reinterpret it as a calibrated probability.
- The response documents `reasons` as an open, additive set; consumer assertions
  must not reject unknown codes solely because they are new.
- The producer does not expose ranked candidates, policy version, request ID, or
  a leading-candidate ID; the consumer test must not assume they are available.
- The consumer test must not assume that `REVIEW_REQUIRED` identifies the
  candidate that triggered review.

**Blocked assertions**

The following cannot be tested until Agent 3/Supervisor supplies requirements:

- which decisions are accepted, rejected, or escalated;
- how a review is routed or assigned;
- whether the consumer needs a leading candidate ID;
- whether the consumer needs ranked candidates, signal details, or policy
  metadata;
- transport, retry, idempotency, and audit requirements;
- exact downstream field names or mappings.

**Owning module**

Agent 3/Supervisor consumer, with `app/schemas/duplicate_response.py` as the
producer boundary.

**Dependency / status**

`[A3-REQ]` — blocked. Until requirements arrive, only the IT-10 schema smoke
test may be implemented; downstream behavior must remain unspecified.

## 8. Cross-case invariants

- Adapter failures occur before retrieval; repository failures occur before
  comparison and never become a business decision.
- A successful empty retrieval is `COMPLETE`; it is not a retrieval failure.
- Comparator exceptions are isolated into `ERROR` signals with null scores.
- The scoring engine never treats missing, invalid, or error evidence as zero.
- The decision policy applies evidence gates before threshold bands; a weak
  candidate with insufficient evidence is a review, not `NEW`.
- The public response exposes only the current six fields; internal ranking and
  policy version remain internal.
- Candidate order in the repository must not change the public outcome for the
  same candidate set.
- No test may mutate production settings, thresholds, weights, mappings, or
  other agents' code.

## 9. Open questions

### Agent 1 handoff contract (`[A1-SIGNOFF]`)

| # | Current draft behavior | Question to resolve |
| --- | --- | --- |
| A1-1 | Adapter targets `a1-to-a2-draft-1`. | What is the final contract version, and who signs it off? |
| A1-2 | `reported_at` is the accepted timestamp key; raw `submitted_at`/`created_at` are rejected at the adapter. | Which upstream timestamp is authoritative, and what fallback is final? |
| A1-3 | `description` is the accepted text key; raw `complaint_text`/`incident_summary` are rejected. | Which text source is final, and may a summary ever substitute? |
| A1-4 | `category` is the accepted category key; raw `incident_type` is rejected. | Is category the incident type, the department category, or a normalized value? How is `UNKNOWN` represented? |
| A1-5 | `location` is the accepted location object. | Which location source/facility identifiers are authoritative, and how are partial coordinates handled? |
| A1-6 | `image_hash` is optional. | Which image is selected when several are accepted, and is the first-image rule final? |
| A1-7 | `kavach_agent1` is optional and ignored; its version is not enforced. | Must the context be mandatory, and must the adapter enforce a version? |
| A1-8 | Unknown top-level and raw/ambiguous keys are rejected. | Is rejection the final policy, or should some unknown fields be ignored/forwarded? |

### Agent 3/Supervisor consumption (`[A3-REQ]`)

| # | Current producer behavior | Question to resolve |
| --- | --- | --- |
| A3-1 | Response is an in-process Pydantic object; HTTP is deferred. | Does Agent 3/Supervisor consume the object, JSON, or an HTTP endpoint? No path is assumed here. |
| A3-2 | Only six fields are exposed. | Are those fields sufficient? Does the consumer need ranked candidates, policy version, request ID, or a leading-candidate ID? |
| A3-3 | `REVIEW_REQUIRED` has no matched ID and no leading-candidate field. | How should the consumer route a review without knowing which candidate triggered it? |
| A3-4 | `score` is a ranking score, not a probability. | What score semantics, thresholds, or confidence handling does the consumer require? |
| A3-5 | `reasons` is an open, additive set. | Which reason codes must be understood, and what is the fallback for unknown codes? |
| A3-6 | Retrieval failures propagate as exceptions; no response is produced. | What retry/error/audit behavior does the consumer require? |

### Cross-cutting policy and retrieval questions

| # | Current behavior | Question to resolve |
| --- | --- | --- |
| X-1 | The service always passes `RetrievalStatus.COMPLETE` after a successful repository call. | How should production retrieval report incomplete or failed searches? |
| X-2 | A text/embedding `ERROR` can still allow `NEW` when other evidence is weak. | Should an `ERROR` signal force `REVIEW_REQUIRED`? This is pending mentor approval. |
| X-3 | `REVIEW_REQUIRED` responses omit the leading candidate. | Is exposing a leading candidate for review required, and if so, under what contract? |
| X-4 | Thresholds, weights, and mappings are provisional. | When will they be calibrated and frozen, and which tests become policy-validation tests at that point? |
| X-5 | No endpoint path is implemented in this plan. | What transport and error contract will the future edge expose? |

## 10. Execution and reporting

### Commands

Focused suites:

```text
python -m pytest tests/test_incident_payload_adapter.py tests/test_detection_service.py tests/test_scoring_engine.py tests/test_decision_policy.py -q
```

Full suite:

```text
python -m pytest -q
```

### Baseline results

Baseline recorded on 2026-10-30:

- Focused suites: **138 passed in 2.01s**.
- Full suite: **379 passed in 2.79s**.

These are baseline results for existing tests. The integration cases in this
plan are not yet implemented; IT-11 remains blocked on `[A3-REQ]`.

### Exit criteria

- Existing focused and full suites pass.
- When implemented, IT-01 through IT-10 pass.
- IT-11 is either implemented against agreed Agent 3/Supervisor requirements or
  explicitly skipped with the `[A3-REQ]` reason.
- No production service, scoring, decision-policy, schema, threshold, weight, or
  mapping change is required to make the tests pass.
- Open questions are resolved or explicitly accepted as known limitations.
- No commit or push is performed as part of test-plan work.
