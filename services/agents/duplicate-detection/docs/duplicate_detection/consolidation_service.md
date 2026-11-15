# Consolidation Service

> **Status: implemented and tested against SQLite; PostgreSQL migration and
> concurrency behaviour are not yet verified in this environment.** The service
> is additive: it does not change the M3 scoring engine, the M4 decision policy,
> or the `POST /internal/v1/duplicate-detection/check` wire contract.

## 1. Purpose and scope

The consolidation service turns an advisory M3 result into durable complaint
state. It receives one Agent 1 complaint at a time, stores it, runs the existing
M3 service against already-consolidated complaints, and then records the outcome:

| M3 decision | Stored result |
| --- | --- |
| `NEW` | The complaint becomes the **primary** of a new `OPEN` group and receives a `PRIMARY` link. |
| `DUPLICATE` | The complaint receives a `DUPLICATE` link to the matched incident's canonical primary. The group's duplicate counters are incremented atomically. |
| `REVIEW_REQUIRED` | A pending review is created. The complaint receives **no** group link and **no** counter changes. The review stores the policy's top-ranked candidate as a suggestion in `leading_candidate_id`; it is never treated as a confirmed match. |

Every complaint is stored individually and is never deleted, merged, or
overwritten. The primary is a pointer, not a replacement record.

In scope:

- complaint persistence and read models;
- group, link and review persistence;
- idempotent ingestion;
- atomic duplicate counters;
- five internal HTTP endpoints.

Out of scope in this version:

- human resolution of pending reviews;
- closing or reopening groups;
- re-parenting a group to a different primary;
- authentication/authorization and rate limiting;
- asynchronous ingestion or a queue;
- production calibration of M3/M4.

## 2. Where it lives

```
app/
  config/database.py            # env-driven database URL selection
  db/
    base.py                     # declarative Base
    models.py                   # five ORM tables
    session.py                  # engine/session factory, SQLite pragmas
  repositories/
    consolidation.py            # thin persistence helpers + atomic counter update
    sql_complaint.py            # ComplaintRepository adapters over the DB
  schemas/consolidation.py      # request/response models
  services/
    consolidation_errors.py     # domain error codes + HTTP status hints
    consolidation_service.py    # ingestion, idempotency, decision mapping
  api/
    consolidation_dependencies.py
    consolidation_router.py     # /internal/v1/consolidation/*
  api/app.py                    # optional router mounting
  main.py                       # DB-backed runtime when a URL is configured
alembic/
  env.py
  versions/0001_consolidation.py
tests/
  test_consolidation.py
  test_consolidation_api.py
  test_consolidation_migration.py
```

M3 code (`app/scoring/`, `app/comparators/`,
`app/services/detection_service.py`) is unchanged. The service calls
`DuplicateDetectionService.check_detailed()` and persists its result.

## 3. Data model

All five tables live in one schema and are created by migration
`0001_consolidation`.

### `complaints`

One row per accepted complaint. The canonical `Complaint` model is stored twice:
as typed columns used for retrieval and as a JSON `payload` snapshot for audit.
`complaint_id` remains the existing opaque 1–64 character string from the
contract.

### `consolidation_groups`

| Column | Meaning |
| --- | --- |
| `group_id` | UUID4 string primary key. |
| `primary_complaint_id` | Canonical complaint; unique, so a complaint can lead at most one group. |
| `status` | `OPEN` or `CLOSED` (check constraint). |
| `active_duplicate_count` | Duplicates currently linked to the group. |
| `historical_duplicate_count` | Duplicates ever linked; never decremented. |
| `creation_reason` | Currently `M3_NEW`. |
| `created_at` / `closed_at` | Timezone-aware timestamps. |

`member_count` in API responses is derived as
`active_duplicate_count + 1` (primary plus active duplicates).

### `consolidation_links`

Exactly one link per consolidated complaint (`complaint_id` is unique). A
`PRIMARY` link points at the group's canonical complaint; a `DUPLICATE` link
records the M3 evidence and the incident M3 actually matched
(`matched_incident_id`). That matched incident may itself be a duplicate; the
link still belongs to the same group, and `primary_complaint_id` in responses is
the group's canonical primary.

### `consolidation_reviews`

One row per `REVIEW_REQUIRED` complaint, with `status` `OPEN`/`CLOSED`. A review
complaint has no link. `leading_candidate_id` is the policy's top-ranked
candidate suggestion, copied from `DecisionOutcome.leading_candidate_id`; it is
advice for the human reviewer, not a confirmed match. This version only creates
reviews; it does not close them.

### `consolidation_requests`

Idempotency record: `idempotency_key` (primary key), `complaint_id` (unique),
SHA-256 `fingerprint`, stored `response_status` and `response_body`, and a
timestamp. Storing the response body is what makes a retry byte-for-byte
repeatable.

Foreign keys use `ON DELETE RESTRICT`; complaints are the system of record and
must not disappear underneath groups.

## 4. Ingestion flow

```
POST /internal/v1/consolidation/complaints
        |
        v
validate Idempotency-Key (required, printable ASCII, 1-128, no spaces)
        |
        v
validate Agent 1 payload -> Complaint
        |
        v
BEGIN transaction
  replay?  -- yes --> return stored response (Idempotent-Replay: true)
  duplicate complaint id? -- yes --> 409 COMPLAINT_ALREADY_EXISTS
  insert complaint
  run M3 check_detailed() over consolidated complaints in this transaction
  switch decision:
    NEW              -> insert group + PRIMARY link
    DUPLICATE        -> resolve matched incident's group
                        reject unknown / unconsolidated / closed
                        insert DUPLICATE link
                        atomic increment of both counters
    REVIEW_REQUIRED  -> insert review (no link)
  store idempotency response snapshot
COMMIT
        |
        v
201 ConsolidationResult
```

### Candidate visibility

Candidate retrieval joins `complaints` to `consolidation_links`. Therefore:

- primaries and duplicates are visible to M3;
- complaints waiting in the review queue are **not** visible until a human
  resolves them.

This is the approved default. It prevents an unresolved review from silently
influencing later decisions, but it means review resolution (not implemented
here) must eventually create/attach a link.

### `DUPLICATE` resolution rules

`matched_incident_id` is resolved through `consolidation_links`:

1. no link and no complaint → `409 MATCHED_PRIMARY_NOT_FOUND`;
2. complaint exists but has no link (for example, it is pending review) →
   `409 MATCHED_PRIMARY_NOT_CONSOLIDATED`;
3. link exists but its group is `CLOSED` → `409 GROUP_CLOSED`;
4. otherwise the duplicate joins the matched link's group.

The link stores the raw M3 match, not a rewritten primary id, so the evidence
stays faithful.

## 5. Idempotency and concurrency

### Idempotency

- `Idempotency-Key` is required. Missing, blank, whitespace-containing, or
  longer-than-128-character keys return `422 INVALID_IDEMPOTENCY_KEY`.
- The fingerprint is a SHA-256 over the canonical JSON form of `Complaint`
  (sorted keys, compact separators, JSON-mode values).
- Same key + same payload → the stored response is returned with
  `Idempotent-Replay: true` and HTTP `201`.
- Same key + different payload → `409 IDEMPOTENCY_KEY_REUSED`.
- Same complaint id + different key → `409 COMPLAINT_ALREADY_EXISTS`, with a
  message advising reuse of the original key.

### Transactions and races

- Each ingestion opens one session and one transaction. A failure rolls back
  the complaint, group, link, review, counter change, and idempotency record
  together.
- Duplicate counters are updated with a single SQL statement:
  `UPDATE ... SET active = active + 1, historical = historical + 1 WHERE group_id = :id AND status = 'OPEN'`.
  The update is atomic at the database level and does not use read-modify-write.
- If two writers race on a unique constraint, the service re-reads once. If the
  winner stored the same idempotency key and payload, the loser replays it;
  otherwise the domain conflict is returned. A second unrecoverable integrity
  failure becomes `500 INTERNAL_ERROR`.
- SQLAlchemy failures become `503 DATABASE_UNAVAILABLE`; unexpected failures
  become `500 INTERNAL_ERROR`.

Atomic counters are implemented, but **multi-process concurrency has only been
exercised with SQLite in tests**. PostgreSQL row locking and isolation behaviour
still need a real PostgreSQL test run.

## 6. HTTP API

Base path: `/internal/v1/consolidation`

These routes exist only when a consolidation service is configured (see §8).
When it is not, they return `404`.

All errors use:

```json
{
  "detail": {
    "code": "MACHINE_CODE",
    "message": "Human-readable explanation."
  }
}
```

### `POST /complaints`

Required header: `Idempotency-Key`.

The body is the existing Agent 1 handoff envelope (the same payload accepted by
`POST /internal/v1/duplicate-detection/check`), translated by
`app/adapters/incident_payload.py`.

Response `201`:

```json
{
  "complaint_id": "INC-2026-001",
  "consolidation_status": "PRIMARY",
  "decision": "NEW",
  "group_id": "73092aeb-b8d4-48ef-9228-d1a2dcab683a",
  "primary_complaint_id": "INC-2026-001",
  "matched_incident_id": null,
  "leading_candidate_id": null,
  "score": null,
  "reasons": ["SCORE_ABOVE_HIGH_THRESHOLD"],
  "active_duplicate_count": 0,
  "historical_duplicate_count": 0,
  "review_id": null,
  "idempotent_replay": false
}
```

A duplicate response (201):

```json
{
  "complaint_id": "INC-2026-002",
  "consolidation_status": "DUPLICATE",
  "decision": "DUPLICATE",
  "group_id": "73092aeb-b8d4-48ef-9228-d1a2dcab683a",
  "primary_complaint_id": "INC-2026-001",
  "matched_incident_id": "INC-2026-001",
  "leading_candidate_id": null,
  "score": 0.94,
  "reasons": ["SCORE_ABOVE_HIGH_THRESHOLD"],
  "active_duplicate_count": 1,
  "historical_duplicate_count": 1,
  "review_id": null,
  "idempotent_replay": false
}
```

A review response (201):

```json
{
  "complaint_id": "INC-2026-003",
  "consolidation_status": "PENDING_REVIEW",
  "decision": "REVIEW_REQUIRED",
  "group_id": null,
  "primary_complaint_id": null,
  "matched_incident_id": null,
  "leading_candidate_id": "INC-2026-001",
  "score": 0.61,
  "reasons": ["SCORE_ABOVE_HIGH_THRESHOLD"],
  "active_duplicate_count": 0,
  "historical_duplicate_count": 0,
  "review_id": "69149f70-80ad-4962-a1c9-55177c8ff263",
  "idempotent_replay": false
}
```

Replays additionally carry `Idempotent-Replay: true` and keep the original
counts and ids.

### `GET /complaints/{complaint_id}`

Returns the canonical complaint, its status, the group summary when linked, the
review when pending, and `received_at`.

```json
{
  "complaint": {
    "complaint_id": "INC-2026-002",
    "description": "Garbage is still overflowing near the park.",
    "category": "WASTE_OVERFLOW",
    "location": {
      "facility_id": null,
      "location_id": null,
      "latitude": 23.2599,
      "longitude": 77.4126
    },
    "reported_at": "2026-10-31T18:30:00Z",
    "image_hash": "a1b2c3d4e5f6"
  },
  "consolidation_status": "DUPLICATE",
  "group": {
    "group_id": "73092aeb-b8d4-48ef-9228-d1a2dcab683a",
    "primary_complaint_id": "INC-2026-001",
    "status": "OPEN",
    "active_duplicate_count": 1,
    "historical_duplicate_count": 1,
    "member_count": 2,
    "created_at": "2026-11-03T20:16:26.839206Z",
    "closed_at": null
  },
  "review": null,
  "received_at": "2026-11-03T20:16:26.852421Z"
}
```

Errors: `404 COMPLAINT_NOT_FOUND`, `409 COMPLAINT_NOT_CONSOLIDATED`,
`503 DATABASE_UNAVAILABLE`.

### `GET /groups`

Query parameters:

| Name | Default | Constraints |
| --- | --- | --- |
| `status` | none (all) | `OPEN` or `CLOSED` |
| `limit` | `50` | 1–200 |
| `offset` | `0` | ≥ 0 |

```json
{
  "items": [
    {
      "group_id": "73092aeb-b8d4-48ef-9228-d1a2dcab683a",
      "primary_complaint_id": "INC-2026-001",
      "status": "OPEN",
      "active_duplicate_count": 1,
      "historical_duplicate_count": 1,
      "member_count": 2,
      "created_at": "2026-11-03T20:16:26.839206Z",
      "closed_at": null
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### `GET /groups/{group_id}`

Returns the group summary plus the primary complaint and every active duplicate
with its link evidence.

```json
{
  "group_id": "73092aeb-b8d4-48ef-9228-d1a2dcab683a",
  "primary_complaint_id": "INC-2026-001",
  "status": "OPEN",
  "active_duplicate_count": 1,
  "historical_duplicate_count": 1,
  "member_count": 2,
  "created_at": "2026-11-03T20:16:26.839206Z",
  "closed_at": null,
  "primary": {
    "complaint_id": "INC-2026-001",
    "description": "Garbage is overflowing near the public park entrance.",
    "category": "WASTE_OVERFLOW",
    "location": {
      "facility_id": null,
      "location_id": null,
      "latitude": 23.2599,
      "longitude": 77.4126
    },
    "reported_at": "2026-10-31T18:30:00Z",
    "image_hash": "a1b2c3d4e5f6"
  },
  "duplicates": [
    {
      "complaint": {
        "complaint_id": "INC-2026-002",
        "description": "Garbage is still overflowing near the park.",
        "category": "WASTE_OVERFLOW",
        "location": {
          "facility_id": null,
          "location_id": null,
          "latitude": 23.2599,
          "longitude": 77.4126
        },
        "reported_at": "2026-10-31T18:30:00Z",
        "image_hash": "a1b2c3d4e5f6"
      },
      "link_id": "c44a68a7-37a5-476d-9f68-6de1bce15f95",
      "matched_incident_id": "INC-2026-001",
      "match_score": 0.94,
      "reasons": ["SCORE_ABOVE_HIGH_THRESHOLD"],
      "linked_at": "2026-11-03T20:16:26.852421Z"
    }
  ]
}
```

Errors: `404 GROUP_NOT_FOUND`, `503 DATABASE_UNAVAILABLE`.

### `GET /review-queue`

Query parameters: `status` defaults to `OPEN`; `limit` and `offset` as above.
Passing no `status` therefore returns open reviews; the parameter accepts
`OPEN` or `CLOSED`.

```json
{
  "items": [
    {
      "review_id": "69149f70-80ad-4962-a1c9-55177c8ff263",
      "complaint_id": "INC-2026-003",
      "status": "OPEN",
      "decision": "REVIEW_REQUIRED",
      "leading_candidate_id": "INC-2026-001",
      "score": 0.61,
      "reasons": ["SCORE_ABOVE_HIGH_THRESHOLD"],
      "created_at": "2026-11-03T20:16:26.852421Z",
      "resolved_at": null,
      "complaint": {
        "complaint_id": "INC-2026-003",
        "description": "Waste may be piling up by the park.",
        "category": "WASTE_OVERFLOW",
        "location": {
          "facility_id": null,
          "location_id": null,
          "latitude": 23.2599,
          "longitude": 77.4126
        },
        "reported_at": "2026-10-31T18:30:00Z",
        "image_hash": "a1b2c3d4e5f6"
      }
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

The example values above were captured from a local run with a stubbed M3
service; timestamps and ids vary per run.

## 7. Error catalog

| HTTP | Code | Meaning |
| --- | --- | --- |
| 404 | `COMPLAINT_NOT_FOUND` | No stored complaint with that id. |
| 404 | `GROUP_NOT_FOUND` | No group with that id. |
| 409 | `COMPLAINT_ALREADY_EXISTS` | Complaint id already stored under another idempotency key. |
| 409 | `COMPLAINT_NOT_CONSOLIDATED` | Stored complaint has no link and no review. |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Key reused with a different payload. |
| 409 | `MATCHED_PRIMARY_NOT_FOUND` | M3 matched an incident that is not stored. |
| 409 | `MATCHED_PRIMARY_NOT_CONSOLIDATED` | M3 matched a stored complaint with no group link. |
| 409 | `GROUP_CLOSED` | The target group no longer accepts duplicates. |
| 422 | `INVALID_COMPLAINT_PAYLOAD` | Payload failed Agent 1/`Complaint` validation. |
| 422 | `INVALID_IDEMPOTENCY_KEY` | Missing or malformed `Idempotency-Key`. |
| 500 | `INTERNAL_ERROR` | Unexpected failure. |
| 503 | `DATABASE_UNAVAILABLE` | Database query/connection failure. |
| 504 | `DUPLICATE_CHECK_TIMEOUT` | M3 raised `TimeoutError`. |

## 8. Runtime configuration

`app.main` builds the consolidation runtime only when `KAVACH_DATABASE_URL` or
`DATABASE_URL` is set (first non-blank wins). Without either variable it keeps
the original zero-configuration app: an empty in-memory M3 repository and no
consolidation routes.

When consolidation is configured and no M3 service is injected, the read-only
`POST /internal/v1/duplicate-detection/check` route uses
`ConsolidationService.build_detection_service()`, which reads persisted,
consolidated complaints through short read-only sessions. `/check` never
writes.

`create_app(service=None, *, consolidation_service=None)` remains backward
compatible. Passing only `service` keeps the old behaviour; passing
`consolidation_service` additionally mounts the consolidation router and uses
its DB-backed M3 service for `/check` unless `service` is supplied explicitly.

## 9. Migrations

Alembic reads the URL from `KAVACH_DATABASE_URL`, then `DATABASE_URL`, then a
non-blank `sqlalchemy.url` in `alembic.ini`. With none configured it raises
`RuntimeError("No database URL configured...")` instead of silently targeting a
default database.

```powershell
$env:KAVACH_DATABASE_URL = "postgresql+psycopg2://kavach:secret@localhost:5432/kavach"
alembic upgrade head
alembic downgrade base   # removes only the five consolidation tables
```

For a throwaway local SQLite database:

```powershell
$env:KAVACH_DATABASE_URL = "sqlite:///./kavach_local.db"
alembic upgrade head
```

Migration `0001_consolidation` creates `complaints`, `consolidation_groups`,
`consolidation_links`, `consolidation_reviews` and `consolidation_requests`,
with their uniques, indexes, foreign keys and check constraints. The downgrade
drops them in dependency order. JSON columns use `JSONB` on PostgreSQL and
plain `JSON` elsewhere.

### Verification status

- `alembic upgrade head` and `alembic downgrade base` were executed against
  temporary SQLite files.
- Generated DDL was inspected for SQLite; PostgreSQL-specific DDL
  (`JSONB`, timezone handling, constraint names) has **not** been applied to a
  live PostgreSQL server here. PostgreSQL 18 is installed locally, but the
  `postgres` password is unknown and no Docker runtime is available.
- Run the migration against PostgreSQL before treating the schema as verified.

## 10. Tests

| File | Coverage |
| --- | --- |
| `tests/test_consolidation.py` | Decision mapping, idempotency replay/reuse, duplicate-of-duplicate resolution, unknown/unconsolidated/closed errors, rollback, timestamps, pagination, review exclusion from M3 candidates. |
| `tests/test_consolidation_api.py` | All five routes, validation envelopes, replay header, pagination bounds, default-app 404 compatibility. |
| `tests/test_consolidation_migration.py` | Upgrade/downgrade, tables, columns, uniques, indexes, check/FK constraints, constraint enforcement, missing-URL error. |

Run them with:

```powershell
python -m pytest tests/test_consolidation.py tests/test_consolidation_api.py tests/test_consolidation_migration.py -q
```

The tests use in-memory/file SQLite with `PRAGMA foreign_keys=ON`. SQLite
in-memory sessions use a `StaticPool` so all sessions share one database.

## 11. Known limitations and open questions

- **PostgreSQL is unverified.** Migration and concurrent-ingestion behaviour
  have only been exercised on SQLite. The atomic counter SQL is portable, but
  isolation and lock behaviour must be tested on the target PostgreSQL version.
- **No review resolution API.** Pending-review complaints stay invisible to M3
  and retain no link until a future endpoint (or operator) resolves them. Who
  owns that workflow is unresolved.
- **No group close/reopen API.** `CLOSED` is modelled and rejected on ingestion
  (`GROUP_CLOSED`), but nothing transitions a group to `CLOSED` yet.
- **ID-format mismatch.** Generated group/link/review ids are UUID4 strings;
  Agent 1 and `Complaint` keep opaque complaint ids. Agent 3's UUID preference
  remains a team decision.
- **Agent 1 receiver-side policy is provisional** under `[A1-SIGNOFF]`.
- **Retrieval completeness** is `COMPLETE` for the DB-backed adapter because it
  reads the entire consolidated set in one transaction. A future blocking or
  windowed adapter must report `PARTIAL` unless it can prove completeness.
  Production completeness remains `[RETRIEVAL-OPEN]`.
- **Idempotency records grow without bound.** There is no retention or cleanup
  policy for `consolidation_requests`.
- **No authentication.** The routes are under `/internal`, but nothing enforces
  network or caller identity.
