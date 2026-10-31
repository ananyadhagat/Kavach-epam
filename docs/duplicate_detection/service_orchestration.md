# Duplicate Detection Agent — Internal Service Orchestration

Implementation note for the transport-free service that composes the existing
building blocks. It documents the code as it exists today; it does **not** change
the Phase 1 API contract or matching policy.

## Status and scope

Implemented:

- [`app/services/detection_service.py`](../../app/services/detection_service.py)
  — `DuplicateDetectionService`.
- [`app/services/__init__.py`](../../app/services/__init__.py) — package export.
- [`tests/test_detection_service.py`](../../tests/test_detection_service.py) —
  service-level tests using fake repositories/comparators and the real scoring
  engine and decision policy.

Not implemented here:

- No FastAPI app, router, HTTP request model or endpoint.
- No database or vector-store adapter.
- No async repository contract.
- No candidate blocking/retrieval filters beyond self-exclusion.
- No expansion of the public `DuplicateDetectionResponse` schema.

The HTTP edge remains deferred (M5 in
[`implementation_plan.md`](./implementation_plan.md)). This service is the
in-process seam that a future edge can call.

## Composition flow

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

The service contains no similarity maths, scoring formula or decision rules. It
only retrieves, invokes collaborators, adapts contracts and returns the existing
response.

## Construction and `check()` interface

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

`check()`:

```python
check(complaint: Complaint) -> DuplicateDetectionResponse
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
- The service always passes `RetrievalStatus.COMPLETE` because a successful
  repository call, including an empty result, is complete retrieval.
- The returned object is the existing six-field response; no new public fields
  are added.

## Candidate retrieval and de-duplication

The repository contract is:

```python
list_candidates(exclude_complaint_id: str | None = None) -> list[Complaint]
```

The service calls it with the incoming `complaint_id`. A successful iterable is
accepted even if the repository ignores the exclusion argument. The service then:

1. Rejects a non-iterable result with `RepositoryError`.
2. Rejects any element that is not a `Complaint` with `RepositoryError`.
3. Skips a candidate whose id equals the incoming complaint id.
4. Keeps the first occurrence of a repeated candidate id and ignores later ones.

An empty result is a legitimate `COMPLETE` retrieval, not an error. The decision
policy then returns `NEW` with `NO_ELIGIBLE_CANDIDATES`.

There is currently no `CandidateRetriever`, no blocking filter, no retrieval
window and no candidate limit in this path. The in-memory repository already
excludes and sorts records; the service filter is a defensive guard for other
repository implementations and test doubles.

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

## Decision and response mapping

The service passes the adapted `CandidateScore` list to `DecisionPolicy.decide()`
with `RetrievalStatus.COMPLETE`, then calls
`DecisionOutcome.to_response(complaint_id)`.

The existing response contains exactly:

- `complaint_id`
- `decision`
- `matched_incident_id`
- `score`
- `signals`
- `reasons`

The decision policy's richer outcome remains internal. In particular,
`DecisionOutcome.candidates` (including the leading candidate for a review),
`policy_version`, retrieval/search details and any request identifier are **not**
exposed by `DuplicateDetectionResponse`. For `REVIEW_REQUIRED`, the response does
not identify which candidate should be reviewed even though the outcome retains
that information.

`score` is the leading candidate's ranking score when the policy exposes one. It
is `None` for `NEW` and for retrieval-blocked reviews, and it is never a
calibrated probability.

## Failure semantics

| Condition | Service behavior | Caller sees |
| --- | --- | --- |
| Repository raises `RepositoryError` | Propagated unchanged; no decision is fabricated | `RepositoryError` |
| Repository returns a non-iterable | Converted to `RepositoryError` | `RepositoryError` |
| Repository returns a non-`Complaint` element | Converted to `RepositoryError` | `RepositoryError` |
| Repository returns an empty iterable | Treated as complete retrieval | `NEW` + `NO_ELIGIBLE_CANDIDATES` |
| Comparator raises an exception | Converted to `ERROR` signal `SIGNAL_ERROR_<NAME>` | Candidate is still scored on remaining signals |
| Comparator returns a non-`SignalResult` | Converted to `ERROR` signal `SIGNAL_ERROR_<NAME>` with `InvalidComparatorResult` | Candidate is still scored on remaining signals |
| Comparator returns its own `ERROR` | Preserved | Candidate is still scored on remaining signals |
| Comparator returns `UNAVAILABLE`/`INVALID` | Preserved | Excluded from scoring; evidence gates may force review |
| Scoring engine rejects evidence/configuration | `ScoringError` propagates | `ScoringError` |
| Explicit contradiction | Policy returns `REVIEW_REQUIRED` | Review response with contradiction reasons |
| Retrieval is incomplete | Not producible by this service; it always reports `COMPLETE` | No `INCOMPLETE` response path |

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

- The shared `Complaint` model is the service input. Field renames or a mapping
  layer from the upstream complaint service are still a team decision.
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
- The public response cannot carry `candidates`, `policy_version`, retrieval
  status, search details or `request_id`. Expanding it is a contract change and
  requires team agreement.
- `REVIEW_REQUIRED` currently loses the leading candidate in the public response.
  If reviewers need a candidate to inspect, the response contract must be
  extended.
- `INCOMPLETE` retrieval is supported by the policy but cannot be produced by
  this service. A future retriever must pass the actual status through rather
  than hard-coding `COMPLETE`.

### Deferred edge work

- FastAPI app, routes, dependency wiring, `/health`, request validation and
  HTTP error mapping (M5).
- Contract tests for `POST /api/v1/duplicate-detection/check`.
- Authentication, deployment model (in-process vs standalone) and sync/async
  invocation remain team decisions in [`integration.md`](./integration.md).

## Tests

Run the focused service suite:

```bash
python -m pytest tests/test_detection_service.py -q
```

Run the full suite:

```bash
python -m pytest -q
```

The service tests cover: clear duplicate, empty repository, low score, multiple
candidates, self-exclusion, duplicate candidate ids, missing/invalid signal
preservation, explicit contradiction, embedding `ERROR` with strong evidence,
embedding `ERROR` with weak evidence, comparator exceptions, repository failure
propagation, response mapping with `COMPLETE` retrieval, and default wiring.
