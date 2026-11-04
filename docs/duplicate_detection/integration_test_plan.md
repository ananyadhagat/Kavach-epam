# Duplicate Detection M2 → M3 → M4 Integration Test Plan

> **Status:** mixed implementation/planning artifact. IT-01 through IT-12 have
> executable evidence at the levels listed in §6; IT-11 remains blocked on
> Agent 3/Supervisor sign-off. This document does not change production logic,
> scoring, decision policy, thresholds, weights or field mappings.
>
> **Transport:** the M3 HTTP edge is implemented at
> `POST /internal/v1/duplicate-detection/check` and documented in
> [`m3_http_contract.md`](./m3_http_contract.md). The in-process pipeline remains
> the primary test surface; HTTP tests inject a deterministic service double.
>
> **Contract dependencies:** cases marked `[A1-SIGNOFF]` depend on Agent 1's
> final handoff contract; cases marked `[A3-REQ]` depend on Agent 3/Supervisor
> response requirements. Open items are listed in §9.
>
> **Contract evidence (2026-11-01):** the two payloads published in the draft
> `a1-to-a2-draft-1` contract are now exact fixtures. IT-01 and the adapter →
> service cases pass against them, but they remain `[A1-SIGNOFF]` draft
> evidence, not final contract validation.
>
> **M3 HTTP evidence (2026-11-02):** the Agent 3 eleven-field response contract,
> decision/processing-status mapping, partial/failed `200` behavior and HTTP
> error mapping are covered by `tests/test_m3_http.py` and
> `tests/test_detection_service_detailed.py`.

## 1. Objective

Verify that a complaint can move through the complete duplicate-detection seam:

```text
Agent 1 handoff envelope
        │
        ▼
M2 input adapter ──► Complaint
        │
        ▼
candidate retrieval (explicit completeness)
        │
        ▼
comparators ──► M3 weighted scoring ──► M4 decision policy
        │
        ▼
DetectionResult ──► internal six-field response
        │
        ▼
M3 HTTP mapper ──► Agent 3 eleven-field response ──► Supervisor
```

The tests should prove four things:

1. Each boundary accepts only the input it is designed to accept.
2. Failures at a boundary are explicit and are not silently converted into a
   business decision.
3. The internal response and the Agent 3 wire response each remain stable for
   their consumers.
4. Partial or failed candidate retrieval is never reported as `NEW` or as a
   confirmed `DUPLICATE`.

## 2. Scope and non-goals

### In scope

- Agent 1 handoff envelope → `Complaint` via
  [`app/adapters/incident_payload.py`](../../app/adapters/incident_payload.py).
- `Complaint` → `DuplicateDetectionResponse` via
  [`app/services/detection_service.py`](../../app/services/detection_service.py).
- `Complaint` → `DetectionResult` → Agent 3 response via
  [`app/api/`](../../app/api) and
  [`app/schemas/m3_response.py`](../../app/schemas/m3_response.py).
- Retrieval through the `ComplaintRepository` contract, including explicit
  completeness (`COMPLETE`/`PARTIAL`/`FAILED`).
- Comparator results, M3 scoring, and M4 decision gates.
- Internal and Agent 3 response shapes and invariants.
- A provisional downstream-consumption smoke test for Agent 3/Supervisor.

### Out of scope

- Finalizing or expanding shared schemas.
- Redesigning comparators, weighted scoring, decision policy or thresholds.
- Real embedding-model, network, database, or vector-store calls in tests.
- Changes to Agent 1 or Agent 3/Supervisor code.
- Declaring current provisional policy values to be final.

## 3. Test levels and ownership

| Level | What it exercises | Owning module |
| --- | --- | --- |
| Adapter contract | Handoff envelope → `Complaint`, including rejection paths | `app/adapters/incident_payload.py`, `app/schemas/complaint.py` |
| Service integration | `Complaint` → retrieval → comparators → engine → policy → response | `app/services/detection_service.py` |
| Retrieval completeness | `CandidateRetrieval` → `DetectionResult` / `RetrievalStatus` | `app/repositories/base.py`, `app/services/detection_service.py` |
| Policy seam | `CandidateScore` → `DecisionOutcome` ranking, gates, ambiguity | `app/scoring/decision_policy.py` |
| Internal response contract | `DuplicateDetectionResponse` shape and invariants | `app/schemas/duplicate_response.py` |
| M3 HTTP edge | Agent 1 JSON → Agent 3 eleven-field response, statuses and errors | `app/api/`, `app/schemas/m3_response.py` |
| Consumer contract | Agent 3 response JSON consumed by Supervisor | Agent 3/Supervisor, with `app/schemas/m3_response.py` as the producer boundary |

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

1. **Handoff fixtures.** Use the two payloads published in the draft contract,
   reproduced verbatim in `tests/conftest.py`:
   `complete_contract_payload` (`INC-2026-001`, full `kavach_agent1` context)
   and `minimal_contract_payload` (`INC-2026-002`, all-null coordinates and
   `image_hash`). Both fixtures return deep copies. They use the canonical keys
   the current adapter accepts; raw `StructuredIncidentRecord` names belong only
   in rejection cases. Additional representative fixtures may be built, but they
   must not add invented mappings. Deep-copy a payload before mutating it in a
   rejection case and assert the original fixture was not mutated. Both fixtures
   include a `kavach_agent1` context object; nested content is tolerated.
2. **Incoming complaint source.** For cases that claim to cover Agent 1 input,
   construct the incoming `Complaint` through `to_complaint()` rather than
   instantiating it directly. For boundary-specific cases, a direct `Complaint`
   is acceptable and should be stated.
3. **Repository double.** Use a fake `ComplaintRepository` that records
   `exclude_complaint_id`, returns a controlled list, or raises
   `RepositoryError`. For `check_detailed()`/M3 cases, override
   `retrieve_candidates()` to return a `CandidateRetrieval` with an explicit
   `RetrievalOutcome` (`COMPLETE`, `PARTIAL`, or `FAILED`) instead of relying on
   the base class's safe `PARTIAL` default.
4. **Comparator double.** Use mapping-based fake comparators keyed by candidate
   ID. Each comparator returns a `SignalResult`; at least one case raises an
   exception and one returns a malformed value.
5. **No hardcoded policy values.** Derive expectations from the active
   `Settings` (for example, `settings.thresholds.high`,
   `settings.thresholds.low`, and `settings.tie_margin`) or from the M3 engine
   result. Do not copy current defaults into the integration plan as final
   values.
6. **No invented mappings.** Use the draft fields already accepted by the
   adapter. Do not add raw upstream fields, response fields outside the agreed
   contract, or endpoint paths. The only implemented path is
   `POST /internal/v1/duplicate-detection/check`; tests must not invent
   additional routes.
7. **Public assertions first.** Assert the internal
   `DuplicateDetectionResponse` for in-process `check()` cases and the Agent 3
   `M3DuplicateCheckResponse` for IT-12, unless a case explicitly says it is a
   policy-seam test. Internal candidate ranking is not part of the internal
   six-field contract; the Agent 3 contract exposes candidates separately.
8. **Determinism.** Run candidate-order variants with the same candidate set and
   assert the same public outcome. Record comparator call counts so an
   accidental extra comparison is visible.
9. **Worktree safety.** Tests must not commit, push, or rewrite unrelated files.
   Cases listed with existing evidence are already implemented; the remaining
   cases stay documentation-only until the team agrees to implement them.

## 6. Case matrix

| ID | Scenario | Primary owner | Dependency | Existing evidence |
| --- | --- | --- | --- | --- |
| IT-01 | Valid Agent 1 handoff accepted end to end | Adapter + schema + service | `[A1-SIGNOFF]` | `test_complete_contract_payload_maps_to_complaint`, `test_minimal_contract_payload_maps_to_complaint`, `test_contract_payload_reaches_service_and_empty_retrieval_is_new` |
| IT-02 | Adapter rejects malformed/ambiguous input before retrieval | Adapter + schema | `[A1-SIGNOFF]` | `test_unknown_top_level_field_on_contract_payload_is_rejected`, `test_unknown_nested_kavach_agent1_fields_are_ignored`, `test_contract_version_is_not_enforced`, `test_non_finite_coordinate_is_rejected`, `test_raw_or_ambiguous_upstream_field_is_rejected`, validation tests |
| IT-03 | Empty retrieval is complete and yields `NEW` | Repository + service + policy | `[NO-DEP]`, `[RETRIEVAL-OPEN]` note | `test_empty_repository_returns_new` |
| IT-04 | Strong duplicate through the full pipeline | Comparators + engine + policy + service | `[NO-DEP]` | `test_clear_duplicate_returns_duplicate` |
| IT-05 | Review-required due to a disqualifying contradiction | Decision policy + service | `[NO-DEP]` | `test_explicit_contradiction_blocks_duplicate` |
| IT-06 | No-match with weak but sufficient evidence | Engine + policy + service | `[NO-DEP]` | `test_low_scoring_candidate_returns_new` |
| IT-07 | Repository failure propagates; never becomes `NEW` | Repository + service | `[NO-DEP]` | `test_repository_failure_propagates_and_is_never_new` |
| IT-08 | Comparator failure is isolated as an `ERROR` signal | Service + comparator + engine | `[POLICY-OPEN]` | `test_comparator_exception_becomes_error_signal` |
| IT-09 | Multiple candidates, deterministic ordering, ambiguity | Service + policy + engine | `[NO-DEP]`; `[A3-REQ]` if ranking is exposed later | `test_multiple_candidates_select_the_highest_score`, ordering tests |
| IT-10 | Response contract smoke test across decisions | Response schema + service | `[NO-DEP]` for shape; `[A3-REQ]` for consumption | Decision-policy response adaptation tests |
| IT-11 | Agent 3/Supervisor consumes the response | Agent 3/Supervisor + response schema | `[A3-REQ]` — blocked | None yet |
| IT-12 | M3 HTTP edge maps results and failures to the Agent 3 contract | HTTP edge + mapper + service + repository | `[NO-DEP]` for producer behavior; `[A3-REQ]` for consumer acceptance | `tests/test_m3_http.py`, `tests/test_detection_service_detailed.py`, retrieval tests in `tests/test_repository.py` |

## 7. Detailed case specifications

### IT-01 — Valid Agent 1 handoff accepted end to end

**Input setup**

- Start from `complete_contract_payload` (`INC-2026-001`) or
  `minimal_contract_payload` (`INC-2026-002`) in `tests/conftest.py`. Both are
  verbatim copies of the payloads published in draft `a1-to-a2-draft-1`.
- The complete fixture has a non-empty `complaint_id`, a description, a
  category, a complete coordinate pair, a timezone-aware `reported_at`, an
  `image_hash`, and full `kavach_agent1` context. The minimal fixture keeps all
  top-level keys but uses an all-null location and `image_hash`, with only
  `contract_version` in `kavach_agent1`.
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
`test_complete_contract_payload_maps_to_complaint`,
`test_minimal_contract_payload_maps_to_complaint`,
`test_complete_contract_payload_is_not_mutated`,
`test_kavach_agent1_is_optional`,
`test_minimal_payload_only_requires_complaint_id`,
`test_adapter_does_not_mutate_the_input_payload`.

`tests/test_detection_service.py`:
`test_contract_payload_reaches_service_and_empty_retrieval_is_new` (both
published payloads), `test_contract_payload_can_match_an_existing_candidate`
(complete payload through the full pipeline).

### IT-02 — Adapter rejects malformed or ambiguous input before retrieval

**Input setup**

Start from `complete_contract_payload` (`INC-2026-001`) in `tests/conftest.py` as
the control, then apply one mutation at a time to a deep copy.

| Mutation | Expected exception | Required assertion |
| --- | --- | --- |
| Payload is not a mapping | `IncidentPayloadError` | Message states a mapping is required; no `Complaint` is built. |
| Raw/ambiguous upstream key is added: `incident_id`, `complaint_text`, `incident_summary`, `created_at`, `submitted_at`, `incident_type`, `request_id`, or `image_ref` | `IncidentPayloadError` | Offending key appears in `unsupported_fields` and in the message. |
| Unknown top-level key is added | `IncidentPayloadError` | The key is rejected rather than silently ignored. |
| Unknown nested `kavach_agent1` field is added | No exception | The entire context object is ignored. |
| `kavach_agent1.contract_version` differs from the adapter constant | No exception | Version enforcement is not yet defined. |
| HTTP-only block such as `options` or `candidates` is added | `IncidentPayloadError` | The block is reported as unsupported. |
| `complaint_id` is missing, blank, or above the schema limit | Pydantic `ValidationError` | Field-level validation fails. |
| `reported_at` is naive or unparsable | Pydantic `ValidationError` | No timezone is guessed. |
| Only one coordinate is supplied | Pydantic `ValidationError` | Coordinates must be supplied together. |
| Coordinate is out of range, non-finite (NaN/inf), or location has an unknown field | Pydantic `ValidationError` | Invalid location is rejected. |
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

`[A1-SIGNOFF]`. The current behavior is implemented and tested, but these
receiver-side rules remain provisional: unknown top-level rejection, optional
and unversioned `kavach_agent1`, required-field/nullability rules, and
partial-coordinate rejection. They are listed in
`docs/duplicate_detection/m2_input_adapter.md` section "Receiver-side rules
(provisional)" and in §9.

**Existing evidence**

`tests/test_incident_payload_adapter.py` mutates the shared contract fixture and
covers:
`test_unknown_top_level_field_on_contract_payload_is_rejected`,
`test_unknown_nested_kavach_agent1_fields_are_ignored`,
`test_contract_version_is_not_enforced`,
`test_non_finite_coordinate_is_rejected`, plus validation tests for missing and
invalid IDs, timestamps, coordinates, location fields, field lengths,
unsupported/raw upstream fields, HTTP-only fields, and the blank-optional
normalization control.

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

`tests/test_detection_service.py::test_empty_repository_returns_new` and
`test_contract_payload_reaches_service_and_empty_retrieval_is_new` (both
published contract payloads through the adapter); self-only handling is covered
by `test_self_candidate_is_skipped_even_if_repository_returns_it`.

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

`tests/test_detection_service.py::test_clear_duplicate_returns_duplicate` and
`test_contract_payload_can_match_an_existing_candidate` (complete contract
payload through the adapter into the full pipeline).

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
- Fake repository raises `RepositoryError` from `list_candidates()` (the
  `check()` path) and from `retrieve_candidates()` (the
  `check_detailed()`/M3 path).
- Add contract-violation variants: returns a non-iterable, or returns an
  iterable containing a non-`Complaint` object.

**Expected behavior**

- `check()`: `RepositoryError` propagates to the caller; no
  `DuplicateDetectionResponse` is produced and no comparator is called.
- `check_detailed()`: a `RepositoryError` becomes a `FAILED` retrieval result
  with the error's `code`; the decision policy returns `REVIEW_REQUIRED`, never
  `NEW` or `DUPLICATE`.
- The M3 HTTP edge returns `200` with `processing_status=FAILED`,
  `decision=REVIEW_REQUIRED`, an `error` object and
  `CANDIDATE_RETRIEVAL_FAILED` in `reason_codes`. The full HTTP assertions live
  in IT-12.
- No path converts a retrieval failure into a confirmed match or an unqualified
  `NEW`.

**Owning module**

`app/repositories/base.py`, `app/services/detection_service.py`, and
`app/api/mapper.py`.

**Dependency / status**

`[NO-DEP]`. The internal propagation behavior and the M3 `200 + FAILED`
representation are both implemented. Invalid-payload and timeout mapping are
asserted separately in IT-12.

**Existing evidence**

`tests/test_detection_service.py::test_repository_failure_propagates_and_is_never_new`;
`tests/test_detection_service_detailed.py::test_repository_failure_becomes_failed_review_not_new`
and `test_malformed_retrieval_result_becomes_failed`;
`tests/test_m3_http.py::test_failed_retrieval_is_200_review_required_with_error`.
Candidate-contract violations are covered by the service's defensive tests.

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
- The test does not require `candidates`, `policy_version`, `check_id`,
  `processing_status`, `checked_at`, `error`, or any other Agent 3 field. Those
  belong to the separate eleven-field wire contract exercised by IT-12.
- This case covers the internal six-field response only. Do not merge the
  internal and Agent 3 shapes into one schema.

**Owning module**

`app/schemas/duplicate_response.py` and `app/services/detection_service.py`.

**Dependency / status**

`[NO-DEP]` for the current shape. `[A3-REQ]` applies to whether this shape is
sufficient for downstream use.

**Existing evidence**

Decision-policy response-adaptation tests and schema validation tests.

### IT-11 — Agent 3/Supervisor consumes the response

**Input setup**

- Use the Agent 3 wire payloads produced by IT-12 and, for the internal path, the
  six-field responses from IT-10.
- Do not create a fake endpoint path or a new shared schema. The implemented path
  is `POST /internal/v1/duplicate-detection/check`; the schema is
  `app/schemas/m3_response.py`.

**Expected behavior (provisional smoke only)**

- Agent 3/Supervisor can receive the Agent 3 JSON response and read the eleven
  documented fields.
- It can read `decision`, `processing_status`, `matched_incident_id`, `score`,
  `candidates`, `reason_codes`, and `error`.
- The response documents `score` and candidate `similarity_score` as ranking /
  similarity values, not calibrated probabilities; consumer assertions must not
  reinterpret them as confidence.
- The response documents `reason_codes` and candidate `reason_codes` as open,
  additive sets; consumer assertions must not reject unknown codes solely because
  they are new.
- `candidates` contains only candidates that completed retrieval and scoring;
  the consumer must not treat an absent candidate as evidence that no incident
  exists.
- `processing_status=PARTIAL` or `FAILED` means the result is not exhaustive;
  the consumer must not treat `NEW` as possible in those states, because the
  producer forces `REVIEW_REQUIRED`.
- `error` is present exactly for `PARTIAL`/`FAILED`; a completed result has
  `error=null`.
- The consumer must not assume that `matched_incident_id` is a UUID. Agent 1
  incident IDs are opaque strings and the producer documents this deviation.

**Blocked assertions**

The following cannot be tested until Agent 3/Supervisor supplies consumer-side
requirements, even though the producer wire contract is now specified:

- which decisions and processing statuses are accepted, rejected, or escalated;
- how a review is routed or assigned;
- whether the consumer requires the leading candidate, all candidates, candidate
  `signals`, or policy metadata beyond the eleven fields;
- how the consumer handles `PARTIAL`/`FAILED` versus transport 5xx/504;
- transport, retry, idempotency, and audit requirements;
- exact downstream field names or mappings;
- final sign-off that `b92.md` is the authoritative contract and that opaque
  incident IDs are acceptable.

**Owning module**

Agent 3/Supervisor consumer, with `app/schemas/m3_response.py` as the producer
boundary and `app/api/` as the transport.

**Dependency / status**

`[A3-REQ]` — blocked on consumer-side sign-off. Until requirements arrive, only
the producer-side IT-12 contract tests may be implemented; downstream behavior
must remain unspecified.

### IT-12 — M3 HTTP edge maps results and failures to the Agent 3 contract

**Input setup**

- Build the app with `create_app(service=...)`, injecting a deterministic
  `DetailedDetectionService` double that returns a controlled `DetectionResult`.
  Use `fastapi.testclient.TestClient`.
- Send the Agent 1 contract fixture from `tests/conftest.py`, or a minimal valid
  envelope, to `POST /internal/v1/duplicate-detection/check`.
- Cover these result variants:
  1. `COMPLETE` retrieval with one strong candidate → `DUPLICATE`;
  2. `COMPLETE` retrieval with only below-threshold candidates → `NEW`;
  3. `COMPLETE` retrieval with a borderline/contradictory candidate →
     `REVIEW_REQUIRED`;
  4. `PARTIAL` retrieval with at least one scored candidate;
  5. `PARTIAL` retrieval with no scored candidate;
  6. `FAILED` retrieval with a `RetrievalFailure`;
  7. malformed Agent 1 payload, unknown field, non-mapping JSON, malformed JSON,
     and missing body;
  8. service `TimeoutError`;
  9. any other unexpected service exception;
  10. the default app with an empty in-memory repository.
- For candidate-order and null-score cases, return candidates in a non-ranked
  order and include one candidate whose internal score is `None`.

**Expected behavior**

- Every successful duplicate check returns exactly the eleven Agent 3 fields:
  `check_id`, `incident_id`, `decision`, `processing_status`, `policy_version`,
  `checked_at`, `matched_incident_id`, `score`, `reason_codes`, `candidates`,
  `error`. Optional values are `null`, never omitted.
- `decision` is one of `NEW`, `DUPLICATE`, `REVIEW_REQUIRED`;
  `processing_status` is one of `COMPLETED`, `PARTIAL`, `FAILED`.
- `check_id` is a UUID generated per request; `checked_at` is a UTC ISO-8601
  timestamp with a trailing `Z`.
- `score` and every candidate `similarity_score` are finite and in `[0, 1]`;
  they are similarity/ranking values, not probabilities.
- `candidates` are ordered by descending `similarity_score`; candidates with a
  `None` score are omitted; candidate `signals` is absent because it is optional
  and not carried by the internal ranking.
- `NEW` forces `matched_incident_id=null` and `score=null`, even when
  below-threshold candidates are listed.
- `DUPLICATE` and `REVIEW_REQUIRED` repeat the leading candidate's ID and score
  at the top level when a candidate exists. `REVIEW_REQUIRED` returns the
  highest-scoring candidate even though the match is unconfirmed.
- `PARTIAL` and `FAILED` always force `decision=REVIEW_REQUIRED` and produce an
  `error` object with `code` and `message`, plus
  `CANDIDATE_RETRIEVAL_INCOMPLETE` or `CANDIDATE_RETRIEVAL_FAILED` in
  `reason_codes`. Valid candidates are preserved.
- Completed, partial and failed duplicate checks all return HTTP `200`.
- Invalid Agent 1 payloads return `422` with a `detail` envelope and no Agent 3
  body; the service is not called.
- `TimeoutError` returns `504`; other unexpected exceptions return `500`. Neither
  returns a fabricated Agent 3 result.
- The default app (empty in-memory repository) returns `NEW`,
  `processing_status=COMPLETED` and `NO_ELIGIBLE_CANDIDATES`.
- The response shape validates as `M3DuplicateCheckResponse`; no extra top-level
  fields are emitted.

**Owning module**

`app/api/router.py`, `app/api/app.py`, `app/api/mapper.py`,
`app/schemas/m3_response.py`, `app/services/detection_service.py`
(`check_detailed()`) and `app/repositories/base.py` (retrieval completeness).

**Dependency / status**

`[NO-DEP]` for the producer behavior implemented from Agent 3's `b92.md`
specification. `[A3-REQ]` applies only to consumer acceptance and final contract
sign-off (IT-11). Two documented deviations remain: opaque incident IDs rather
than UUIDs, and omitted per-candidate `signals`. Production repository
completeness remains `[RETRIEVAL-OPEN]`.

**Existing evidence**

`tests/test_m3_http.py`:
`test_response_has_exactly_the_eleven_contract_fields`,
`test_check_id_is_a_uuid_and_checked_at_is_utc`,
`test_route_passes_the_adapted_complaint_to_the_service`,
`test_default_app_is_wired_with_an_empty_repository`,
`test_duplicate_repeats_the_leading_candidate`,
`test_review_required_returns_the_highest_scoring_candidate`,
`test_new_nulls_match_and_score_but_keeps_below_threshold_candidates`,
`test_candidates_are_sorted_by_descending_similarity_score`,
`test_candidates_without_a_score_are_omitted`,
`test_candidate_reason_codes_preserve_policy_codes_and_contradictions`,
`test_partial_retrieval_is_200_review_required_and_never_duplicate`,
`test_partial_retrieval_without_candidates_is_review_not_new`,
`test_failed_retrieval_is_200_review_required_with_error`,
`test_missing_required_field_returns_422_and_no_contract_body`,
`test_unsupported_field_returns_422`,
`test_non_mapping_json_returns_422`,
`test_malformed_json_returns_422`,
`test_missing_body_returns_422`,
`test_timeout_returns_504_and_no_contract_body`,
`test_unexpected_failure_returns_500_and_no_contract_body`,
`test_422_does_not_call_the_service`.

`tests/test_detection_service_detailed.py`:
`test_complete_retrieval_preserves_duplicate_decision`,
`test_complete_empty_retrieval_is_new`,
`test_partial_retrieval_with_high_score_is_not_reported_as_complete`,
`test_partial_retrieval_with_low_score_is_review_not_new`,
`test_partial_retrieval_without_candidates_is_review_not_new`,
`test_list_only_repository_defaults_to_partial_not_complete`,
`test_repository_failure_becomes_failed_review_not_new`,
`test_malformed_retrieval_result_becomes_failed`,
`test_timeout_propagates_for_http_504`,
`test_unexpected_exception_propagates_for_http_500`.

`tests/test_repository.py`:
`test_in_memory_retrieve_candidates_reports_complete`,
`test_in_memory_retrieve_candidates_excludes_self`,
`test_default_retrieve_candidates_reports_partial_not_complete`,
`test_candidate_retrieval_synthesises_a_failure_for_partial`,
`test_candidate_retrieval_synthesises_a_failure_for_failed`,
`test_complete_candidate_retrieval_rejects_failures`,
`test_candidate_retrieval_rejects_non_complaint_candidates`,
`test_candidate_retrieval_rejects_non_retrieval_outcome`,
`test_repository_error_defaults_to_retrieval_failed_code`,
`test_repository_error_accepts_a_machine_readable_code`,
`test_repository_error_rejects_a_malformed_code`,
`test_retrieval_failure_rejects_a_malformed_code`.

## 8. Cross-case invariants

- Adapter failures occur before retrieval; repository failures occur before
  comparison and never become an unqualified `NEW` or a confirmed `DUPLICATE`.
- A successful empty retrieval is complete only when the repository attests
  `COMPLETE`; `InMemoryComplaintRepository` does, while the base
  `retrieve_candidates()` defaults to `PARTIAL`.
- Partial or failed retrieval never produces `NEW`; the M3 edge forces
  `REVIEW_REQUIRED` and reports the matching processing status.
- Comparator exceptions are isolated into `ERROR` signals with null scores.
- The scoring engine never treats missing, invalid, or error evidence as zero.
- The decision policy applies evidence gates before threshold bands; a weak
  candidate with insufficient evidence is a review, not `NEW`.
- The internal `check()` response exposes exactly six fields; the Agent 3 wire
  response exposes exactly eleven. They are separate contracts and must not be
  merged.
- The M3 response never fabricates candidates: `candidates` contains only
  candidates that completed retrieval and scoring.
- The M3 top-level `matched_incident_id`/`score` repeat the leading candidate for
  non-`NEW` decisions and are `null` for `NEW`.
- Candidate order in the repository must not change the internal public outcome
  for the same candidate set; the M3 wire response is deterministically sorted by
  descending similarity.
- HTTP `200` covers completed, partial and failed duplicate checks; `422` is
  limited to invalid requests; `504`/`500` are used only when no trustworthy
  result exists.
- No test may mutate production settings, thresholds, weights, mappings, or
  other agents' code.

## 9. Open questions

### Agent 1 handoff contract (`[A1-SIGNOFF]`)

The draft contract (`a1-to-a2-draft-1`) resolved several mapping questions. It
did not resolve receiver-side policy, and it is not signed off.

| # | Contract-confirmed | Still open |
| --- | --- | --- |
| A1-1 | Draft version is `a1-to-a2-draft-1`; status is "Draft — pending agreement". | What is the final version, and who signs it off? Confirm that "M2 → M3" and "Agent 1 → Agent 2" name the same seam. |
| A1-2 | `reported_at` ← `submitted_at`, falling back to `created_at`; ISO-8601 with an explicit UTC offset; app clock is `Asia/Kolkata`. | Whether `created_at` is semantically valid as report time, and whether every fallback value is timezone-aware. M3 cannot tell which upstream field produced `reported_at`. |
| A1-3 | `description` ← `complaint_text`, falling back to `incident_summary` when `complaint_text` is empty/falsy. | Whether the fallback is acceptable only for legacy records, or should be flagged/rejected. |
| A1-4 | `category` ← `incident_type` unless it is `UNKNOWN`, in which case the broader `category` is used. | Whether M3 should compare on the specific `incident_type` (for example `WASTE_OVERFLOW`) or the broader department category (for example `SANITATION`). |
| A1-5 | `location` ← `reported_incident_location` only; device GPS and EXIF are never promoted; coordinates may be `null`. | Whether `facility_id` / `location_id` stay `null`; whether a partial coordinate pair is rejected (current receiver behavior) or repaired. |
| A1-6 | `image_hash` ← first accepted media item with a non-empty `perceptual_hash`, in media order; all accepted hashes also appear under `kavach_agent1`. | Whether the first-image rule is final, and whether the adapter should receive all hashes instead of only `image_hash`. |
| A1-7 | The sender always emits `kavach_agent1`; the contract documents it as ignorable by Agent 2. | Whether the receiver must require it and enforce `contract_version`. Current behavior is optional and unenforced. |
| A1-8 | Unknown-field behavior is not specified by Agent 1; the contract delegates it to Agent 2/M3. | Whether unknown top-level fields are rejected (current behavior) or ignored, and whether unknown nested `kavach_agent1` fields remain harmless (currently yes). |
| A1-9 | The minimal payload is published as a receiver proposal only; the sender currently emits all seven top-level keys. | Which fields M3 must actually require, and which may be omitted or `null`. |
| A1-10 | Both published payloads are reproduced verbatim in `tests/conftest.py` and pass the adapter and adapter → service tests. | Formal fixture sign-off once the contract is frozen. The contract labels every value an illustrative placeholder, not a captured API response; draft-contract coverage is not final contract validation. |

### Agent 3/Supervisor consumption (`[A3-REQ]`)

| # | Current producer behavior | Question to resolve |
| --- | --- | --- |
| A3-1 | The producer now exposes an eleven-field HTTP JSON contract at `POST /internal/v1/duplicate-detection/check`, implemented from Agent 3's `b92.md`. The internal six-field object still exists for `check()`. | Does Agent 3/Supervisor sign off on `b92.md` as final and consume the HTTP JSON directly? Is the internal six-field object still required by any consumer? |
| A3-2 | The M3 response exposes `check_id`, `incident_id`, `decision`, `processing_status`, `policy_version`, `checked_at`, `matched_incident_id`, `score`, `reason_codes`, `candidates`, and `error`. | Are those eleven fields sufficient? Does the consumer need candidate `signals`, policy metadata, or additional audit fields? |
| A3-3 | `REVIEW_REQUIRED` now returns the highest-scoring candidate as `candidates[0]` and repeats it in `matched_incident_id`/`score`, even though the match is unconfirmed. | Is exposing an unconfirmed leading candidate acceptable for review routing, or does the consumer need an explicit confirmation flag? |
| A3-4 | `score` and candidate `similarity_score` are similarity/ranking values in `[0, 1]`, not probabilities. | What score semantics, thresholds, or confidence handling does the consumer require? |
| A3-5 | `reason_codes` and candidate `reason_codes` are open, additive sets. | Which reason codes must be understood, and what is the fallback for unknown codes? |
| A3-6 | `check_detailed()` converts `RepositoryError` into `200 + REVIEW_REQUIRED + FAILED`; raw timeouts/unexpected failures become `504`/`500`; invalid payloads become `422`. | Does the consumer need different retry/error/audit behavior for `PARTIAL`/`FAILED` versus transport failures? |
| A3-7 | Incident IDs are validated as opaque strings, not UUIDs; `check_id` is a UUID. | Does Agent 3/Supervisor require UUID-format incident IDs, or accept the Agent 1 opaque format? |

### Cross-cutting policy and retrieval questions

| # | Current behavior | Question to resolve |
| --- | --- | --- |
| X-1 | `check_detailed()` uses `retrieve_candidates()`; the base implementation defaults to `PARTIAL`, while `InMemoryComplaintRepository` attests `COMPLETE`. `check()` still uses `list_candidates()` and assumes complete retrieval. | How should each production adapter attest completeness, and should `check()` eventually delegate to the explicit retrieval path? |
| X-2 | A text/embedding `ERROR` can still allow `NEW` when other evidence is weak. | Should an `ERROR` signal force `REVIEW_REQUIRED`? This is pending mentor approval. |
| X-3 | The internal six-field response omits the leading candidate for `REVIEW_REQUIRED`; the M3 wire response exposes it. | Does any consumer still need a leading candidate from the internal contract, or is the M3 exposure sufficient? |
| X-4 | Thresholds, weights, and mappings are provisional. | When will they be calibrated and frozen, and which tests become policy-validation tests at that point? |
| X-5 | The M3 endpoint `POST /internal/v1/duplicate-detection/check` is implemented with 200/422/504/500 semantics; `/health`, authentication, rate limiting and deployment topology are not. | What deployment, auth, timeout and health-check contract will the edge expose, and should the path remain `/internal/...`? |

## 10. Execution and reporting

### Commands

Focused adapter/service suites:

```text
python -m pytest tests/test_incident_payload_adapter.py tests/test_detection_service.py tests/test_scoring_engine.py tests/test_decision_policy.py -q
```

Focused M3 HTTP/retrieval suites:

```text
python -m pytest tests/test_repository.py tests/test_detection_service_detailed.py tests/test_m3_http.py -q
```

Full suite:

```text
python -m pytest -q
```

### Results

Recorded on 2026-11-01 on branch `duplicate-detection-agent` at commit
`851ab7c` with working-tree changes uncommitted:

```text
python -m pytest tests/test_incident_payload_adapter.py -q
46 passed in 0.41s

python -m pytest tests/test_incident_payload_adapter.py tests/test_detection_service.py -q
63 passed in 2.28s

python -m pytest tests/test_incident_payload_adapter.py tests/test_detection_service.py tests/test_scoring_engine.py tests/test_decision_policy.py -q
153 passed in 2.28s

python -m pytest -q
394 passed in 2.87s
```

Recorded on 2026-11-02 after the M3 HTTP edge, same branch and commit, with
working-tree changes still uncommitted:

```text
python -m pytest tests/test_repository.py tests/test_detection_service_detailed.py tests/test_m3_http.py -q
59 passed in 4.43s

python -m pytest -q
437 passed in 3.13s
```

The previous baseline, recorded on 2026-10-30, was **138 passed** for the
four-file focused suite and **379 passed** for the full suite. The 2026-11-01
work added 15 tests (12 adapter cases and 3 adapter → service cases). The
2026-11-02 M3 work added 43 tests across repository retrieval outcomes, the
detailed service path and the HTTP contract.

IT-01 through IT-10 and IT-12 have executable evidence at the levels listed in
§6. IT-11 remains blocked on `[A3-REQ]` consumer-side sign-off. Still unresolved:
final receiver policy (`[A1-SIGNOFF]`), production repository completeness
semantics, the comparator-`ERROR` policy, and downstream consumer acceptance.
The M3 producer contract is implemented from Agent 3's `b92.md`, with two
documented deviations: opaque incident IDs rather than UUIDs, and omitted
per-candidate `signals`.

### Exit criteria

- Existing focused and full suites pass.
- IT-01 through IT-10 and IT-12 pass.
- IT-11 is either implemented against agreed Agent 3/Supervisor requirements or
  explicitly skipped with the `[A3-REQ]` reason.
- No production service, scoring, decision-policy, comparator, threshold,
  weight, or mapping change is required to make the tests pass.
- The M3 response never fabricates candidates, never returns `NEW` for partial or
  failed retrieval, and never converts a timeout/outage into a business result.
- Open questions are resolved or explicitly accepted as known limitations.
- No commit or push is performed as part of test-plan work.
