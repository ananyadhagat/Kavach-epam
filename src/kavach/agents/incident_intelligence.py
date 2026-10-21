"""Agent 1: semantic understanding via an LLM, behind a swappable interface.

The agent only interprets language/images. Validation, location math, EXIF and severity floors
are deterministic code elsewhere. The agent never fabricates output when the LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from kavach.config import Settings
from kavach.errors import (
    IncidentProcessingError,
    LLMRequestRejectedError,
    LLMUnavailableError,
    OutputValidationError,
)
from kavach.schemas.incident_intelligence import GeminiIncidentProposal, IncidentIntelligenceInput
from kavach.services.incident_intelligence.output_validator import validate_proposal
from kavach.services.incident_intelligence.prompt_builder import (
    PromptBundle,
    build_prompt,
    build_repair_prompt,
)
from kavach.services.media.validation import ValidatedImage

logger = logging.getLogger(__name__)


class IncidentLLM(Protocol):
    name: str

    def generate(self, prompt: PromptBundle) -> str:
        """Return raw model text (expected JSON). Raise LLMUnavailableError on timeout/quota/config."""
        ...


# ------------------------------------------------------------------ Gemini
_RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


def classify_llm_exception(exc: Exception) -> Exception:
    """Map an SDK/network failure to a controlled domain error.

    Timeouts, 429 quota, 5xx and network errors -> LLMUnavailableError (retryable, HTTP 503).
    Other HTTP 4xx (bad API key, permission, invalid request) -> LLMRequestRejectedError (not retryable).
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int) and 400 <= code < 500 and code not in _RETRYABLE_HTTP:
        logger.error("gemini_request_rejected status=%s type=%s", code, type(exc).__name__)
        return LLMRequestRejectedError(f"Gemini rejected the request (HTTP {code})")
    logger.error("gemini_call_failed status=%s type=%s", code, type(exc).__name__)
    return LLMUnavailableError("Gemini request failed, was rate-limited or timed out")


class GeminiLLM:
    def __init__(self, api_key: str | None, model: str, timeout_seconds: float):
        if not api_key:
            raise LLMUnavailableError("GEMINI_API_KEY is not configured")
        from google import genai  # lazy import: tests/mock mode work without the SDK
        from google.genai import types

        self._types = types
        self._model = model
        self.name = f"gemini:{model}"
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )

    def generate(self, prompt: PromptBundle) -> str:
        t = self._types
        parts: list = [t.Part.from_bytes(data=img.content, mime_type=img.mime_type) for img in prompt.images]
        parts.append(prompt.user_text)
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=parts,
                config=t.GenerateContentConfig(
                    system_instruction=prompt.system_instruction,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            text = response.text or ""
        except Exception as exc:  # noqa: BLE001 - classified below; never fabricate output
            raise classify_llm_exception(exc) from exc
        return text


# ------------------------------------------------------------------ Mock (development / tests only)
class MockLLM:
    """Deterministic keyword classifier. Offline. NOT for production: it only demonstrates the contract."""
    name = "mock-llm"

    _RULES: tuple[tuple[str, str, str], ...] = (
        (r"toilet|washroom|restroom|urinal", "SANITATION", "DIRTY_PUBLIC_TOILET"),
        (r"litter|littering|plastic wrappers?", "SANITATION", "LITTERING"),
        (r"garbage|waste|dustbin|\bbin\b|trash|rubbish", "SANITATION", "WASTE_OVERFLOW"),
        (r"street ?light|lamp ?post", "ELECTRICAL", "BROKEN_STREETLIGHT"),
        (r"exposed wires?|live wire|sparking|electric", "ELECTRICAL", "EXPOSED_WIRING"),
        (r"burst pipe|broken pipe|pipe", "WATER_SUPPLY", "BROKEN_PIPE"),
        (r"leak", "WATER_SUPPLY", "WATER_LEAKAGE"),
        (r"bench", "MAINTENANCE", "DAMAGED_BENCH"),
        (r"pothole|road", "MAINTENANCE", "ROAD_DAMAGE"),
        (r"crowd|stampede", "PUBLIC_SAFETY", "CROWD_CONGESTION"),
        (r"\bfire\b|smoke", "PUBLIC_SAFETY", "FIRE_HAZARD"),
    )

    def generate(self, prompt: PromptBundle) -> str:
        m = re.search(r"<complaint>\n(.*?)\n</complaint>", prompt.user_text, re.DOTALL)
        text = (m.group(1) if m else "").strip()
        low = text.lower()
        category, itype = "OTHER", "UNKNOWN"
        for pattern, cat, typ in self._RULES:
            if re.search(pattern, low):
                category, itype = cat, typ
                break
        severity = "MEDIUM" if re.search(r"block|overflow|spill", low) else "UNKNOWN"
        return json.dumps({
            "incident_summary": text[:200] or "No description",
            "category": category,
            "incident_type": itype,
            "severity_recommendation": severity,
            "severity_reason": "Mock keyword heuristic",
            "extracted_facts": [{"fact": text[:250], "source": "COMPLAINT_TEXT"}] if text else [],
            "claimed_location_text": None,
            "claimed_time_text": None,
            "image_observations": [f"{len(prompt.images)} image(s) attached (not analysed in mock mode)"]
            if prompt.images else [],
            "missing_information": [],
            "conflicting_information": [],
            "needs_clarification": False,
            "clarification_questions": [],
        })


def create_llm(settings: Settings) -> IncidentLLM:
    if settings.llm_mode == "gemini":
        return GeminiLLM(settings.gemini_api_key, settings.gemini_model, settings.gemini_timeout_seconds)
    if settings.llm_mode == "mock":
        logger.warning("Running with MockLLM - development only")
        return MockLLM()
    raise ValueError(f"Unknown KAVACH_LLM_MODE: {settings.llm_mode!r}")


# ------------------------------------------------------------------ Agent
class IncidentIntelligenceAgent:
    def __init__(self, llm: IncidentLLM, max_repairs: int = 1):
        self.llm = llm
        self.max_repairs = max_repairs

    def interpret(self, inp: IncidentIntelligenceInput, images: list[ValidatedImage]) -> GeminiIncidentProposal:
        original = build_prompt(inp, images)
        prompt = original
        for attempt in range(self.max_repairs + 1):
            raw = self.llm.generate(prompt)  # LLMUnavailableError propagates: no fabricated output
            try:
                return validate_proposal(raw)
            except OutputValidationError as exc:
                logger.warning("model_output_invalid attempt=%d problems=%d", attempt, len(exc.problems))
                if attempt >= self.max_repairs:
                    raise IncidentProcessingError("Model output remained invalid after bounded repair") from exc
                prompt = build_repair_prompt(original, exc.problems)
        raise IncidentProcessingError("unreachable")  # pragma: no cover
