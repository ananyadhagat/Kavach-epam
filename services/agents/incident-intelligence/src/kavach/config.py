"""Runtime settings, read from environment variables (never hard-code secrets)."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Default is the REAL model. Mock must be chosen explicitly (KAVACH_LLM_MODE=mock) so a deployment
    # with a missing env var can never silently serve keyword-classifier output as if it were Gemini.
    llm_mode: str = "gemini"  # "mock" | "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 30.0
    repository: str = "memory"  # "memory" | "postgres"
    database_url: str | None = None
    max_image_bytes: int = 8 * 1024 * 1024
    max_images: int = 4
    # --- added (new optional variables; no existing variable renamed)
    media_dir: str | None = None              # KAVACH_MEDIA_DIR: store uploaded images on disk; unset = in-memory
    read_api_key: str | None = None           # KAVACH_READ_API_KEY: required for GET /incidents/{id}
    rate_limit_per_minute: int = 30           # KAVACH_RATE_LIMIT_PER_MINUTE: POST limit per client IP (0 = off)
    duplicate_detection_url: str | None = None  # KAVACH_DUPLICATE_DETECTION_URL: Agent 2 endpoint (optional)
    handoff_timeout_seconds: float = 10.0     # KAVACH_HANDOFF_TIMEOUT_SECONDS

    @property
    def max_request_bytes(self) -> int:
        """Whole multipart body cap: all images + 1 MB for form fields."""
        return self.max_images * self.max_image_bytes + 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_mode=os.getenv("KAVACH_LLM_MODE", "gemini").lower(),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            gemini_timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30")),
            repository=os.getenv("KAVACH_REPOSITORY", "memory").lower(),
            database_url=os.getenv("DATABASE_URL") or None,
            max_image_bytes=int(os.getenv("KAVACH_MAX_IMAGE_BYTES", str(8 * 1024 * 1024))),
            max_images=int(os.getenv("KAVACH_MAX_IMAGES", "4")),
            media_dir=os.getenv("KAVACH_MEDIA_DIR") or None,
            read_api_key=os.getenv("KAVACH_READ_API_KEY") or None,
            rate_limit_per_minute=int(os.getenv("KAVACH_RATE_LIMIT_PER_MINUTE", "30")),
            duplicate_detection_url=os.getenv("KAVACH_DUPLICATE_DETECTION_URL") or None,
            handoff_timeout_seconds=float(os.getenv("KAVACH_HANDOFF_TIMEOUT_SECONDS", "10")),
        )
