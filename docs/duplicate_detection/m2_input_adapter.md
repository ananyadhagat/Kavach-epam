# M2 Input Adapter — Incident Intelligence Handoff

> **Status:** implementation note, not a signed contract. The upstream contract
> is the draft `a1-to-a2-draft-1` handoff from Agent 1. It is **not yet signed
> off** (`[A1-SIGNOFF]`). This document records the mapping the adapter relies
> on, the exact payloads published in the draft, the receiver-side rules that
> remain provisional, and the questions that still need confirmation.
>
> **Contract review (2026-11-01):** both payloads published in the draft —
> complete `INC-2026-001` and proposed minimal `INC-2026-002` — are accepted by
> the adapter with no production-code change. They are reproduced verbatim in
> `tests/conftest.py`. That coverage is draft-contract evidence, not final
> contract validation.

## Scope

`app/adapters/incident_payload.py` converts the **handoff envelope** produced by
Agent 1 into the existing `Complaint` model. It is transport-free and sits
outside `DuplicateDetectionService`; the HTTP edge in `app/api/router.py`
invokes it before calling `check_detailed()`.

The adapter does **not** re-implement Agent 1's mapping from
`StructuredIncidentRecord`. Agent 1's
`src/kavach/services/incident_intelligence/handoff.py` already emits the
canonical V1 keys. Keeping that mapping in one place avoids two competing
interpretations of the ambiguous fields below.

The contract's `GET /api/v1/incidents/{incident_id}/duplicate-detection-request`
endpoint belongs to Agent 1. It returns the payload dictionary directly, without
a wrapper. M3 consumes that dictionary; it does not define or call the endpoint.

## Published contract payloads

The two examples below are copied from the draft contract, sections 4 and 5. The
contract labels every value as an illustrative placeholder, not a captured API
response. The shared pytest fixtures in `tests/conftest.py` keep these exact
values and return deep copies so tests can mutate them safely.

### Complete illustrative payload (`INC-2026-001`)

```json
{
  "complaint_id": "INC-2026-001",
  "description": "Garbage is overflowing near the public park entrance.",
  "category": "WASTE_OVERFLOW",
  "location": {
    "facility_id": null,
    "location_id": null,
    "latitude": 23.2599,
    "longitude": 77.4126
  },
  "reported_at": "2026-10-31T18:30:00+05:30",
  "image_hash": "a1b2c3d4e5f6",
  "kavach_agent1": {
    "contract_version": "a1-to-a2-draft-1",
    "request_id": "REQ-001",
    "category": "SANITATION",
    "incident_type": "WASTE_OVERFLOW",
    "incident_summary": "Garbage overflowing near the park.",
    "severity_recommendation": "MEDIUM",
    "location_source": "USER_SELECTED_PIN",
    "location_check_status": "PASSED",
    "image_sha256": ["example_sha256_hash"],
    "image_perceptual_hashes": ["a1b2c3d4e5f6"],
    "needs_clarification": false
  }
}
```

### Proposed minimal payload (`INC-2026-002`)

The contract explicitly calls this a proposal for the receiver to consider, not
a shape Agent 1 currently emits. Agent 1 currently emits all seven top-level
keys.

```json
{
  "complaint_id": "INC-2026-002",
  "description": "Streetlight is not working.",
  "category": "BROKEN_STREETLIGHT",
  "location": {
    "facility_id": null,
    "location_id": null,
    "latitude": null,
    "longitude": null
  },
  "reported_at": "2026-10-31T19:00:00+05:30",
  "image_hash": null,
  "kavach_agent1": {
    "contract_version": "a1-to-a2-draft-1"
  }
}
```

The adapter preserves the minimal payload's all-null `location` object as a
`Location` whose four fields are all `None`; it does not collapse the object to
`None`.

## Draft mapping

| Agent 1 source | Handoff payload key | `Complaint` field | Rule |
| --- | --- | --- | --- |
| `incident_id` | `complaint_id` | `complaint_id` | Direct. |
| `complaint_text`, fallback `incident_summary` | `description` | `description` | Agent 1 applies the fallback when `complaint_text` is empty/falsy. |
| `incident_type` unless `UNKNOWN`, else `category` | `category` | `category` | Agent 1 prefers the specific incident type; `UNKNOWN` falls back to the broader category. |
| `submitted_at`, fallback `created_at` | `reported_at` | `reported_at` | ISO-8601 with an explicit UTC offset. The app clock is configured for `Asia/Kolkata`. |
| `reported_incident_location` | `location` | `location` | Coordinates come only from the reported location; device GPS is not substituted. `facility_id`/`location_id` are currently `null`. |
| First accepted media item with a non-empty `perceptual_hash`, in media order | `image_hash` | `image_hash` | Optional; may be `null`. All accepted perceptual and SHA-256 hashes also appear under `kavach_agent1`. |
| Agent 1 context | `kavach_agent1` | — | Always emitted by the current sender; documented as ignorable by Agent 2. The adapter drops it. |

## Adapter behaviour

- Accepts a mapping with the canonical handoff keys.
- Drops `kavach_agent1` before validating `Complaint`, including all nested
  content, unknown nested keys and `contract_version`.
- Rejects any other top-level key, including raw `StructuredIncidentRecord`
  names such as `incident_id`, `complaint_text`, `incident_summary`,
  `created_at`, `incident_type` and `submitted_at`.
- Leaves field-level validation to `Complaint` / Pydantic: missing
  `complaint_id`, naive timestamps, lone coordinates, non-finite or out-of-range
  coordinates, unknown `location` fields and length violations raise
  `ValidationError`.
- Raises `IncidentPayloadError` for envelope problems (not a mapping,
  unsupported top-level fields).

Rejecting raw upstream names is deliberate. If Agent 1 renames or adds a field,
the adapter should fail loudly rather than silently ignoring a field whose
meaning has not been agreed.

## Receiver-side rules (provisional)

These rules are implemented and tested, but the draft contract leaves receiver
validation to Agent 2/M3. They stay provisional until `[A1-SIGNOFF]` freezes
them.

| Rule | Current adapter behaviour | Why it is provisional |
| --- | --- | --- |
| Unknown top-level fields | Strict rejection with `IncidentPayloadError`; the offending keys are reported in `unsupported_fields`. | The contract says unknown-field behaviour is not specified by Agent 1 and must be decided by Agent 2/M3. Ignoring instead of rejecting is still possible. |
| `kavach_agent1` | Optional. The whole object is ignored; unknown nested fields and a mismatched `contract_version` are accepted. | The sender always includes it, but receiver-side omission and version enforcement are undefined. |
| `complaint_id` | Required, trimmed, non-empty, 1–64 characters. | The contract does not define M3's required fields; it only supplies a proposed minimal payload. |
| All other `Complaint` fields | Optional. A missing value is preserved as `None`; blank optional strings normalise to `None`. | Minimum acceptance and nullability still need agreement. |
| `location` | Latitude and longitude are pair-only, finite, and range-checked. Identifier-only and all-null locations are valid. | The contract says coordinates may be `null`; it does not define partial-coordinate behaviour. |
| `reported_at` | Optional, but when present it must be timezone-aware; a naive timestamp is rejected rather than guessed. | The contract confirms the `submitted_at` → `created_at` fallback and an `Asia/Kolkata` app clock, but not whether every fallback value is timezone-aware or whether `created_at` is semantically acceptable as report time. The adapter cannot tell which upstream field produced `reported_at`. |
| `image_hash` | Optional; only provisional length validation. | The first-accepted-media rule is documented but not frozen. |

## Questions for the Incident Intelligence owner

1. **Timestamp semantics:** Is `submitted_at` the intended equivalent of
   `reported_at`? The draft confirms `submitted_at` first with a `created_at`
   fallback. Please confirm whether `created_at` is record-creation time rather
   than report time, whether the fallback is always timezone-aware, and whether
   it is acceptable for old records.
2. **Complaint text:** Is `complaint_text` always populated for new records?
   The draft confirms `incident_summary` as the fallback when `complaint_text`
   is empty/falsy. Is that acceptable only for legacy records, or should those
   records be rejected or flagged?
3. **Category:** The mapping is now confirmed: top-level `category` is
   `incident_type` unless it is `UNKNOWN`, in which case the broader category is
   used. Should the Duplicate Detection Agent compare on that specific
   `incident_type` (for example `WASTE_OVERFLOW`) or on the broader
   department-level `category` (for example `SANITATION`)?
4. **Location:** The draft confirms that only `reported_incident_location` is
   sent, and that device GPS / EXIF must never be promoted to it. Will
   `facility_id` / `location_id` remain `null`, or will a facility lookup
   populate them later? Should a partial coordinate pair be rejected (current
   receiver behaviour) or repaired?
5. **Image evidence:** The draft confirms “first accepted media item with a
   non-empty perceptual hash, in media order”. Is that rule final? Should the
   adapter receive all hashes from `kavach_agent1` instead of only
   `image_hash`?
6. **Extra context:** The sender always includes `kavach_agent1`, and the
   docstring says Agent 2 may ignore it. Must the receiver require it, and must
   the adapter enforce a contract version? Current behaviour is optional and
   unversioned.
7. **Minimum payload:** The contract's minimal example keeps all seven top-level
   keys. Which fields must the receiver actually require, and which may be
   omitted or `null`?
8. **Unknown fields:** Should unknown top-level fields be rejected (current
   behaviour) or ignored? Should unknown nested `kavach_agent1` fields remain
   harmless?
9. **Contract sign-off:** `a1-to-a2-draft-1` is provisional. When the contract
   is frozen, confirm the field names, the timestamp/text fallbacks, the
   receiver-side rules above, and the final contract version.

## Tests

Shared exact-payload fixtures live in `tests/conftest.py`. The published-payload
coverage there is exercised by:

- `test_complete_contract_payload_maps_to_complaint`
- `test_minimal_contract_payload_maps_to_complaint`
- `test_complete_contract_payload_is_not_mutated`
- `test_unknown_nested_kavach_agent1_fields_are_ignored`
- `test_contract_version_is_not_enforced`
- `test_unknown_top_level_field_on_contract_payload_is_rejected`
- `test_non_finite_coordinate_is_rejected` (NaN and both infinities, for each
  axis)

`tests/test_incident_payload_adapter.py` also covers representative full and
minimal payloads, missing optional fields, blank-string normalisation,
identifier-only locations, invalid values, raw/ambiguous upstream fields,
HTTP-only fields and non-mapping input.

`tests/test_detection_service.py` adds the adapter → service seam:

- `test_contract_payload_reaches_service_and_empty_retrieval_is_new` runs both
  published payloads through `to_complaint()` and the service, and asserts an
  empty retrieval is `NEW`.
- `test_contract_payload_can_match_an_existing_candidate` runs the complete
  payload through the full pipeline to a `DUPLICATE` decision.
