# src/kavach/main.py
import os

from dotenv import load_dotenv

load_dotenv()  # reads .env from the current working directory

from fastapi import FastAPI  # noqa: E402

from kavach.api.routes.supervisor import router as supervisor_router  # noqa: E402

app = FastAPI(title="Kavach API")
app.include_router(supervisor_router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    mode = (os.getenv("KAVACH_LLM_MODE") or "mock").strip().lower()
    return {
        "status": "ok",
        "llm_mode": mode,
        "gemini_key_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "model": os.getenv("GEMINI_MODEL") or "gemini-2.5-flash",
    }
