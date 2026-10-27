# KAVACH — Incident Intelligence Agent (Agent 1)

**KAVACH** is a FastAPI-based incident intelligence service that converts citizen complaints into structured, validated incident records for the Duplicate Detection Agent (Agent 2).

Citizens can submit complaints using text, an optional voice transcript, images, device GPS coordinates, and a map-selected incident location. The pipeline validates evidence, analyses the complaint, checks location consistency, applies severity rules, records evidence provenance, and persists the resulting incident record.

## Key Features

- **Structured incident analysis:** Classifies incidents by category and incident type and produces a summary, extracted facts, image observations, and clarification questions.
- **Text and voice-transcript input:** Supports typed complaints and browser-generated voice transcripts.
- **Image validation:** Validates image formats and size constraints, computes hashes, and extracts image metadata.
- **GPS and EXIF verification:** Keeps the user-selected incident pin, device location, image EXIF GPS, and facility reference separate.
- **Deterministic location checks:** Compares available location evidence and records distances, accuracy, reason codes, and review requirements.
- **Severity safeguards:** Applies deterministic severity rules so configured danger keywords can enforce a minimum severity.
- **Evidence provenance:** Tracks evidence sources, image references, hashes, model information, and rule versions.
- **Idempotent submissions:** Uses `X-Request-ID` to prevent duplicate processing of identical retries.
- **Duplicate Detection handoff:** Maps the structured incident record to the downstream Agent 2 contract.
- **Timezone-aware timestamps:** Uses the `Asia/Kolkata` timezone for server-generated submission and creation timestamps.

## Architecture

```text
Citizen Complaint
       |
       v
FastAPI Incident API
       |
       v
Request Validation and Idempotency
       |
       v
Image Validation and Storage
       |
       v
EXIF Metadata Extraction
       |
       v
Deterministic Location Verification
       |
       v
Incident Intelligence Agent
       |
       v
Output Validation and Repair
       |
       v
Severity Rules and Evidence Merge
       |
       v
StructuredIncidentRecord
       |
       v
Repository Persistence
       |
       v
Duplicate Detection Agent (Agent 2)
```

## Technology Stack

- Python
- FastAPI
- Pydantic
- Uvicorn
- Gemini through the incident intelligence agent
- Pytest and HTTPX for testing
- In-memory repository and media storage for lightweight testing
- PostgreSQL JSONB repository support
- Python `zoneinfo` and `tzdata` for timezone handling

## Project Structure

```text
kavach-agent1/
├── frontend/
│   └── index.html
├── src/
│   └── kavach/
│       ├── agents/
│       │   └── incident_intelligence.py
│       ├── api/
│       │   └── routes/
│       │       └── incidents.py
│       ├── repositories/
│       │   └── incident_repository.py
│       ├── schemas/
│       │   ├── incident_intelligence.py
│       │   └── location.py
│       ├── services/
│       │   ├── incident_intelligence/
│       │   ├── location/
│       │   └── media/
│       ├── errors.py
│       └── main.py
├── tests/
│   ├── integration/
│   └── ...
├── .env.example
├── requirements.txt
├── CHANGES.md
└── README.md
```

*The tree above highlights the main components; it is not an exhaustive listing of every file.*

## Prerequisites

- Python 3.11 or a compatible version supported by the project dependencies.
- Git.
- A Gemini API key when using the real Gemini model.
- PostgreSQL only if you want to run the PostgreSQL-backed repository or its database integration tests.

## Setup and Installation

### Windows — PowerShell

Run these commands from the project root.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Configure the environment:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally and configure the required variables, including `GEMINI_API_KEY` and `KAVACH_LLM_MODE`, according to your environment.

**Never commit `.env` or API keys to GitHub.**

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

### Timezone Configuration

The orchestrator generates timezone-aware timestamps using `ZoneInfo("Asia/Kolkata")`. The `tzdata` package is included in `requirements.txt` to support environments, particularly Windows, that do not provide the required IANA timezone database.

Generated timestamps use the `+05:30` offset. Existing records are not automatically converted or rewritten.

## Running the Application

From the project root, activate the virtual environment and run:

```powershell
python -m uvicorn kavach.main:app --reload --app-dir src --env-file .env
```

Available local endpoints:

- **API documentation:** http://127.0.0.1:8000/docs
- **Incident tester:** http://127.0.0.1:8000/tester/
- **Local API:** http://127.0.0.1:8000

The interactive tester supports the complaint submission flow. Browser-based voice input requires browser speech-recognition support and microphone permission.

## Running Tests

Run the test suite from the project root:

```powershell
python -m pytest -q
```

The test suite includes incident submission, image validation, location verification, severity safeguards, idempotency, API error handling, repository behaviour, and Agent 2 handoff.

Some PostgreSQL integration tests require a running PostgreSQL instance and the corresponding test database configuration.

## API Usage

### Submit an Incident

Endpoint:

```http
POST /api/v1/incidents
```

Example using `curl`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/incidents \
  -H "X-Request-ID: demo-1" \
  -F 'complaint_text=Dustbin near the main gate is overflowing and blocking the path' \
  -F 'selected_latitude=23.2500' \
  -F 'selected_longitude=77.4000' \
  -F 'device_latitude=23.2503' \
  -F 'device_longitude=77.4002' \
  -F 'device_accuracy_meters=15' \
  -F 'images=@photo.jpg'
```

The image and location values are illustrative. Use valid coordinates and an actual image for your test.

The API can accept the supported complaint fields, including `voice_transcript`, optional images, device location, and a selected incident location. Check `/docs` for the current request schema.

### Request Idempotency

`X-Request-ID` identifies a submission for retry handling.

- Same request ID and same payload: returns the existing incident record.
- Same request ID and a different payload: returns `409 Conflict`.
- Identical retries do not require a second LLM call when the existing record is found.

### Read an Incident

Reading an incident requires `KAVACH_READ_API_KEY` when read authentication is configured.

```bash
curl http://127.0.0.1:8000/api/v1/incidents/INC-XXXX \
  -H "X-API-Key: YOUR_READ_API_KEY"
```

### Retrieve the Duplicate Detection Handoff Payload

```bash
curl http://127.0.0.1:8000/api/v1/incidents/INC-XXXX/duplicate-detection-request \
  -H "X-API-Key: YOUR_READ_API_KEY"
```

Replace the example incident ID and API key with valid values from your environment.

## Incident Record

The `StructuredIncidentRecord` is the primary output of Agent 1. Depending on the submitted evidence, it can contain:

- Incident ID and request ID.
- Incident summary, category, and incident type.
- Severity recommendation, reason, and matched rules.
- Extracted facts with their evidence sources.
- Original complaint text and voice transcript.
- User-selected incident location and device location.
- Image metadata, hashes, and EXIF GPS results.
- Location consistency checks and reason codes.
- Missing information, conflicting information, and clarification questions.
- Evidence provenance and model/prompt version information.
- Server-generated submission and creation timestamps.
- Request fingerprint and media references.

Unavailable or uncertain information should remain explicit rather than being fabricated.

## Responsibility Split

| Component | Responsibility |
|---|---|
| `schemas/` | Input validation, types, and structured record definitions |
| `services/media/validation.py` | Image format, size, and image safety checks |
| `services/location/exif_reader.py` | Image metadata and EXIF GPS extraction |
| `services/location/` | Coordinate conversion and deterministic location verification |
| `agents/incident_intelligence.py` | Semantic classification, facts, summaries, and image observations |
| `services/incident_intelligence/output_validator.py` | Model output validation and bounded repair |
| `services/incident_intelligence/severity_rules.py` | Deterministic severity safeguards |
| `services/incident_intelligence/orchestrator.py` | Pipeline orchestration, evidence merging, timestamps, and persistence |
| `repositories/` | Incident repository implementations |
| `services/incident_intelligence/handoff.py` | Mapping and delivery to Duplicate Detection Agent |

## Behaviour and Safety Contract

- **Location evidence stays separate.** Device GPS and image EXIF are not silently substituted for the citizen's selected incident pin.
- **Remote reports are valid.** A citizen submitting a report from another location is not automatically classified as fraudulent.
- **Location consistency is not proof.** GPS proximity alone cannot establish that a complaint is genuine.
- **Missing incident location remains unknown.** Device GPS or EXIF coordinates are not automatically promoted to the reported incident location.
- **Unknown severity remains possible.** Severity depends on available evidence and the configured rules.
- **Image failures are handled per file.** Rejected images include a rejection reason; valid complaint processing can continue where the pipeline allows it.
- **Failures are controlled.** The API defines handling for model failures, storage errors, rate limits, and invalid requests.
- **Logs avoid sensitive evidence.** Coordinates and raw EXIF should not be written to application logs.

## Current Limitations and Team Decisions

The following areas require deployment configuration, calibration, or additional implementation:

- **Authentication and authorization:** The shared read API key is a stopgap. Production deployments should use appropriate identity, role-based access control, and gateway authentication.
- **Rate limiting:** An in-process limiter is not a substitute for distributed rate limiting across multiple workers.
- **Agent 2 contract:** Confirm and version the handoff contract jointly with the downstream team.
- **Location thresholds:** Current radius and accuracy thresholds are configurable policy values that require field validation.
- **Severity taxonomy:** Review category definitions, severity keywords, language coverage, and operational escalation rules with the responsible team.
- **Speech-to-text:** The current API accepts an already-produced voice transcript. Browser speech recognition is a separate frontend capability.
- **Evidence authenticity:** EXIF metadata and device GPS can be missing, inaccurate, or manipulated. They are signals, not cryptographic proof of capture.
- **Worker resolution evidence:** An enforced app-only live-capture workflow, server-side verification, and a separate worker evidence audit trail require further implementation and testing.
- **Database design:** The PostgreSQL repository provides a minimal JSONB persistence implementation. A normalized evidence schema can be introduced as a later improvement.

## Development Notes

- Keep `.env`, API keys, virtual environments, cache directories, and generated secrets out of commits.
- Run the test suite after changing schemas, orchestration, location verification, severity rules, or API routes.
- Update `CHANGES.md` when introducing notable behaviour changes.
- Coordinate schema changes with the Duplicate Detection Agent team before changing the handoff contract.

## License

Add the license and ownership information approved by your project or organization before making the repository public.
