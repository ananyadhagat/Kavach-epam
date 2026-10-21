# Duplicate Detection Agent — API Contract (V1)

> Phase 1 design document. Field names here are the **proposed V1 contract**
> (`ASSUMPTION A1`) and may be mapped/renamed during KAVACH integration.
> All examples are synthetic.

## 1. Endpoint

```
POST /api/v1/duplicate-detection/check
Content-Type: application/json
```

- **Versioning:** the path embeds `v1`. Breaking field changes require `v2`.
- **Synchronous by default** (`ASSUMPTION A4/D4`): the call returns a decision in one
  response. A future async variant (`202 Accepted` + polling/webhook) is noted in
  `integration.md` but not specified for V1.
- **Business outcomes never use error status codes.** `DUPLICATE`, `REVIEW_REQUIRED`,
  and `NEW` all return `200 OK`. HTTP errors are reserved for transport/validation/
  infrastructure failures (§6).

An optional `GET /api/v1/duplicate-detection/health` returns `{"status":"ok"}` and a
repository-reachability indicator for orchestration.

## 2. Request schema

### 2.1 Top-level fields

| Field | Type | Required | Constraints | Notes |
| --- | --- | --- | --- | --- |
| `complaint_id` | string | **yes** | 1–64 chars, non-empty after trim | Identifier of the incoming complaint. Also used to exclude self-comparison. |
| `description` | string \| null | **recommended\*** | 0–5000 chars | Free-text complaint. `null`/empty allowed but degrades match quality (see §5.1). |
| `category` | string \| null | **recommended\*** | 1–64 chars when present | Opaque category code (`ASSUMPTION A3`). Unknown values are handled, not rejected. |
| `location` | object \| null | **recommended\*** | see §2.2 | Geographic / facility context. |
| `reported_at` | string (ISO-8601) \| null | **recommended\*** | see §2.4 | When the incident was reported. |
| `image_hash` | string \| null | no | e.g. `phash:<hex>` (≤ 128 chars) | Optional perceptual hash. Never required. |
| `image_ref` | string \| null | no | ≤ 512 chars | Optional opaque reference to an image stored elsewhere. The DDA does **not** fetch it in V1. |
| `options` | object \| null | no | see §2.5 | Per-call overrides that do not change algorithm semantics. |
| `candidates` | array \| null | no | see §2.6 | *Advanced/optional.* Explicit candidate list; repository is used when omitted. |

\* "recommended" = optional at the schema level, but at least one usable signal is
required at runtime; see §5.1 and the minimum-evidence rules in `matching_policy.md`.

**Candidates vs repository:** for the first prototype the endpoint is
**repository-based** — the caller submits only the new complaint and the DDA compares
against its own synthetic repository. The optional `candidates` array exists so a
caller *may* supply its own set (useful for testing or when another agent already has
the candidate list), but it is not the default and the caller is **never** required to
send the whole complaint database.

### 2.2 `location` object

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `facility_id` | string \| null | no | 1–64 chars; e.g. `FAC-CENTRAL-MARKET`. |
| `location_id` | string \| null | no | 1–64 chars; finer-grained than facility, e.g. `LOC-CM-GATE-NORTH`. |
| `latitude` | number \| null | no | −90.0 ≤ lat ≤ 90.0, finite, not NaN. |
| `longitude` | number \| null | no | −180.0 ≤ lon ≤ 180.0, finite, not NaN. |

Rules:
- All four sub-fields are optional; the object itself may be `null`.
- Coordinates must be supplied **as a pair**. Supplying only `latitude` or only
  `longitude` is a **validation error** (`422`).
- Coordinates outside the valid range, or non-finite (`NaN`, `Infinity`), are rejected
  with `422`. (Contrast with *valid-but-far* coordinates, which are a business outcome.)
- Identifier-only locations (facility/location, no coords) are valid and fully usable
  by the identifier path of the `LocationComparator`.

### 2.3 `options` object (all optional)

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `include_candidates` | boolean | `false` | When `true`, include the ranked candidate list in the response (recommended for `REVIEW_REQUIRED`). |
| `max_candidates` | integer | `5` | 1–50; how many ranked candidates to return. |
| `retrieval_window_hours` | integer | server default | Coarse blocking window; see `architecture.md` §6. |
| `weights_override` | object | `null` | **Disabled by default / `TEAM-DECISION`.** If enabled, per-signal weights must be non-negative and sum > 0. Off in V1 to keep scoring reproducible. |

### 2.4 Timestamp requirements

- `reported_at` must be ISO-8601 (`YYYY-MM-DDTHH:MM:SS` with optional fractional
  seconds) **with an explicit UTC offset** (`Z`, `+05:30`, `-08:00`).
- Timestamps **without** an offset are rejected (`422`) — the DDA will not guess the
  timezone (`ASSUMPTION A4`).
- Stored timestamps are compared as absolute instants (converted to UTC internally).
- `reported_at` may be absent; the time signal then becomes `UNAVAILABLE` (§5.2), it is
  **not** treated as "infinitely far away".

### 2.5 `candidates[]` entry (advanced, optional)

Each entry mirrors the comparable fields of a stored incident:

| Field | Type | Required |
| --- | --- | --- |
| `complaint_id` | string | yes |
| `description` | string \| null | no |
| `category` | string \| null | no |
| `location` | object \| null | no |
| `reported_at` | string (ISO-8601) \| null | no |
| `image_hash` | string \| null | no |

Entries with the same `complaint_id` as the request are ignored (self-comparison).

## 3. Response schema

### 3.1 Top-level fields

| Field | Type | Always present | Notes |
| --- | --- | --- | --- |
| `complaint_id` | string | yes | Echoes the request. |
| `decision` | enum | yes | `DUPLICATE` \| `REVIEW_REQUIRED` \| `NEW`. |
| `matched_incident_id` | string \| null | yes | The single best candidate **only** when justified (see §4). `null` for `NEW`, and `null` for `REVIEW_REQUIRED` unless policy allows naming a leading candidate. |
| `score` | number \| null | yes | **Ranking score in [0,1]**, not a calibrated probability. `null` when no candidate could be scored. |
| `signals` | object | yes | Per-signal results for the selected/best candidate (§3.2). |
| `reasons` | array[string] | yes | Explicit reason codes (§3.3). |
| `candidates` | array | when `include_candidates=true` or multiple plausible | Ranked candidate summaries (§3.4). |
| `search` | object | yes | What was searched: `repository_scope`, `eligible_count`, `filters_applied`, `candidates_evaluated`. |
| `policy` | object | yes | Effective `weights`, `high_threshold`, `low_threshold`, `tie_margin`, `policy_version`. Supports reproducibility. |
| `request_id` | string | yes | Correlation id for logs/tracing. |

### 3.2 `signals` object

One key per signal: `text`, `location`, `category`, `time`, `image`.

| Field | Type | Notes |
| --- | --- | --- |
| `status` | enum | `AVAILABLE` \| `UNAVAILABLE` \| `INVALID` \| `ERROR`. |
| `score` | number \| null | Present **only** when `status = AVAILABLE`; range [0,1]. |
| `weight` | number | Effective weight used in normalisation (0 if unavailable or disabled). |
| `details` | object | Signal-specific supporting facts (see §3.5). |

**Hard rule:** when `status != AVAILABLE`, `score` is `null`. Missing evidence is never
silently coerced to `0`.

### 3.3 Reason codes (initial set)

`TEXT_*`, `LOCATION_*`, `CATEGORY_*`, `TIME_*`, `IMAGE_*` per-signal codes plus policy codes:

| Code | Meaning |
| --- | --- |
| `SCORE_ABOVE_HIGH_THRESHOLD` | Normalised score ≥ high threshold. |
| `SCORE_BETWEEN_THRESHOLDS` | Normalised score in the review band. |
| `SCORE_BELOW_LOW_THRESHOLD` | Normalised score < low threshold. |
| `INSUFFICIENT_EVIDENCE` | Fewer than the minimum required available signals. |
| `MISSING_CORE_ANCHOR` | Neither text nor location available/supportive. |
| `CONTRADICTION_LOCATION_MISMATCH` | Very similar text + clearly different location. |
| `CONTRADICTION_CATEGORY_INCOMPATIBLE` | Categories declared incompatible. |
| `AMBIGUOUS_TIED_CANDIDATES` | Top two candidates within `tie_margin`. |
| `NO_ELIGIBLE_CANDIDATES` | Repository returned no eligible records. |
| `SIGNAL_UNAVAILABLE_<NAME>` | A signal could not be computed (missing input). |
| `SIGNAL_INVALID_<NAME>` | A signal input was present but invalid. |
| `SIGNAL_ERROR_<NAME>` | A comparator raised unexpectedly. |
| `SELF_COMPARISON_EXCLUDED` | One or more records matched the request id and were skipped. |
| `REPOSITORY_ERROR` | Candidate retrieval failed (paired with an HTTP 5xx). |
| `IMAGE_SIGNAL_DISABLED` | Image comparator off by default in V1. |

A full code catalog with trigger conditions lives in `matching_policy.md`.

### 3.4 `candidates[]` entry

| Field | Type | Notes |
| --- | --- | --- |
| `complaint_id` | string | Candidate id. |
| `score` | number | Ranking score for that candidate. |
| `rank` | integer | 1-based. |
| `signals` | object | Same shape as §3.2, per candidate. |
| `reasons` | array[string] | Per-candidate reason codes. |
| `contradictions` | array[string] | Disqualifying/flagging codes for that candidate. |

### 3.5 Signal `details` — illustrative

- `text`: `{"method":"tfidf_cosine","token_count_a":14,"token_count_b":13,"shared_terms":["pothole","market","rain"]}`
- `location`: `{"basis":"identifier","distance_m":null,"matched_location_id":"LOC-CM-GATE-NORTH"}`
  or `{"basis":"haversine","distance_m":37.4,"radius_m":500}`
- `category`: `{"relation":"exact" | "compatible" | "incompatible" | "unknown"}`
- `time`: `{"delta_hours":0.58,"decay":"exponential_floor","tau_hours":48,"floor":0.10}`
- `image`: `{"basis":"phash","hamming_distance":6,"threshold":10}`

## 4. Decision representation rules

| Situation | `decision` | `matched_incident_id` | `score` | `candidates` |
| --- | --- | --- | --- | --- |
| Confirmed best candidate, score ≥ high, evidence OK, no contradiction | `DUPLICATE` | the candidate id | its score | optional (top 1) |
| Multiple plausible matches / top two within tie margin | `REVIEW_REQUIRED` | `null` (unless policy names a leader **and flags it**) | top score | **required**, ranked, each with reasons |
| Borderline score in review band | `REVIEW_REQUIRED` | `null` | top score | recommended |
| Contradiction present (location/category) | `REVIEW_REQUIRED` | `null` | top score | required, contradiction codes shown |
| No eligible candidates | `NEW` | `null` | `null` | empty |
| All candidates scored below low threshold | `NEW` | `null` | top score | optional |
| Invalid request | *n/a* | *n/a* | *n/a* | *n/a* — HTTP `422` |
| Repository/comparator failure severe enough to block | *n/a* | *n/a* | *n/a* | *n/a* — HTTP `500/503` |

For `REVIEW_REQUIRED` the response must **not** assert certainty: `matched_incident_id`
stays `null` unless a candidate is explicitly labelled as a *leading candidate for
review*, and the `reasons` array must include the reason it could not be confirmed.

## 5. Degraded and edge inputs

### 5.1 Missing description / location / category / timestamp
These are schema-optional. At runtime the corresponding signal becomes `UNAVAILABLE`
(if absent) or `INVALID` (if present but unusable). Scoring then normalises over the
remaining weights. If fewer than the minimum signals are available, the decision is
downgraded to `REVIEW_REQUIRED` (or `NEW` only if there is genuinely no candidate), and
an `INSUFFICIENT_EVIDENCE` reason is emitted. A request with **no** usable signal at all
returns `200` with `decision = REVIEW_REQUIRED` and `score = null`, **not** an error.

### 5.2 Optional image evidence
Absent or unparseable `image_hash` → image signal `status = UNAVAILABLE` (absent) or
`INVALID` (present but malformed). The `IMAGE_SIGNAL_DISABLED` reason is added when the
comparator is disabled (default in V1). Image evidence never blocks a response.

## 6. Error behaviour (transport-level)

| Condition | HTTP | Body shape |
| --- | --- | --- |
| Schema/validation failure (bad types, bad coords, missing offset, lone coordinate) | `422` | `{"error":{"code":"VALIDATION_ERROR","message":...,"fields":[{"field":"location.latitude","issue":"..."}]}}` |
| Candidate retrieval failed (repository down) | `500` / `503` | `{"error":{"code":"REPOSITORY_ERROR","message":...}}` |
| Unexpected internal error | `500` | `{"error":{"code":"INTERNAL_ERROR","request_id":...}}` |
| Unsupported media type | `415` | standard error body |

Error bodies are **distinct from business outcomes**: a `NEW` decision is `200`, never
a `404`; a duplicate is `200`, never a `409`.

## 7. Worked examples

All examples use the canonical synthetic dataset from `README.md`.

### 7.1 `DUPLICATE`

Request:
```json
{
  "complaint_id": "CMP-2026-0001",
  "description": "Large pothole near the main gate of Central Market causing two-wheeler accidents during rain",
  "category": "ROAD_DAMAGE",
  "location": {
    "facility_id": "FAC-CENTRAL-MARKET",
    "location_id": "LOC-CM-GATE-NORTH",
    "latitude": 12.971598,
    "longitude": 77.594566
  },
  "reported_at": "2026-10-14T09:15:00+05:30",
  "image_hash": null
}
```

Response (`200`):
```json
{
  "complaint_id": "CMP-2026-0001",
  "decision": "DUPLICATE",
  "matched_incident_id": "CMP-2026-0000",
  "score": 0.93,
  "signals": {
    "text":     {"status": "AVAILABLE", "score": 0.84, "weight": 0.40, "details": {"method": "tfidf_cosine", "shared_terms": ["pothole", "central", "market", "rain"]}},
    "location": {"status": "AVAILABLE", "score": 1.00, "weight": 0.30, "details": {"basis": "identifier", "matched_location_id": "LOC-CM-GATE-NORTH"}},
    "category": {"status": "AVAILABLE", "score": 1.00, "weight": 0.15, "details": {"relation": "exact"}},
    "time":     {"status": "AVAILABLE", "score": 0.98, "weight": 0.15, "details": {"delta_hours": 0.58, "decay": "exponential_floor"}},
    "image":    {"status": "UNAVAILABLE", "score": null, "weight": 0.00, "details": {"note": "IMAGE_SIGNAL_DISABLED"}}
  },
  "reasons": [
    "TEXT_SIMILARITY_HIGH",
    "LOCATION_IDENTIFIER_MATCH",
    "CATEGORY_EXACT_MATCH",
    "TIME_WITHIN_WINDOW",
    "SCORE_ABOVE_HIGH_THRESHOLD"
  ],
  "candidates": [
    {"complaint_id": "CMP-2026-0000", "rank": 1, "score": 0.93, "reasons": ["TEXT_SIMILARITY_HIGH", "LOCATION_IDENTIFIER_MATCH"], "contradictions": []}
  ],
  "search": {"repository_scope": "in_memory_default", "eligible_count": 4, "filters_applied": [], "candidates_evaluated": 4},
  "policy": {"weights": {"text": 0.40, "location": 0.30, "category": 0.15, "time": 0.15}, "high_threshold": 0.85, "low_threshold": 0.55, "tie_margin": 0.05, "policy_version": "v1-draft"},
  "request_id": "req-8f2c1a"
}
```

### 7.2 `REVIEW_REQUIRED` (contradiction: similar text, different location)

Using candidate `CMP-2026-0055` (8 km away):
```json
{
  "complaint_id": "CMP-2026-0001",
  "decision": "REVIEW_REQUIRED",
  "matched_incident_id": null,
  "score": 0.52,
  "signals": {
    "text":     {"status": "AVAILABLE", "score": 0.82, "weight": 0.40, "details": {"method": "tfidf_cosine"}},
    "location": {"status": "AVAILABLE", "score": 0.05, "weight": 0.30, "details": {"basis": "haversine", "distance_m": 8043.0, "radius_m": 500}},
    "category": {"status": "AVAILABLE", "score": 1.00, "weight": 0.15, "details": {"relation": "exact"}},
    "time":     {"status": "AVAILABLE", "score": 0.97, "weight": 0.15, "details": {"delta_hours": 0.25}},
    "image":    {"status": "UNAVAILABLE", "score": null, "weight": 0.00, "details": {"note": "IMAGE_SIGNAL_DISABLED"}}
  },
  "reasons": [
    "TEXT_SIMILARITY_HIGH",
    "LOCATION_PROXIMITY_BEYOND_RADIUS",
    "CONTRADICTION_LOCATION_MISMATCH",
    "SCORE_BETWEEN_THRESHOLDS"
  ],
  "candidates": [
    {"complaint_id": "CMP-2026-0055", "rank": 1, "score": 0.52, "reasons": ["TEXT_SIMILARITY_HIGH"], "contradictions": ["CONTRADICTION_LOCATION_MISMATCH"]}
  ],
  "search": {"repository_scope": "in_memory_default", "eligible_count": 4, "filters_applied": [], "candidates_evaluated": 4},
  "policy": {"weights": {"text": 0.40, "location": 0.30, "category": 0.15, "time": 0.15}, "high_threshold": 0.85, "low_threshold": 0.55, "tie_margin": 0.05, "policy_version": "v1-draft"},
  "request_id": "req-9b17de"
}
```

### 7.3 `NEW` (empty repository)

```json
{
  "complaint_id": "CMP-2026-0001",
  "decision": "NEW",
  "matched_incident_id": null,
  "score": null,
  "signals": {},
  "reasons": ["NO_ELIGIBLE_CANDIDATES"],
  "candidates": [],
  "search": {"repository_scope": "in_memory_default", "eligible_count": 0, "filters_applied": [], "candidates_evaluated": 0},
  "policy": {"weights": {"text": 0.40, "location": 0.30, "category": 0.15, "time": 0.15}, "high_threshold": 0.85, "low_threshold": 0.55, "tie_margin": 0.05, "policy_version": "v1-draft"},
  "request_id": "req-1c0a44"
}
```

### 7.4 `422` (lone coordinate + missing offset)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request payload failed validation.",
    "fields": [
      {"field": "location.latitude", "issue": "latitude and longitude must be supplied together"},
      {"field": "reported_at", "issue": "timestamp must include a UTC offset, e.g. 2026-10-14T09:15:00+05:30"}
    ]
  }
}
```

## 8. Contract notes for integration

- **Names may change.** `complaint_id`, `category`, `location_id`, `reported_at` are
  placeholders (`ASSUMPTION A1`). A mapping layer should translate KAVACH's canonical
  names to the DDA V1 names so the algorithms are untouched.
- **Score is a ranking score.** It orders candidates; it is **not** a probability and
  must not be presented to end users as "93% likely a duplicate".
- **`matched_incident_id` is a proposal.** Downstream components decide whether to act.
- **Reproducibility.** Every response echoes the effective `policy` so a result can be
  re-derived after threshold changes.
