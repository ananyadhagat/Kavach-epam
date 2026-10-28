"""DEPRECATED: issue_classifier removed. Upstream category and incident_type determine templates deterministically."""


def identify_issue_type_with_gemini(*args, **kwargs):
    raise RuntimeError(
        "LLM classification is forbidden in Module 04. Deterministic policy resolution is active."
    )
