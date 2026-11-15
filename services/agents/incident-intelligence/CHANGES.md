# Changes - v1.1.0 (audit fixes, 17 Oct 2026)

No file deleted or renamed. No new runtime dependency. Existing env variable names unchanged.
Tests: 93 -> 130 passing (3 PostgreSQL tests run when KAVACH_TEST_DATABASE_URL is set; verified on PostgreSQL 16).

| ID | Fix | Files |
|---|---|---|
| C-01 | Original `complaint_text` and `voice_transcript` stored verbatim in the record | schemas/incident_intelligence.py, orchestrator.py |
| C-02 | Raw evidence kept: `device_location`, `image_exif_results`, server `submitted_at` | same |
| C-03 | Accepted images stored (`services/media/storage.py`); record `media[]` has full sha256, 64-bit dHash `perceptual_hash`, `storage_ref` | media/validation.py, media/storage.py (new) |
| C-04 | Device GPS / EXIF are never promoted to `reported_incident_location`; no pin -> `INCIDENT_LOCATION_UNKNOWN` + clarification question | orchestrator.py |
| C-05 | `GET` endpoints need `X-API-Key` (= `KAVACH_READ_API_KEY`), closed (403) if unset; per-IP POST rate limit; 413 for oversized bodies | api/routes/incidents.py, main.py, config.py |
| C-06 | Same `X-Request-ID` + different payload -> 409 `REQUEST_ID_REUSED`; parallel duplicates call the LLM once; Postgres race returns the stored record | orchestrator.py, repositories/incident_repository.py |
| C-07 | Storage failure -> controlled 503 `STORAGE_UNAVAILABLE` (nothing half-saved) | errors.py, routes, repository |
| C-08 | MPO (multi-picture JPEG from many Android/Samsung phones) accepted | media/validation.py |
| C-09 | Images beyond `KAVACH_MAX_IMAGES` are not read into memory | routes |
| C-10 | Gemini 4xx (bad key/permission/invalid request) -> 502 `LLM_REQUEST_REJECTED` (not retryable); 429/5xx/timeout stay 503 | agents/incident_intelligence.py |
| C-11 | Severity floor also covers Hindi + Hinglish danger words (aag, करंट, ghayal, भगदड़ ...) | severity_rules.py |
| C-12 | Text-only complaint: model image observations / IMAGE facts dropped; prompt-tag injection neutralised; EXIF 0,0 = invalid; poor-accuracy device can't trigger SOURCE_CONFLICT; mock no longer default | orchestrator.py, prompt_builder.py, exif_reader.py, verification.py, config.py |
| Handoff | `services/incident_intelligence/handoff.py` maps the record to Agent 2's documented request; optional POST to `KAVACH_DUPLICATE_DETECTION_URL`; `GET /api/v1/incidents/{id}/duplicate-detection-request` | new |

## Provisional decisions - confirm with the team
1. Agent 2 mapping (handoff.py docstring): `category` sent as incident_type (e.g. WASTE_OVERFLOW); `facility_id`/`location_id` null.
2. Read auth is a shared API key until the gateway JWT/RBAC exists.
3. No-pin complaints are accepted but flagged `needs_clarification`.
4. Taxonomy, severity rubric/floor and location thresholds remain placeholders needing ops sign-off.
5. Not done (needs a decision or a new dependency): HEIC images, speech-to-text, ward lookup, facility lookup, normalised evidence tables.

# Changes - v1.1.1 (17 Oct 2026)
- `services/media/validation.py`: perceptual hash uses `Image.get_flattened_data()` when available
  (`getdata()` is deprecated and removed in Pillow 14, Oct 2027). Same pixel values -> identical hashes.
- Tests: `test_rejected_llm_request_returns_502_and_stores_nothing` now also asserts exactly 1 LLM call and
  no `Retry-After` header; new `test_gemini_generate_makes_exactly_one_call_per_error` drives the real
  `GeminiLLM.generate()` with a fake SDK client (401/403/400 -> rejected, 429/503 -> unavailable, 1 call each).
- Note: `google-genai` is a declared dependency; install with `pip install -r requirements.txt pytest httpx`
  before running tests (the SDK-level tests fail with ModuleNotFoundError otherwise).
