# M2 Input Adapter — Incident Intelligence Handoff

> **Status:** implementation note. The upstream contract is the draft
> `a1-to-a2-draft-1` handoff on the `origin/incident-intelligence-agent` branch.
> It is **not yet signed off** by both agents. This document records the
> mapping the adapter relies on and the questions that still need confirmation.

## Scope

`app/adapters/incident_payload.py` converts the **handoff envelope** produced by
Agent 1 into the existing `Complaint` model. It is transport-free and sits
outside both `DuplicateDetectionService` and the deferred HTTP layer.

The adapter does **not** re-implement Agent 1's mapping from
`StructuredIncidentRecord`. Agent 1's
`src/kavach/services/incident_intelligence/handoff.py` already emits the
canonical V1 keys. Keeping that mapping in one place avoids two competing
interpretations of the ambiguous fields below.

## Draft mapping

| Agent 1 source | Handoff payload key | `Complaint` field | Rule |
| --- | --- | --- | --- |
| `incident_id` | `complaint_id` | `complaint_id` | Direct. |
| `complaint_text`, fallback `incident_summary` | `description` | `description` | Agent 1 applies the fallback for old records. |
| `incident_type` unless `UNKNOWN`, else `category` | `category` | `category` | Agent 1 prefers the specific incident type. |
| `submitted_at`, fallback `created_at` | `reported_at` | `reported_at` | ISO-8601 with an explicit UTC offset. |
| `reported_incident_location` | `location` | `location` | Latitude/longitude only. Device GPS, EXIF and facility reference are not used as the incident location. `facility_id`/`location_id` are currently `null`. |
| First accepted image's `perceptual_hash` | `image_hash` | `image_hash` | Optional. |
| Agent 1 context | `kavach_agent1` | — | Documented as ignorable by Agent 2; the adapter drops it. |

## Adapter behaviour

- Accepts a mapping with the canonical handoff keys.
- Drops `kavach_agent1` before validating `Complaint`.
- Rejects any other top-level key, including raw `StructuredIncidentRecord`
  names such as `incident_id`, `complaint_text`, `incident_summary`,
  `created_at`, `incident_type` and `submitted_at`.
- Leaves field-level validation to `Complaint` / Pydantic: missing
  `complaint_id`, naive timestamps, lone coordinates, out-of-range coordinates,
  unknown `location` fields and length violations raise `ValidationError`.
- Raises `IncidentPayloadError` for envelope problems (not a mapping,
  unsupported top-level fields).

Rejecting raw upstream names is deliberate. If Agent 1 renames or adds a field,
the adapter should fail loudly rather than silently ignoring a field whose
meaning has not been agreed.

## Questions for the Incident Intelligence owner

1. **Timestamp semantics:** Is `submitted_at` the intended equivalent of
   `reported_at`? The draft uses `submitted_at` first and falls back to
   `created_at`. Please confirm whether `created_at` is record-creation time
   rather than report time, and whether the fallback is acceptable for old
   records.
2. **Complaint text:** Is `complaint_text` always populated for new records?
   Is `incident_summary` an acceptable fallback only for legacy records, or
   should those records be rejected or flagged?
3. **Category:** Should the Duplicate Detection Agent compare on the specific
   `incident_type` (for example `WASTE_OVERFLOW`) or on the department-level
   `category` (for example `SANITATION`)? The draft prefers `incident_type`
   unless it is `UNKNOWN`.
4. **Location:** Confirm that only `reported_incident_location` is sent as the
   incident location, and that device GPS / EXIF must never be promoted to it.
   Will `facility_id` / `location_id` remain `null`, or will a facility lookup
   populate them later?
5. **Image evidence:** If several images are accepted, is “first accepted image”
   deterministic and the agreed choice for `image_hash`? Should the adapter
   receive all hashes instead?
6. **Extra context:** Is `kavach_agent1` guaranteed to be optional and safe to
   ignore? The adapter currently ignores it entirely.
7. **Contract sign-off:** `a1-to-a2-draft-1` is provisional. When the contract
   is frozen, confirm the field names, the timestamp/text fallbacks and whether
   unknown top-level fields should be rejected (current adapter behaviour) or
   ignored.

## Tests

`tests/test_incident_payload_adapter.py` covers full and minimal payloads,
missing optional fields, blank-string normalisation, identifier-only locations,
invalid values, raw/ambiguous upstream fields, HTTP-only fields and non-mapping
input.
