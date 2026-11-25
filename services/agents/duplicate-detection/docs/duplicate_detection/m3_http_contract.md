# M3 HTTP Contract — Agent 3 Duplicate-Check Endpoint

Implementation contract for the transport edge over the existing duplicate-detection
service. The authoritative source is Agent 3's response specification (`b92.md`).
This document describes the code as implemented in:

- [`app/api/router.py`](../../app/api/router.py) — route and HTTP error mapping.
- [`app/api/app.py`](../../app/api/app.py) — application factory and validation handler.
- [`app/api/dependencies.py`](../../app/api/dependencies.py) — service injection.
- [`app/api/mapper.py`](../../app/api/mapper.py) — internal result → Agent 3 response.
- [`app/schemas/m3_response.py`](../../app/schemas/m3_response.py) — wire schema and invariants.
- [`app/services/detection_service.py`](../../app/services/detection_service.py) —
  `check_detailed()` and `DetectionResult`.

The endpoint does **not** introduce a second comparator set, scoring formula or
decision policy. It adapts the existing
[`DuplicateDetectionService`](../../app/services/detection_service.py) outcome to
the Agent 3 wire shape.

## 1. Endpoint

```text
POST /internal/v1/duplicate-detection/check
Content-Type: application/json
```

The path is the M3/Agent 3 integration endpoint. It is distinct from the Phase 1
design path `POST /api/v1/duplicate-detection/check` in
[`api_contract.md`](./api_contract.md), which remains a design proposal and is not
implemented.

Run locally:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Request body

The body is the Agent 1 incident handoff envelope. It is validated by
[`to_complaint()`](../../app/adapters/incident_payload.py), not by FastAPI field
declarations, because the adapter owns the Agent 1 field mapping and rejection
rules. See [`m2_input_adapter.md`](./m2_input_adapter.md).

A valid body is adapted to a `Complaint`, passed to
`DuplicateDetectionService.check_detailed()`, and mapped to the response below. The
endpoint does not accept `options`, `candidates` or other Phase 1 request-only
fields.

### Processing flow

```text
Agent 1 handoff JSON
        │
        ▼
to_complaint()                   422 on invalid payload
        │
        ▼
DuplicateDetectionService.check_detailed()
        │  repository.retrieve_candidates() → CandidateRetrieval
        │  comparators → weighted scoring → decision policy
        ▼
DetectionResult
        │
        ▼
to_m3_response()                 Agent 3 wire response (HTTP 200)
```

## 2. Response schema

A successful duplicate check always returns exactly these eleven top-level fields:

| Field | Type | Notes |
| --- | --- | --- |
| `check_id` | string | Unique id for this check. Generated as a UUID per request. |
| `incident_id` | string | Echoes the incoming complaint id. |
| `decision` | enum | `NEW` \| `DUPLICATE` \| `REVIEW_REQUIRED`. |
| `processing_status` | enum | `COMPLETED` \| `PARTIAL` \| `FAILED`. |
| `policy_version` | string | Effective decision-policy version (for example `v1-draft`). |
| `checked_at` | string (ISO-8601 UTC) | Evaluation timestamp, serialized with a trailing `Z`. |
| `matched_incident_id` | string \| null | Leading candidate for a non-`NEW` decision; `null` for `NEW` or when no candidate exists. |
| `score` | number \| null | Leading candidate's **similarity/ranking score** in `[0, 1]`; never a confidence or probability. `null` for `NEW` or when no candidate exists. |
| `reason_codes` | array[string] | Machine-readable UPPER_SNAKE reason codes. Open, additive set. |
| `candidates` | array | Retrieved and scored candidates, ordered by descending `similarity_score`. |
| `error` | object \| null | `{"code", "message"}` exactly when processing is `PARTIAL` or `FAILED`; otherwise `null`. |

Every field is always present. Optional values are `null`; they are never omitted.

### `candidates[]`

```json
{
  "matched_incident_id": "INC-2026-002",
  "similarity_score": 0.91,
  "reason_codes": ["SCORE_ABOVE_HIGH_THRESHOLD"]
}
```

- `similarity_score` is required and must be a finite number in `[0, 1]`.
- Candidates whose internal score is `None` are omitted. The Agent 3 contract
  requires a numeric `similarity_score`, so an unscorable candidate cannot be
  represented without inventing a value.
- Candidate `signals` is omitted. It is optional in the Agent 3 contract, and the
  internal `RankedCandidate` does not carry per-candidate signal details.
- `reason_codes` combines the candidate's policy reasons and contradictions,
  de-duplicated in first-seen order.
- Candidates are sorted by `similarity_score` descending. The policy already ranks
  them; the mapper's stable sort makes the wire invariant explicit without
  changing ties or introducing a second ranking formula.

### Cross-field invariants

The schema rejects a response that violates any of these:

1. `error` is present exactly when `processing_status` is `PARTIAL` or `FAILED`.
2. `PARTIAL` and `FAILED` always force `decision = REVIEW_REQUIRED`, even if the
   policy produced `DUPLICATE`.
3. `NEW` has `matched_incident_id = null` and `score = null`.
4. For any non-`NEW` decision, `matched_incident_id` and `score` repeat the leading
   candidate when one exists; both are `null` when no candidate exists.
5. `DUPLICATE` requires `processing_status = COMPLETED` and at least one candidate.
6. Candidates are ordered by descending `similarity_score`.

## 3. Decision and processing-status mapping

### Processing status

| Repository retrieval | `processing_status` | Decision forced to `REVIEW_REQUIRED`? |
| --- | --- | --- |
| `COMPLETE` | `COMPLETED` | No — the policy decision is preserved. |
| `PARTIAL` | `PARTIAL` | Yes. |
| `FAILED` | `FAILED` | Yes. |

`COMPLETED` means the repository guaranteed that every eligible candidate was
returned. An empty result from a complete repository is still `COMPLETED`; the
policy returns `NEW`.

### Decision rules

| Situation | `decision` | `matched_incident_id` / `score` |
| --- | --- | --- |
| Confirmed best candidate above the high threshold, no blocking contradiction | `DUPLICATE` | Leading candidate. |
| Borderline, ambiguous, contradiction, or insufficient evidence | `REVIEW_REQUIRED` | Highest-scoring candidate, even though unconfirmed. |
| Complete retrieval, no candidate qualifies, no candidate above threshold | `NEW` | Both `null`. Below-threshold candidates may still be listed. |
| Partial or failed retrieval | `REVIEW_REQUIRED` | Leading valid candidate if one was scored; otherwise both `null`. |

`REVIEW_REQUIRED` intentionally returns the highest-scoring candidate even though
the decision is unconfirmed. The candidate list is evidence for the reviewer, not
an assertion of a match.

### Retrieval failure and `error`

- A partial retrieval adds `CANDIDATE_RETRIEVAL_INCOMPLETE` to `reason_codes` and
  returns an `error` built from the repository's first `RetrievalFailure`.
- A failed retrieval adds `CANDIDATE_RETRIEVAL_FAILED` and returns an `error`
  built from the repository failure (code `RETRIEVAL_FAILED` by default).
- `RepositoryError` is converted inside `check_detailed()` into a failed
  `DetectionResult`; it never escapes as a fabricated `NEW` or `DUPLICATE`.
- Unexpected exceptions (including `TimeoutError`) are **not** converted. They
  propagate to the HTTP layer, which returns 5xx/504 rather than a fabricated
  result.

## 4. HTTP status policy

| Condition | HTTP status | Body |
| --- | --- | --- |
| Completed, partial or failed duplicate check | `200` | Agent 3 response (§2), including an `error` object when partial/failed. |
| Invalid Agent 1 payload, malformed JSON or missing body | `422` | `{"detail": {"code": "INVALID_INCIDENT_PAYLOAD", "message": "..."}}` |
| Duplicate-check timeout | `504` | `{"detail": {"code": "DUPLICATE_CHECK_TIMEOUT", "message": "..."}}` |
| Unexpected internal failure before a result exists | `500` | `{"detail": {"code": "INTERNAL_ERROR", "message": "..."}}` |

Rules:

- **Business outcomes never use error status codes.** `NEW`, `DUPLICATE` and
  `REVIEW_REQUIRED` return `200`, as do `PARTIAL` and `FAILED` processing states
  that produced a trustworthy response.
- A service outage or timeout that prevents a result must produce 5xx/timeout. It
  must never be converted into `NEW` or another fabricated Agent 3 body.
- Error responses use a `detail` envelope, not the Agent 3 result shape, and do not
  include stack traces or submitted values.
- Validation errors are returned before retrieval. They therefore do not produce a
  `check_id` or any other Agent 3 field.

## 5. Identifier deviation

Agent 3's specification describes identifiers as UUID strings. The upstream Agent 1
payload and the internal `Complaint` model use opaque incident identifiers
(for example `INC-2026-001`) with a 1–64 character limit. This implementation:

- validates `incident_id`, `matched_incident_id` and each candidate
  `matched_incident_id` as non-empty strings up to 64 characters, **not** as UUIDs;
- generates `check_id` as a real UUID, so that half of the contract is honoured.

This is a documented deviation, not an accidental omission. Enforcing UUID format
would reject valid Agent 1 fixtures. Reconciling the two identifier contracts
remains an integration decision.

## 6. Service wiring

`create_app(service=None)` builds the FastAPI application:

- When `service` is supplied, it is stored at
  `app.state.duplicate_detection_service` and used by the route.
- When omitted, the app constructs a `DuplicateDetectionService` over an **empty**
  `InMemoryComplaintRepository`. Every valid check then returns `NEW` with
  `NO_ELIGIBLE_CANDIDATES` and `processing_status = COMPLETED`.
- Callers that need real candidates — or a deterministic demo set — inject their own
  `DuplicateDetectionService` into `create_app()`.

The route depends only on a narrow `DetailedDetectionService` protocol exposing
`check_detailed()`. Tests inject deterministic doubles without subclassing the
concrete service.

The public realization of the Agent 3 check is `check_detailed()`. The existing
`check()` method is unchanged and still returns the internal six-field
`DuplicateDetectionResponse`; it is not used by this endpoint.

## 7. Examples

### 7.1 Confirmed duplicate (`200`)

```json
{
  "check_id": "0f2a4b0e-6f1a-4a0e-9a5e-2f7c1e7b9d10",
  "incident_id": "INC-2026-001",
  "decision": "DUPLICATE",
  "processing_status": "COMPLETED",
  "policy_version": "v1-draft",
  "checked_at": "2026-11-02T10:15:00Z",
  "matched_incident_id": "INC-2026-000",
  "score": 0.93,
  "reason_codes": ["SCORE_ABOVE_HIGH_THRESHOLD"],
  "candidates": [
    {
      "matched_incident_id": "INC-2026-000",
      "similarity_score": 0.93,
      "reason_codes": ["SCORE_ABOVE_HIGH_THRESHOLD"]
    }
  ],
  "error": null
}
```

### 7.2 Review required with a leading candidate (`200`)

```json
{
  "check_id": "a72e9d38-1c6b-4f10-8f4b-3d2f9e8a7c61",
  "incident_id": "INC-2026-001",
  "decision": "REVIEW_REQUIRED",
  "processing_status": "COMPLETED",
  "policy_version": "v1-draft",
  "checked_at": "2026-11-02T10:16:00Z",
  "matched_incident_id": "INC-2026-055",
  "score": 0.52,
  "reason_codes": [
    "SCORE_BETWEEN_THRESHOLDS",
    "CONTRADICTION_LOCATION_MISMATCH"
  ],
  "candidates": [
    {
      "matched_incident_id": "INC-2026-055",
      "similarity_score": 0.52,
      "reason_codes": [
        "SCORE_BETWEEN_THRESHOLDS",
        "CONTRADICTION_LOCATION_MISMATCH"
      ]
    }
  ],
  "error": null
}
```

### 7.3 Partial retrieval (`200`)

```json
{
  "check_id": "b1d4c9e2-5a3f-4c7e-9b0d-6e8f2a1c3d45",
  "incident_id": "INC-2026-001",
  "decision": "REVIEW_REQUIRED",
  "processing_status": "PARTIAL",
  "policy_version": "v1-draft",
  "checked_at": "2026-11-02T10:17:00Z",
  "matched_incident_id": "INC-2026-000",
  "score": 0.88,
  "reason_codes": [
    "SCORE_ABOVE_HIGH_THRESHOLD",
    "CANDIDATE_RETRIEVAL_INCOMPLETE"
  ],
  "candidates": [
    {
      "matched_incident_id": "INC-2026-000",
      "similarity_score": 0.88,
      "reason_codes": ["SCORE_ABOVE_HIGH_THRESHOLD"]
    }
  ],
  "error": {
    "code": "RETRIEVAL_INCOMPLETE",
    "message": "Candidate retrieval was incomplete."
  }
}
```

### 7.4 Invalid request (`422`)

```json
{
  "detail": {
    "code": "INVALID_INCIDENT_PAYLOAD",
    "message": "incident payload failed validation: incident_type: Field required"
  }
}
```

## 8. Tests

Contract and edge coverage lives in:

- [`tests/test_m3_http.py`](../../tests/test_m3_http.py) — exact eleven-field
  shape, all three decisions, partial/failed `200` responses, candidate ordering,
  null-score omission, invalid/malformed payload `422`, timeout `504`, unexpected
  failure `500`, and default-app `NEW`.
- [`tests/test_detection_service_detailed.py`](../../tests/test_detection_service_detailed.py) —
  complete/partial/failed retrieval, safe default `PARTIAL`, malformed retrieval,
  and propagation of unexpected exceptions.
- [`tests/test_repository.py`](../../tests/test_repository.py) — retrieval outcome,
  completeness default, failure synthesis, and error codes.

Run them with:

```powershell
python -m pytest tests\test_m3_http.py tests\test_detection_service_detailed.py tests\test_repository.py -q
```

## 9. Known limitations

- **Default repository is empty.** The default app is structurally complete but has
  no production candidate source. `NEW + COMPLETED` is the expected result until a
  seeded service or a real repository adapter is injected.
- **Completeness is repository-attested.** The base repository defaults
  `retrieve_candidates()` to `PARTIAL` with
  `RETRIEVAL_COMPLETENESS_UNKNOWN`; only `InMemoryComplaintRepository` overrides it
  to `COMPLETE`. A new adapter must explicitly attest completeness or remain
  partial. The interface change is documented in
  [`service_orchestration.md`](./service_orchestration.md).
- **No authentication or rate limiting.** The endpoint is `/internal/...`; network
  exposure and auth remain deployment decisions.
- **Synchronous request handling.** The service and repository interfaces are
  synchronous. A blocking production repository should be moved off the event loop
  or wrapped in an async adapter before deployment.
- **Identifier format deviation.** See §5.
- **Candidate signals are absent.** See §2.
- **Comparator `ERROR` policy remains open.** The HTTP edge preserves the policy's
  current behavior; it does not force review merely because a comparator failed.
