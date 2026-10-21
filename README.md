# KAVACH - Incident Intelligence Agent (Agent 1)

Citizen complaint (text, optional images/voice transcript, device GPS, map pin) ->
validated, structured `StructuredIncidentRecord` ready for the Duplicate Detection Agent.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest httpx
cp .env.example .env           # set GEMINI_API_KEY and KAVACH_LLM_MODE=gemini for the real model (default is gemini)
pytest                          # fully offline: mock LLM, in-memory repo
cd src && uvicorn kavach.main:app --reload --env-file ../.env
```

```bash
curl -X POST localhost:8000/api/v1/incidents \
  -H "X-Request-ID: demo-1" \
  -F complaint_text="Dustbin near the main gate is overflowing and blocking the path" \
  -F selected_latitude=23.2500 -F selected_longitude=77.4000 \
  -F device_latitude=23.2503 -F device_longitude=77.4002 -F device_accuracy_meters=15 \
  -F images=@photo.jpg
```
`X-Request-ID` makes retries idempotent (same ID + same payload returns the same record, no second LLM call;
same ID + different payload -> 409).

Read a record (needs `KAVACH_READ_API_KEY`):
```bash
curl -H "X-API-Key: $KAVACH_READ_API_KEY" localhost:8000/api/v1/incidents/INC-XXXX
curl -H "X-API-Key: $KAVACH_READ_API_KEY" localhost:8000/api/v1/incidents/INC-XXXX/duplicate-detection-request
```
PostgreSQL tests: `pip install "psycopg[binary]"` then
`KAVACH_TEST_DATABASE_URL=postgresql://user@localhost:5432/kavach_test pytest`.

See `CHANGES.md` for the v1.1.0 audit fixes.

## Responsibility split
| Concern | Owner |
|---|---|
| Input validation, ranges, NaN/inf | Pydantic (`schemas/`) |
| Image safety (real format, size, pixel cap) | `services/media/validation.py` |
| EXIF GPS -> decimal degrees | `services/location/exif_reader.py`, `coordinate_conversion.py` |
| Distance, source comparison, reason codes | `services/location/` (deterministic, no LLM) |
| Semantic classification, facts, image observations | Gemini via `agents/incident_intelligence.py` |
| Schema + taxonomy checks, bounded repair (1 retry) | `output_validator.py`, agent |
| Severity safety floor (never lowered below HIGH on danger keywords) | `severity_rules.py` |
| Provenance, persistence, idempotency | `orchestrator.py`, `repositories/` |

## Behaviour contract
- Location sources (pin / device / EXIF / facility) stay separate; none overwrites another.
- A far-away citizen is a **valid remote report** (`MISMATCH` + `REMOTE_REPORT_POSSIBLE`, no review flag).
  Device-vs-EXIF disagreement -> `SOURCE_CONFLICT` + `requires_human_review`.
- Gemini timeout/quota -> **503** (+`Retry-After`); Gemini rejects request (bad key etc.) -> **502** `LLM_REQUEST_REJECTED`;
  invalid output after one repair -> **502**. Nothing is fabricated or stored.
- Storage failure -> **503** `STORAGE_UNAVAILABLE`. Rate limit -> **429**. Oversized upload -> **413**.
- Without a map pin, device GPS / EXIF are NOT used as the incident location: `INCIDENT_LOCATION_UNKNOWN` + clarification.
- The record keeps the citizen's original text, raw device/EXIF evidence, server receipt time and image references.
- Unknown category -> `OTHER`/`UNKNOWN`, `needs_clarification=true`. Unknown severity stays `UNKNOWN`.
- Bad images are rejected per-file (`IMAGE_REJECTED:<id>:<reason>` in `missing_information`); the request continues.
- Logs contain IDs/status only - never coordinates or raw EXIF.

## Needs your team's decision / not done here
- **Auth / RBAC**: reads use a shared `X-API-Key` stop-gap; replace `require_read_access` with the gateway JWT dependency. Rate limit is in-process (per worker). Anonymous reporting policy must be explicit.
- **Agent 2 contract**: `handoff.py` mapping is a draft (`a1-to-a2-draft-1`) until both teams sign off.
- Thresholds (`LocationRules`: 100 m radius, 150 m max accuracy, 250 m conflict) are placeholders - calibrate with field tests.
- Category taxonomy and the severity keyword floor (English only) need ops sign-off.
- Voice: accepts an already-produced `voice_transcript`; choose/add the speech-to-text component separately.
- `PostgresIncidentRepository` is a minimal JSONB store (tested against PostgreSQL 16). Normalized evidence tables from the geolocation guide are a later step.
- `facility_reference` is supported in the pipeline but intentionally not exposed on the public API (must come from a server-side lookup).
