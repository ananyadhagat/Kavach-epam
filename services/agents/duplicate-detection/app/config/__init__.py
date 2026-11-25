"""Configurable policy values (weights and thresholds).

Values are provisional hypotheses from the Phase 1 specification and have not
been validated against labelled data.
"""

from app.config.settings import (
    DEFAULT_SETTINGS,
    CategoryCompatibilityMap,
    ComparatorSettings,
    DecisionPolicySettings,
    DecisionThresholds,
    MatchingWeights,
    Settings,
)

__all__ = [
    "DEFAULT_SETTINGS",
    "CategoryCompatibilityMap",
    "ComparatorSettings",
    "DecisionPolicySettings",
    "DecisionThresholds",
    "MatchingWeights",
    "Settings",
]
