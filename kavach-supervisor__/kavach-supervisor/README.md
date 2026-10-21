# Kavach Supervisor Agent (stage 1)

Supervisor Agent (agent 3) of the Kavach incident workflow.
For one new incident it chooses the department, sets the priority, makes a
basic action plan and decides if the plan can go ahead.

**Gemini only suggests. The final decision is made by the python rules.**

## Files
- `app/data.py` - departments, routing rules, allowed actions, sample incidents
- `app/supervisor.py` - Gemini call and all the decision logic
- `app/main.py` - FastAPI app

## Setup
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Create a `.env` file:
```
GEMINI_MODEL=gemini-3.8-flash
```
No key yet? Use `LLM_PROVIDER=mock` in `.env` to test without Gemini.

## Run
```
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs. `GET /samples` gives sample incidents,
`POST /supervisor/evaluate` evaluates one.

## Output
`approval_status` is one of:
- `APPROVED_TO_PROCEED` - routine case, can go to the Sanitation agent
- `PENDING_APPROVAL` - plan is fine but an official must approve first
- `NEEDS_REVIEW` - missing/conflicting info, Gemini problem, or no agent for that department

`reason_codes` explains why.

## Rules 
- immediate_safety_risk = true -> HIGH
- incomplete evidence -> needs review
- path obstructed -> MEDIUM
- safety unknown (null) -> not treated as LOW, goes to review / human approval
- only LOW and MEDIUM can be auto approved, HIGH needs a human

## Not done yet
- Not tested with the real Gemini key yet
- Not connected to the other agents (input fields are my own guess)
- Approval queue and the "verification failed -> back to supervisor" loop
- Rules need to be confirmed by the team
- No automated tests yet
