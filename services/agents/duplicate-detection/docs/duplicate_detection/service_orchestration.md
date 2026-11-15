# Duplicate Detection Agent — Internal Service Orchestration

Implementation note for the transport-free service that composes the existing
building blocks, plus the M3 HTTP edge that consumes it. It documents the code as
it exists today; it does **not** change the Phase 1 API design, matching policy,
comparators or scoring formula.

## Status and scope

Implemented:

- [`app/services/detection_service.py`](../../app/services/detection_service.py)
  — `DuplicateDetectionService`, `check()` and `check_detailed()`, and
  `DetectionResult`.
- [`app/services/__init__.py`](../../app/services/__init__.py) — package exports.
- [`app/repositories/base.py`](../../app/repositories/base.py) — retrieval
  completeness contract: `RetrievalOutcome`, `RetrievalFailure`,
  `CandidateRetrieval` and `retrieve_candidates()`.
- [`app/api/`](../../app/api) — FastAPI app factory, route, dependency and the
  internal-result → Agent 3 mapper.
- [`app/schemas/m3_response.py`](../../app/schemas/m3_response.py) — Agent 3 wire
  schema and cross-field invariants.
- [`app/main.py`](../../app/main.py) — ASGI entry point.
- Service, repository and HTTP tests listed in §Tests.

Not implemented here:

- No production database, vector-store or remote KAVACH repository adapter.
- No async repository/service contract.
- No authentication, rate limiting or deployment topology.
- No candidate blocking/retrieval filters beyond self-exclusion.
- No expansion of the internal `DuplicateDetectionResponse` schema.

The M3 HTTP contract is documented in
[`m3_http_contract.md`](./m3_http_contract.md). The endpoint wraps this service;
it does not duplicate its scoring or decision logic.

## Composition flow

`check()` — the original transport-free path:

```text
Complaint
   │
   ▼
ComplaintRepository.list_candidates(exclude_complaint_id=complaint.complaint_id)
   │  (successful iterable, including [])
   ▼
defensive candidate filter (skip self, keep first duplicate id)
   │
   ▼
for each eligible candidate:
    for each configured comparator:
        comparator.compare(complaint, candidate) -> SignalResult
    WeightedScoringEngine.score(signals) -> ScoringResult
    ScoringResult.to_candidate_score(candidate_id) -> CandidateScore
   │
   ▼
DecisionPolicy.decide(candidate_scores, retrieval_status=COMPLETE)
   │
   ▼
DecisionOutcome.to_response(complaint.complaint_id)
   │
   ▼
DuplicateDetectionResponse
```

`check_detailed()` — the M3/Agent 3 path:

```text
Complaint
   │
   ▼
ComplaintRepository.retrieve_candidates(exclude_complaint_id=...)
   │  -> CandidateRetrieval(candidates, outcome, failures)
   │
   ▼
RepositoryError? ──► FAILED DecisionOutcome (no comparison)
   │
   ▼
defensive candidate filter
   │
   ▼
comparators → WeightedScoringEngine → CandidateScore list
   │
   ▼
DecisionPolicy.decide(candidate_scores, retrieval_status=mapped_status)
   │
   ▼
DetectionResult(incident_id, outcome, retrieval_status, retrieval_failure)
   │
   ▼
app.api.mapper.to_m3_response() → M3DuplicateCheckResponse
```

Both methods share the same candidate filtering, comparator isolation and scoring
helpers. Neither contains similarity maths, a scoring formula or decision rules.

## Construction and interfaces

```python
DuplicateDetectionService(
    repository: ComplaintRepository,
    *,
    comparators: Mapping[str, Comparator] | None = None,
    scoring_engine: WeightedScoringEngine | None = None,
    decision_policy: DecisionPolicy | None = None,
    settings: Settings | None = None,
)
```

Public methods:

```python
check(complaint: Complaint) -> DuplicateDetectionResponse
check_detailed(complaint: Complaint) -> DetectionResult
```

Construction rules:

- `repository` must be a `ComplaintRepository`; otherwise `TypeError`.
- `settings` must be a `Settings` or `None`; otherwise `TypeError`.
- With `comparators=None`, defaults come from
  `build_core_comparators(settings)`. The text backend is selected once by the
  factory: `embedding` by default, `tfidf` when configured. There is no
  automatic failover between backends.
- A custom comparator mapping must contain all four core names (`text`,
  `location`, `category`, `time`), keys must be non-empty strings, each value
  must be a `Comparator`, and each key must equal `comparator.name`.
- `scoring_engine`, when supplied, must be a `WeightedScoringEngine`.
- `decision_policy`, when supplied, must be a `DecisionPolicy`.
- Defaults use the resolved settings for weights, thresholds and policy version.

`check()` rules:

- The argument must be a `Complaint`; otherwise `TypeError`.
- Candidate retrieval is called exactly once per `check()`.
- Each configured comparator is called once per eligible candidate.
- The service always passes `RetrievalStatus.COMPLETE` because it calls
  `list_candidates()`, whose contract has no completeness channel. This method
  does not claim to be the M3 retrieval edge.
- The returned object is the existing six-field response; no new public fields
  are added.

`check_detailed()` rules:

- The argument must be a `Complaint`; otherwise `TypeError`.
- Candidate retrieval is called exactly once via `retrieve_candidates()`.
- A `RepositoryError` becomes a `FAILED` retrieval result with the error's `code`
  and a bounded message; the decision policy is then called with `FAILED` and an
  empty candidate list. It returns `REVIEW_REQUIRED`, never `NEW`.
- An unexpected exception (including `TimeoutError`) is **not** caught. It
  propagates so the HTTP edge can return 5xx/504 instead of a fabricated result.
- The result preserves candidate evidence even when retrieval is partial.
- `DetectionResult.to_response()` adapts it to the internal six-field response
  when needed; the HTTP layer uses the Agent 3 mapper instead.

## Candidate retrieval and de-duplication

### `check()` path

`check()` uses:

```python
list_candidates(exclude_complaint_id: str | None = None) -> list[Complaint]
```

The service calls it with the incoming `complaint_id`. A successful iterable is
accepted even if the repository ignores the exclusion argument. The service then:

1. Rejects a non-iterable result with `RepositoryError`.
2. Rejects any element that is not a `Complaint` with `RepositoryError`.
3. Skips a candidate whose id equals the incoming complaint id.
4. Keeps the first occurrence of a repeated candidate id and ignores later ones.

An empty result is treated as a legitimate `COMPLETE` retrieval, not an error.
The decision policy then returns `NEW` with `NO_ELIGIBLE_CANDIDATES`.

### `check_detailed()` path and the completeness gap

The original repository interface could not distinguish "the repository returned
everything" from "the repository returned what it could find". Treating every
successful call as `COMPLETE` would silently produce `NEW` from a partial search.
The smallest safe interface change was therefore a new optional method:

```python
retrieve_candidates(
    exclude_complaint_id: str | None = None,
) -> CandidateRetrieval
```

```python
CandidateRetrieval(
    candidates: tuple[Complaint, ...],
    outcome: RetrievalOutcome,        # COMPLETE | PARTIAL | FAILED
    failures: tuple[RetrievalFailure, ...] = (),
)
```

Rules:

- `COMPLETE` means the repository **guarantees** every eligible candidate was
  returned, and forbids `failures`.
- `PARTIAL` means the returned candidates are valid but the set may be
  incomplete. A failure is required (or synthesised).
- `FAILED` means retrieval did not produce a trustworthy candidate set. A failure
  is required (or synthesised).
- The base implementation of `retrieve_candidates()` defaults to **`PARTIAL`**
  with `RETRIEVAL_COMPLETENESS_UNKNOWN`. A repository that cannot attest to
  completeness therefore cannot cause an unqualified `NEW`.
- `InMemoryComplaintRepository` overrides it to `COMPLETE`, because its full
  in-memory set is exhaustive.
- `RepositoryError` carries an optional `code` (default `RETRIEVAL_FAILED`).
  `INVALID_RETRIEVAL_RESULT` is used when `check_detailed()` receives something
  other than a `CandidateRetrieval`.

The repository layer deliberately defines its own `RetrievalOutcome` rather than
importing the decision policy's `RetrievalStatus`; the repository must not depend
on scoring. `check_detailed()` maps:

| `RetrievalOutcome` | `RetrievalStatus` | `processing_status` |
| --- | --- | --- |
| `COMPLETE` | `COMPLETE` | `COMPLETED` |
| `PARTIAL` | `INCOMPLETE` | `PARTIAL` |
| `FAILED` | `FAILED` | `FAILED` |

There is still no `CandidateRetriever`, blocking filter, retrieval window or
candidate limit in this path. The in-memory repository already excludes and sorts
records; the service filter is a defensive guard for other repository
implementations and test doubles.

## Comparator and scoring semantics

For each candidate, the service builds a mapping of signal name to
`SignalResult`:

- A comparator's own `UNAVAILABLE`, `INVALID` or `ERROR` result is preserved
  exactly as emitted.
- An unexpected exception from `compare()` becomes an `ERROR` signal with
  reason `SIGNAL_ERROR_<NAME>` (for example `SIGNAL_ERROR_TEXT`). Details record
  the signal name, exception type and a bounded, single-line message.
- A non-`SignalResult` return value becomes an `ERROR` signal with the same
  reason and `details["error_type"] == "InvalidComparatorResult"`.

`WeightedScoringEngine.score()` then excludes every non-`AVAILABLE` signal and
renormalises the configured weights over the available signals only. `ERROR` is
therefore **not** a zero score and not a missing signal that silently contributes
nothing; it is excluded, and the remaining weights are rescaled. This can change
the evidence gates as well as the numeric score because the policy sees fewer
available signals.

`ScoringError` is not caught by the service. It indicates malformed evidence or
invalid configuration and propagates as a programming/configuration failure.
The HTTP route's broad exception handler converts an uncaught `ScoringError`
into HTTP `500`; it never becomes a fabricated business decision.

## Decision and response mapping

The service passes the adapted `CandidateScore` list to `DecisionPolicy.decide()`
with the mapped retrieval status, then wraps the outcome in `DetectionResult`.

`DetectionResult` contains:

| Field | Meaning |
| --- | --- |
| `incident_id` | Incoming complaint id. |
| `outcome` | Unchanged `DecisionOutcome` from the policy. |
| `retrieval_status` | `COMPLETE`, `INCOMPLETE` or `FAILED`. |
| `retrieval_failure` | First `RetrievalFailure` for incomplete/failed retrieval; otherwise `None`. |

The internal six-field response (`check()` / `DetectionResult.to_response()`)
contains exactly:

- `complaint_id`
- `decision`
- `matched_incident_id`
- `score`
- `signals`
- `reasons`

The Agent 3 HTTP response instead contains the eleven fields documented in
[`m3_http_contract.md`](./m3_http_contract.md). The mapper applies only
contract-level rules:

- `processing_status` comes from `retrieval_status`.
- `PARTIAL`/`FAILED` force `REVIEW_REQUIRED` even if the policy returned
  `DUPLICATE`.
- Top-level `matched_incident_id`/`score` repeat the leading candidate for a
  non-`NEW` decision; `NEW` forces both to `null`.
- `CANDIDATE_RETRIEVAL_INCOMPLETE` or `CANDIDATE_RETRIEVAL_FAILED` is added for
  incomplete/failed retrieval, plus the contract `error` object.
- Candidates are emitted in descending `similarity_score` order; candidates with
  a `None` score are omitted because the wire contract requires a numeric score.

The policy's `DecisionOutcome` remains the sole source of the decision, reason
codes and candidate ranking. `DecisionOutcome.matched_incident_id` is `None` for
`REVIEW_REQUIRED`; the mapper derives the wire match from `candidates[0]`.

`score` is the leading candidate's ranking/similarity score when the policy
exposes one. It is `None` for `NEW` and for retrieval-blocked reviews with no
scored candidate, and it is never a calibrated probability.

## Failure semantics

| Condition | Service behavior | `check()` caller sees | `check_detailed()` / HTTP |
| --- | --- | --- | --- |
| Repository raises `RepositoryError` | `check()` propagates; `check_detailed()` converts to `FAILED` | `RepositoryError` | `200` + `REVIEW_REQUIRED` + `FAILED` + error object |
| Repository returns a non-iterable | Converted to `RepositoryError` | `RepositoryError` | Same `FAILED` path |
| Repository returns a non-`Complaint` element | Converted to `RepositoryError` | `RepositoryError` | Same `FAILED` path |
| Repository returns an empty iterable | Complete retrieval if the repository attests `COMPLETE` | `NEW` + `NO_ELIGIBLE_CANDIDATES` | `200`, `COMPLETED`, `NEW` |
| Repository defaults to `PARTIAL` | Returned candidates are still scored | n/a | `200` + `REVIEW_REQUIRED` + `PARTIAL` |
| Unexpected repository exception / timeout | Propagated unchanged | Exception | HTTP `500` / `504`; no Agent 3 body |
| Comparator raises an exception | Converted to `ERROR` signal `SIGNAL_ERROR_<NAME>` | Candidate still scored on remaining signals | Preserved in the result |
| Comparator returns a non-`SignalResult` | Converted to `ERROR` signal with `InvalidComparatorResult` | Candidate still scored | Preserved |
| Comparator returns its own `ERROR` | Preserved | Candidate still scored | Preserved |
| Comparator returns `UNAVAILABLE`/`INVALID` | Preserved | Excluded from scoring; evidence gates may force review | Preserved |
| Scoring engine rejects evidence/configuration | `ScoringError` propagates | `ScoringError` | HTTP `500`; no fabricated decision |
| Explicit contradiction | Policy returns `REVIEW_REQUIRED` | Review response with contradiction reasons | `200`; leading candidate exposed |
| Retrieval is incomplete | `check()` cannot produce it; `check_detailed()` can | n/a | `200` + `REVIEW_REQUIRED` + `PARTIAL` + error |

A comparator failure is isolated per candidate. It does not abort the whole
request, and it does not automatically produce `REVIEW_REQUIRED`. Whether the
remaining evidence is sufficient is decided by the existing evidence gates and
thresholds.

## Known limitation: embedding `ERROR` can still yield `NEW`

`EmbeddingTextComparator` reports model-load, inference and invalid-output
failures as `ERROR`, never as a zero score. The service preserves that status and
the scoring engine excludes it.

If the remaining signals clear the evidence gates but their renormalised score
is below the low threshold, the decision is `NEW`. A focused service test covers
this case: text `ERROR`, location `0.60`, category `0.60`, time `0.10` produces a
score of `0.475` and therefore `NEW` with `SCORE_BELOW_LOW`.

This is the current policy, not a claim that a failed text backend is safe to
ignore. Whether a text/embedding `ERROR` should force `REVIEW_REQUIRED` even when
other signals are available is an **open policy question requiring mentor
approval**. No automatic embedding-to-TF-IDF failover is implemented; the
backend is selected at construction time.

## Integration dependencies and open decisions

### M2 / shared input and candidate contract

- The shared `Complaint` model is the service input. Agent 1 handoff JSON is
  adapted by [`to_complaint()`](../../app/adapters/incident_payload.py); see
  [`m2_input_adapter.md`](./m2_input_adapter.md).
- The repository must supply eligible existing complaints. The current prototype
  uses `InMemoryComplaintRepository`; the production source (shared DB, API or
  batch export) is unresolved.
- Retrieval scope, blocking filters and whether the upstream system already
  excludes the incoming complaint must be agreed. The service's defensive
  self-exclusion is not a substitute for a defined retrieval contract.
- The text backend (`embedding` or `tfidf`) is configuration, not a runtime
  fallback. Changing it changes the score distribution and should be calibrated.

### M3 / scoring boundary

- The service consumes `WeightedScoringEngine` and `ScoringResult`; it does not
  own weights, thresholds or normalization rules.
- `ERROR` exclusion and weight renormalisation are existing engine semantics.
  Any change to “failed signal forces review” belongs in the policy/evidence
  layer, not in this service.
- The embedding comparator's score distribution has not been calibrated against
  the provisional thresholds; see
  [`embedding_comparator.md`](./embedding_comparator.md).

### M4 / decision and response boundary

- The service consumes `DecisionPolicy` and `DecisionOutcome`; thresholds,
  evidence gates, contradiction rules and tie handling remain policy-owned.
- The internal six-field response cannot carry `candidates`, `policy_version`,
  retrieval status, search details or `request_id`. The Agent 3 wire response
  carries the agreed subset through a separate adapter.
- `REVIEW_REQUIRED` loses the leading candidate in the internal six-field
  response. The M3 HTTP response does expose the highest-scoring candidate, as
  required by Agent 3.
- `INCOMPLETE`/`FAILED` retrieval is now supported by `check_detailed()`. A future
  retriever must pass its actual status through `retrieve_candidates()` rather
  than claiming completeness.

### Edge and deployment work

- The M3 route, dependency wiring, request validation and HTTP error mapping are
  implemented in [`app/api/`](../../app/api).
- No `/health` endpoint yet.
- Authentication, deployment model (in-process vs standalone) and sync/async
  invocation remain team decisions in [`integration.md`](./integration.md).
- The default application uses an empty in-memory repository. Real candidates
  require injecting a seeded or production-backed service.

## Tests

Run the focused service and HTTP suites:

```powershell
python -m pytest tests\test_detection_service.py tests\test_detection_service_detailed.py tests\test_m3_http.py -q
```

Run the full suite:

```powershell
python -m pytest -q
```

Coverage:

- `tests/test_detection_service.py` — clear duplicate, empty repository, low
  score, multiple candidates, self-exclusion, duplicate candidate ids,
  missing/invalid signal preservation, explicit contradiction, embedding
  `ERROR`, comparator exceptions, repository failure propagation, response
  mapping and default wiring.
- `tests/test_detection_service_detailed.py` — complete/partial/failed retrieval,
  safe default `PARTIAL`, malformed retrieval, and propagation of unexpected
  exceptions.
- `tests/test_m3_http.py` — exact eleven-field response, all three decisions,
  partial/failed `200`, candidate ordering, null-score omission, `422` validation,
  `504` timeout, `500` unexpected failure and default-app behavior.
