# src/kavach/agents/supervisor.py
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from kavach.schemas.supervisor import (
    GeminiSupervisorSuggestion,
    PriorityLevel,
    SupervisorIncidentInput,
    most_severe,
)
from kavach.services.supervisor.prompt_builder import SYSTEM_INSTRUCTION, build_supervisor_prompt
from kavach.services.supervisor.reference_data import (
    UNRESOLVED_DEPARTMENT,
    UNRESOLVED_WARD,
    resolve_department_deterministically,
    resolve_ward_deterministically,
)

logger = logging.getLogger(__name__)

VALID_MODES = {"mock", "gemini"}
DEFAULT_MODEL = "gemini-2.5-flash"  # override with GEMINI_MODEL in .env

# Mock mode only: simple hazard words so the escalation path can be tested without an API key
MOCK_HAZARD_KEYWORDS = ("sewage", "biohazard", "hospital", "bathing", "ghat", "stampede", "chemical")


class SupervisorAgentClient:
    """
    Gemini wrapper for Process 3.0 advisory evaluation.
    Env: KAVACH_LLM_MODE=mock|gemini, GEMINI_API_KEY (or GOOGLE_API_KEY), GEMINI_MODEL.
    """

    def __init__(
        self,
        llm_mode: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        raw_mode = llm_mode or os.getenv("KAVACH_LLM_MODE") or os.getenv("LLM_PROVIDER") or "mock"
        self.llm_mode = raw_mode.strip().lower()
        if self.llm_mode not in VALID_MODES:
            raise ValueError(f"KAVACH_LLM_MODE must be one of {sorted(VALID_MODES)}, got '{raw_mode}'.")
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = model_name or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self.last_error: Optional[str] = None
        self.last_called: bool = False
        self.last_raw_text: Optional[str] = None
        self.last_suggestion: Optional[GeminiSupervisorSuggestion] = None

    # ------------------------------------------------------------------ public
    def evaluate(self, incident: SupervisorIncidentInput) -> Optional[GeminiSupervisorSuggestion]:
        self.last_error = None
        self.last_called = False
        self.last_raw_text = None
        self.last_suggestion = None
        if self.llm_mode == "mock":
            self.last_suggestion = self._evaluate_mock(incident)
            return self.last_suggestion
        return self._evaluate_gemini(incident)

    # ------------------------------------------------------------------ mock
    def _evaluate_mock(self, incident: SupervisorIncidentInput) -> GeminiSupervisorSuggestion:
        dept = (
            resolve_department_deterministically(incident.category, incident.incident_type)
            or UNRESOLVED_DEPARTMENT
        )
        loc = incident.location_metadata
        ward = (
            resolve_ward_deterministically(
                locality=loc.locality,
                latitude=loc.latitude,
                longitude=loc.longitude,
                ward_hint=loc.ward_hint,
            )
            or UNRESOLVED_WARD
        )

        base = incident.resolved_priority or PriorityLevel.P2
        suggested = base
        text = incident.description.lower()
        reasons: list[str] = []
        if any(k in text for k in MOCK_HAZARD_KEYWORDS):
            suggested = most_severe(base, PriorityLevel.P2)
            reasons.append("MOCK_HAZARD_KEYWORD")
        if dept != UNRESOLVED_DEPARTMENT:
            reasons.append(f"DEPT_RESOLVED_{dept}")
        if ward != UNRESOLVED_WARD:
            reasons.append(f"WARD_RESOLVED_{ward}")

        return GeminiSupervisorSuggestion(
            department=dept,
            ward_or_route=ward,
            suggested_priority=suggested,
            reason_codes=reasons or ["MOCK_EVALUATION_COMPLETED"],
            rationale=(
                f"[MOCK] Resolved department {dept} from taxonomy "
                f"({incident.category}/{incident.incident_type}) and ward {ward} from location metadata."
            ),
        )

    # ------------------------------------------------------------------ gemini
    def _call_gemini(self, prompt: str) -> Optional[str]:
        """Network call. Isolated so tests can override it without touching the API."""
        if not self.api_key:
            self.last_error = "GEMINI_API_KEY missing"
            logger.error("KAVACH_LLM_MODE=gemini but no GEMINI_API_KEY / GOOGLE_API_KEY is set.")
            return None

        from google import genai
        from google.genai import types

        self.last_called = True  # a real API request is about to be sent
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=GeminiSupervisorSuggestion,
            ),
        )
        return response.text if response else None

    def _evaluate_gemini(self, incident: SupervisorIncidentInput) -> Optional[GeminiSupervisorSuggestion]:
        try:
            text = self._call_gemini(build_supervisor_prompt(incident))
            self.last_raw_text = text
            if not text:
                self.last_error = self.last_error or "empty response"
                logger.warning("Empty response from Gemini: %s", self.last_error)
                return None
            self.last_suggestion = GeminiSupervisorSuggestion.model_validate(json.loads(text))
            return self.last_suggestion
        except Exception as exc:  # network, auth, quota, malformed JSON, schema mismatch
            self.last_error = type(exc).__name__
            logger.exception("Gemini Supervisor evaluation failed: %s", exc)
            return None
