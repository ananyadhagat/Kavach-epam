# KAVACH Verification Agent

FastAPI prototype that accepts Field Worker completion references, checks stored evidence, calculates plan/GPS/visual findings, persists an audit response and returns a versioned JSON contract. See [docs/INTEGRATION.md](docs/INTEGRATION.md) for the cross-agent field mapping, endpoint, decision statuses, visual pipeline and review threshold.

## Backend

Install `requirements.txt`, configure `.env` from `.env.example`, then run:

```powershell
uvicorn app.main:app --reload
```

Swagger is at `http://127.0.0.1:8000/docs`. Verification requires the configured `X-KAVACH-API-Key`. `VISION_PROVIDER=mock` is the default for local fixtures; Gemini requires an allowed `GEMINI_API_KEY` and `GEMINI_MODEL`.

## Confidence and status

OpenCV landmark alignment and Gemini semantic cleanup scoring feed `verification_confidence`. If the confidence is below `KAVACH_REVIEW_CONFIDENCE_THRESHOLD` (default 80), the response is `MANUAL_REVIEW`, `requires_manual_review=true`, and includes `LOW_VERIFICATION_CONFIDENCE`. The Supervisor/orchestrator owns the actual inspector assignment or notification; this verification service emits the routing signal and does not implement that queue.
