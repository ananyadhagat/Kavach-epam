"""Severity rubric + deterministic safety floor.

Gemini *recommends* a severity; Python guarantees certain danger indicators can never be
rated below HIGH. The floor errs toward escalation (e.g. it cannot read negation like
"no fire") because a false HIGH costs a human glance, while a missed HIGH can cost safety.
English-keyword based: the LLM remains responsible for multilingual understanding, and
this list must be extended/approved by the KAVACH operations team.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from kavach.schemas.incident_intelligence import Severity

SEVERITY_RUBRIC = """\
LOW: routine nuisance, no obstruction, no health or safety effect.
MEDIUM: meaningful disruption (blocked path, strong odour, service unusable) needing timely action.
HIGH: immediate danger to people (injury, fire, electrical hazard, gas leak, structural collapse, crowd crush)
      or another urgent condition.
UNKNOWN: the complaint does not give enough information. Do NOT assume LOW when information is missing."""

_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}

HIGH_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (rule_id, re.compile(pattern, re.IGNORECASE))
    for rule_id, pattern in (
        ("INJURY", r"\b(injur\w*|bleeding|unconscious|ambulance|fractur\w*)\b"),
        ("FIRE", r"\b(fire|smoke|burning|explosion|blast)\b"),
        ("ELECTRICAL_HAZARD", r"\b(electrocut\w*|live wire|exposed wires?|sparking|short[- ]circuit)\b"),
        ("GAS_LEAK", r"\bgas leak\w*\b"),
        ("STRUCTURAL", r"\b(collaps\w*|about to fall|falling down)\b"),
        ("CROWD_CRUSH", r"\b(stampede|crowd crush|crushed)\b"),
        ("DROWNING", r"\b(drown\w*)\b"),
    )
)

# Hindi (Devanagari) + Hinglish (romanised) equivalents. Devanagari vowel signs are not \w in Python,
# so word edges are expressed as "not followed/preceded by another Devanagari character"
# (so that e.g. "आग" (fire) matches but "आगे" (ahead) does not).
_DV = r"[ऀ-ॿ]"


def _dv(words: str) -> str:
    return rf"(?<!{_DV})(?:{words})(?!{_DV})"


HIGH_RISK_PATTERNS = HIGH_RISK_PATTERNS + tuple(
    (rule_id, re.compile(pattern, re.IGNORECASE))
    for rule_id, pattern in (
        ("INJURY", _dv("घायल|खून|बेहोश|एम्बुलेंस") + r"|\b(ghayal|khoon|behosh)\b"),
        ("FIRE", _dv("आग|धुआं|धुआँ|धुंआ|विस्फोट") + r"|\b(aag|dhuan|dhuaan|dhuan)\b"),
        ("ELECTRICAL_HAZARD", _dv("करंट|नंगे तार|खुले तार|बिजली का तार") + r"|\b(karant|current lag\w*|nange taar|khule taar)\b"),
        ("GAS_LEAK", _dv("गैस लीक|गैस रिसाव") + r"|\bgas leak\w*\b"),
        ("STRUCTURAL", _dv("गिर गया|गिर गई|गिरने वाला|गिरने वाली|ढह") + r"|\b(gir gay[ai]|girne wal[ai])\b"),
        ("CROWD_CRUSH", _dv("भगदड़|भगदड") + r"|\b(bhagdad|bhagdar)\b"),
        ("DROWNING", _dv("डूब") + r"|\b(doob\w*|dub raha)\b"),
    )
)


@dataclass
class SeverityDecision:
    severity: Severity
    reason: str
    matched_rules: list[str] = field(default_factory=list)


def parse_severity(raw: str | None) -> Severity | None:
    value = (raw or "").strip().upper()
    return next((s for s in Severity if s.value == value), None)


def apply_severity_floor(text: str, recommended: Severity, model_reason: str = "") -> SeverityDecision:
    """Return max(model recommendation, rule floor). Never lowers; UNKNOWN stays UNKNOWN absent a rule hit."""
    matched = list(dict.fromkeys(rid for rid, rx in HIGH_RISK_PATTERNS if rx.search(text or "")))
    if matched:
        reason = f"Safety rule(s) {', '.join(matched)} matched; severity set to at least HIGH."
        if model_reason:
            reason += f" Model rationale: {model_reason}"
        return SeverityDecision(Severity.HIGH, reason, matched)
    return SeverityDecision(recommended, model_reason or "No rule override; model recommendation retained.", [])
