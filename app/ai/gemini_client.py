"""DEPRECATED: Gemini client removed in favor of deterministic zero-LLM sanitation planning."""


def generate_text(*args, **kwargs):
    raise RuntimeError(
        "Gemini client is forbidden in Module 04. Deterministic zero-LLM architecture is active."
    )
