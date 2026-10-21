import json

import pytest

from app.ai.sanitation_graph import identify_issue_type_with_gemini


def mock_gemini(monkeypatch, response):
    monkeypatch.setattr(
        "app.ai.sanitation_graph.generate_text",
        lambda prompt: response,
    )


def test_overflowing_dustbin_classification(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": "overflowing_dustbin",
            "reason": "The dustbin is overflowing.",
        }),
    )

    assert identify_issue_type_with_gemini(
        "Overflowing public dustbin"
    )[0] == "overflowing_dustbin"


def test_garbage_pile_classification(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": "garbage_pile",
            "reason": "A large garbage pile is reported.",
        }),
    )

    assert identify_issue_type_with_gemini(
        "A large garbage pile near the entrance"
    )[0] == "garbage_pile"


def test_dirty_public_toilet_classification(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": "dirty_public_toilet",
            "reason": "The public toilet is dirty.",
        }),
    )

    assert identify_issue_type_with_gemini(
        "The public toilet is dirty"
    )[0] == "dirty_public_toilet"


def test_waste_spill_classification(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": "waste_spill",
            "reason": "Waste has spilled near the collection point.",
        }),
    )

    assert identify_issue_type_with_gemini(
        "Waste spill near the collection point"
    )[0] == "waste_spill"


def test_unknown_issue_returns_none(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": None,
            "reason": "This is a broken streetlight, not a supported sanitation issue.",
        }),
    )

    assert identify_issue_type_with_gemini(
        "Broken streetlight"
    )[0] is None


def test_classification_handles_unusual_wording(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": "overflowing_dustbin",
            "reason": "The description indicates overflowing waste bins.",
        }),
    )

    issue_type, reason = identify_issue_type_with_gemini(
        "Waste bins are spilling over everywhere."
    )

    assert issue_type == "overflowing_dustbin"
    assert reason


def test_clean_dustbin_is_not_classified_as_overflowing(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": None,
            "reason": "The dustbin is clean and empty.",
        }),
    )

    assert identify_issue_type_with_gemini(
        "The dustbin is clean and empty"
    )[0] is None


def test_invalid_gemini_json_is_rejected(monkeypatch):
    mock_gemini(monkeypatch, "This is not JSON")

    with pytest.raises(ValueError, match="invalid JSON"):
        identify_issue_type_with_gemini("Overflowing public dustbin")


def test_unsupported_gemini_category_is_rejected(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({
            "issue_type": "workers_already_dispatched",
            "reason": "Unsupported category.",
        }),
    )

    with pytest.raises(ValueError, match="unsupported issue type"):
        identify_issue_type_with_gemini("Overflowing public dustbin")


def test_missing_classification_reason_is_rejected(monkeypatch):
    mock_gemini(
        monkeypatch,
        json.dumps({"issue_type": "waste_spill"}),
    )

    with pytest.raises(ValueError, match="classification reason"):
        identify_issue_type_with_gemini("Waste spill near the entrance")


def test_gemini_exception_is_propagated(monkeypatch):
    def simulate_failure(prompt):
        raise RuntimeError("Simulated Gemini failure")

    monkeypatch.setattr(
        "app.ai.sanitation_graph.generate_text",
        simulate_failure,
    )

    with pytest.raises(RuntimeError, match="Simulated Gemini failure"):
        identify_issue_type_with_gemini("Overflowing public dustbin")
