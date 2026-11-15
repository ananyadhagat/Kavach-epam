# Kavach Supervisor Agent (Process 3.0)

Input: incident JSON  ->  Output: Supervisor decision JSON (`supervisor_decision`, `routing`, `audit`).

## Setup (Windows PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then edit .env
```
macOS/Linux: `source .venv/bin/activate` and `cp .env.example .env`.

## .env
```
KAVACH_LLM_MODE=gemini            # mock = no API call, gemini = real Gemini call
GEMINI_API_KEY=<your new key>     # GOOGLE_API_KEY also works
GEMINI_MODEL=gemini-2.5-flash     # any model your account can use
KAVACH_REQUIRE_DUPLICATE_CHECK=false   # true once process 2.0 supplies duplicate_check
```

## Run on a JSON file (quickest check)
```powershell
python scripts/run_supervisor.py sample_incident.json              # uses .env mode
python scripts/run_supervisor.py sample_incident.json --mode gemini
python scripts/run_supervisor.py sample_incident_critical.json
```
`audit.actor` is `supervisor_agent:gemini` when the real API was used and `supervisor_agent:mock` otherwise.
If Gemini fails (bad key, quota, malformed output) you get NEEDS_REVIEW with `LLM_EVALUATION_FAILED` and the error class in `audit.rationale`.

## What the output contains
`supervisor_decision`, `routing`, `audit`, and `llm_response`:
- `llm_response.called`: true only when a real Gemini request was sent
- `llm_response.raw_text`: exact text Gemini returned
- `llm_response.parsed_suggestion`: Gemini's department, ward, suggested priority, reason codes, rationale
- `llm_response.error`: error class if the call or parsing failed
- `llm_response.skipped_reason`: `HARD_GATE_FAILED` or `MOCK_MODE_NO_API_CALL` when no call was made

Compare `parsed_suggestion.suggested_priority` with `supervisor_decision.priority` to see where code overrode Gemini.

## Run as an API
```powershell
$env:PYTHONPATH="src"; uvicorn kavach.main:app --reload
# health: GET http://127.0.0.1:8000/health      docs: http://127.0.0.1:8000/docs
curl -X POST http://127.0.0.1:8000/api/v1/supervisor/evaluate -H "Content-Type: application/json" -d @sample_incident.json
```
One endpoint: `POST /api/v1/supervisor/evaluate` (incident report JSON in, decision JSON out). Nothing is stored.

## Tests
```powershell
pytest            # pytest.ini sets PYTHONPATH and mock mode; no API key needed
```

## Rules enforced in code
- `duplicate_check` is optional in this phase (the input can be just an incident report). If it is supplied it must be completed and NEW, with no candidate >= 0.90 similarity, otherwise NEEDS_REVIEW with no Gemini call. Set `KAVACH_REQUIRE_DUPLICATE_CHECK=true` to make it mandatory.
- Priority = most severe of Agent 1 severity and the Gemini suggestion. Never lowered. A raised priority, P1, or a high-risk incident type is output as PENDING_APPROVAL (no approval step exists in this phase; it is just the status).
- Department and ward must exist in `reference_data.py`; departments without a domain agent go to review.
- Deadlines come from the SLA table using `reported_at`.
- Only APPROVED_TO_PROCEED has `dispatch_eligible=true`. Gemini cannot set approval status.
- Unresolved department/ward are `null`; `priority` is always P1-P4.

## Edit these to match your team
`src/kavach/services/supervisor/reference_data.py`: departments, wards, SLA, approval rules, duplicate statuses and threshold, default priority.
