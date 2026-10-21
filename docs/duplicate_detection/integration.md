# KAVACH Inter-Agent Integration Contract

> Phase 1 design document for a 10-member project. This section states what the
> Duplicate Detection Agent (DDA) **needs** from the rest of KAVACH and what it
> **returns**. Component roles below are **conceptual**; the real agents may have other
> names (`TEAM-DECISION`). The DDA never updates another agent's database and never
> takes over another agent's responsibility.

## 1. Boundaries (hard rules)

- The DDA is **read-only** with respect to complaint data. It proposes; it does not
  merge, delete, or overwrite.
- The DDA does not own the master complaint store, does not modify lifecycle state,
  and does not notify users or dashboards.
- The DDA does not call other agents' private databases directly. It reads candidates
  through **either** (a) a shared/own repository it is given, **or** (b) an explicit
  `candidates[]` list supplied in the request. `TEAM-DECISION D2` chooses which.
- The DDA's internal algorithm is private. Callers interact only through the V1
  contract; they never need to know the comparators or thresholds.

## 2. Upstream dependency (conceptual)

**Role: Complaint Submission / Incident Ingestion.**
Provides the new complaint that must be checked. It is the only required input source.

| Needs from upstream | Type | Notes |
| --- | --- | --- |
| `complaint_id` | string | The id used to exclude self-comparison. |
| `description` | string \| null | Optional but strongly improves text signal. |
| `category` | string \| null | Opaque code; mapped via the compatibility table. |
| `location` (`facility_id`, `location_id`, `latitude`, `longitude`) | object \| null | Any subset; coordinates as a pair. |
| `reported_at` | ISO-8601 + offset \| null | Must carry an explicit offset. |
| `image_hash` | string \| null | Optional. |

`TEAM-DECISION`: whether ingestion calls the DDA synchronously *before* persisting the
complaint, or the complaint is persisted first and the DDA is called afterwards. The
former risks the candidate never being its own repository record (good for
self-comparison); the latter requires reliable self-exclusion (already handled).

## 3. Downstream consumers (conceptual)

| Role | What it consumes from the DDA | What it must NOT expect |
| --- | --- | --- |
| **Supervisor / Review workflow** | `decision`, `score`, `matched_incident_id` (may be null), `candidates[]` with `reasons`/`contradictions` | A certainty claim. `REVIEW_REQUIRED` means a human decides. |
| **Complaint-management service** | `matched_incident_id` (the proposed relationship) and `reasons` | Any mutation by the DDA. It records the relationship itself. |
| **Dashboard / reporting** | `decision`, `score`, `reasons`, `search.scope` | A calibrated probability — `score` is a **ranking score only**. |

Error/edge awareness: consumers must treat `NEW` as "not found in scope", not "proven
unique", and must surface `search.scope` when displaying `NEW`.

## 4. The minimal integration surface

### 4.1 Invocation
```
POST {dda_base_url}/api/v1/duplicate-detection/check
Content-Type: application/json
```
Full schema in `api_contract.md`. V1 is **synchronous** (`ASSUMPTION`).

### 4.2 Required request fields (types)
| Field | Type | Required |
| --- | --- | --- |
| `complaint_id` | string | yes |
| `description` | string \| null | recommended |
| `category` | string \| null | recommended |
| `location` | object \| null | recommended |
| `reported_at` | ISO-8601 string \| null | recommended |
| `image_hash` | string \| null | no |

### 4.3 Response fields (types)
| Field | Type | Notes |
| --- | --- | --- |
| `complaint_id` | string | echo |
| `decision` | `"DUPLICATE"` \| `"REVIEW_REQUIRED"` \| `"NEW"` | business outcome |
| `matched_incident_id` | string \| null | proposal only |
| `score` | number \| null | **ranking score**, not probability |
| `signals` | object | per-signal status/score/details |
| `reasons` | string[] | reason codes |
| `candidates` | array (optional) | ranked, with reasons/contradictions |
| `search` | object | scope/reproducibility |
| `policy` | object | effective weights/thresholds/version |
| `request_id` | string | correlation id |

### 4.4 Error behaviour
- `422` — invalid request (bad types, lone coordinate, missing offset). Body:
  `{"error":{"code":"VALIDATION_ERROR","fields":[...]}}`.
- `500`/`503` — `REPOSITORY_ERROR` / `INTERNAL_ERROR`. A failure is **never** returned
  as `NEW`.
- All three decisions return `200`. Callers must branch on `decision`, not on status code.

### 4.5 Candidate ID conventions
- `complaint_id` values are **opaque strings** to the DDA (1–64 chars). The DDA echoes
  and compares them but does not parse structure.
- `TEAM-DECISION`: whether KAVACH ids are numeric, UUIDs, or prefixed
  (`CMP-2026-0001`). The DDA accepts any stable string.

### 4.6 Category identifier conventions
- Treated as opaque strings; matching is exact (case-insensitive) or via the
  compatibility table.
- `TEAM-DECISION D3`: the canonical category vocabulary. Until fixed, the DDA ships a
  placeholder map and marks unknown relations `UNAVAILABLE` (never a penalty).

### 4.7 Location representation
- Preferred: `location_id` (finest) ≥ `facility_id` (coarser), with optional
  `latitude`/`longitude` as a fallback pair.
- `TEAM-DECISION`: the canonical location id scheme and whether a shared geocoding
  standard (WGS84 decimal degrees) is used.

### 4.8 Timestamp conventions
- ISO-8601 with an explicit UTC offset (`Z` or `±HH:MM`). Offsets are **required**.
- Internally normalised to UTC before comparison.
- `TEAM-DECISION`: confirm the agreed storage/transport format.

### 4.9 Sync vs async
- **V1: synchronous.** Simple, deterministic, easy to demo and test.
- **Future/async option:** `202 Accepted` + `request_id`, result retrieved via polling or
  a callback/webhook. Only worth it if complaint volume or latency demands it.

### 4.10 Invoke without knowing the algorithm
Callers send the documented request and read the documented response. They never
import comparators, never pass thresholds, and never depend on reason-code *strings*
beyond treating them as opaque, displayable, and loggable labels. New reason codes must
be additive and must not break consumers (treat `reasons` as an open set).

## 5. Contracts the team should agree **before** final integration

Priority order (P1 = blocks integration):

| # | Decision | Why it blocks | Owner |
| --- | --- | --- | --- |
| P1 | **Integration model A vs B** (in-process import vs standalone service). | Determines how everyone calls the DDA. | Whole team |
| P1 | **Data access path for candidates** — shared DB, an aggregation API, or caller-supplied `candidates[]`. | The DDA cannot retrieve without it. | DDA + storage/ingestion owners |
| P1 | **Canonical `complaint_id` scheme** (and candidate id stability). | Self-exclusion and match reporting depend on it. | Ingestion + all |
| P1 | **Canonical category vocabulary + compatibility table.** | Category signal and contradiction C2 depend on it. | Relevant domain agents + DDA |
| P2 | **Location identifier scheme** (`facility_id`/`location_id`) and geocode standard. | Location signal quality. | Location/mapping owner + DDA |
| P2 | **Timestamp format + timezone policy.** | Time signal correctness. | Ingestion + DDA |
| P2 | **Sync vs async invocation.** | Affects every caller's code path. | Whole team |
| P3 | **Field-name mapping** between KAVACH canonical names and DDA V1 names. | Cosmetic but must be settled to avoid drift. | DDA + ingestion |
| P3 | **Whether image evidence is used at all**, and its hash algorithm. | Optional signal; weight 0 until decided. | DDA + image owner |
| P3 | **Score presentation rule** ("ranking score, not probability") in any UI. | Avoids misleading users. | Dashboard owner + DDA |

## 6. Versioning
- The path carries `v1`. Additive changes (new optional request field, new reason code)
  stay in `v1`. Breaking changes (renamed/removed fields, changed decision semantics)
  require `v2`.
- Every response echoes `policy.policy_version` and a `request_id` for auditability.

## 7. Assumptions / unresolved decisions

| ID | Type | Statement |
| --- | --- | --- |
| I-A1 | `ASSUMPTION` | No shared auth is required for the prototype. `TEAM-DECISION`: the auth scheme for the service. |
| I-A2 | `ASSUMPTION` | The DDA is the system of record for *no* complaint; it reads a repository interface. |
| I-D1 | `TEAM-DECISION` | Integration A vs B (§5 P1). |
| I-D2 | `TEAM-DECISION` | Candidate data access path (§5 P1). |
| I-D3 | `TEAM-DECISION` | Category vocabulary and location scheme (§5 P1/P2). |
| I-D4 | `TEAM-DECISION` | Sync vs async and required auth. |
