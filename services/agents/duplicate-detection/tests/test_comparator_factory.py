"""Tests for the comparator construction seam and embedding -> scoring path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from pydantic import ValidationError

from app.comparators import (
    CategoryComparator,
    EmbeddingTextComparator,
    LocationComparator,
    TextComparator,
    TimeComparator,
    build_core_comparators,
    build_text_comparator,
)
from app.comparators.embedding_text_comparator import clear_model_cache
from app.config.settings import ComparatorSettings, Settings
from app.schemas.complaint import Complaint, Location
from app.schemas.duplicate_response import Decision, SignalStatus
from app.scoring import DecisionPolicy
from app.scoring.engine import WeightedScoringEngine

UTC = timezone.utc
_MOMENT = datetime(2026, 10, 14, 9, 15, tzinfo=UTC)


class FakeEncoder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = {key: np.asarray(value, dtype=float) for key, value in vectors.items()}

    def encode(self, sentences, **kwargs):
        return np.asarray([self._vectors[text] for text in sentences], dtype=float)


class RaisingEncoder:
    def encode(self, sentences, **kwargs):
        raise RuntimeError("inference exploded")


def _location() -> Location:
    return Location(
        facility_id="FAC-CENTRAL-MARKET",
        location_id="LOC-CM-GATE-NORTH",
        latitude=12.9716,
        longitude=77.5946,
    )


def _complaints() -> tuple[Complaint, Complaint]:
    new = Complaint(
        complaint_id="NEW-1",
        description="broken streetlight near the north gate",
        category="STREETLIGHT",
        location=_location(),
        reported_at=_MOMENT,
    )
    candidate = Complaint(
        complaint_id="CMP-1",
        description="lamp not working by the north gate",
        category="STREETLIGHT",
        location=_location(),
        reported_at=_MOMENT + timedelta(hours=1),
    )
    return new, candidate


# --------------------------------------------------------------------------- #
# Factory: exactly one text signal, TF-IDF still selectable
# --------------------------------------------------------------------------- #
def test_default_factory_selects_embedding_backend_without_loading_it() -> None:
    clear_model_cache()

    text = build_text_comparator()

    assert isinstance(text, EmbeddingTextComparator)
    assert text.name == "text"
    assert text.model_name == "sentence-transformers/all-MiniLM-L6-v2"


def test_tfidf_backend_is_selectable_as_the_baseline() -> None:
    settings = Settings(comparators=ComparatorSettings(text_backend="tfidf"))

    text = build_text_comparator(settings)

    assert isinstance(text, TextComparator)
    assert text.name == "text"


def test_core_factory_builds_one_of_each_core_signal() -> None:
    settings = Settings(comparators=ComparatorSettings(text_backend="tfidf"))

    comparators = build_core_comparators(settings)

    assert set(comparators) == {"text", "location", "category", "time"}
    assert {comparator.name for comparator in comparators.values()} == set(comparators)
    text_comparators = [
        comparator
        for comparator in comparators.values()
        if isinstance(comparator, (TextComparator, EmbeddingTextComparator))
    ]
    assert len(text_comparators) == 1
    assert isinstance(comparators["location"], LocationComparator)
    assert isinstance(comparators["category"], CategoryComparator)
    assert isinstance(comparators["time"], TimeComparator)


def test_factory_uses_configured_embedding_model() -> None:
    clear_model_cache()
    settings = Settings(
        comparators=ComparatorSettings(
            text_backend="embedding",
            embedding_model="sentence-transformers/paraphrase-MiniLM-L3-v2",
        )
    )

    text = build_text_comparator(settings)

    assert isinstance(text, EmbeddingTextComparator)
    assert text.model_name == "sentence-transformers/paraphrase-MiniLM-L3-v2"


# --------------------------------------------------------------------------- #
# Configuration validation
# --------------------------------------------------------------------------- #
def test_unknown_text_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ComparatorSettings(text_backend="llm")


def test_blank_embedding_model_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ComparatorSettings(embedding_model="   ")


# --------------------------------------------------------------------------- #
# Embedding comparator -> weighted scoring engine
# --------------------------------------------------------------------------- #
def test_embedding_signal_scores_through_the_existing_engine() -> None:
    new, candidate = _complaints()
    embedding = EmbeddingTextComparator(
        model=FakeEncoder(
            {
                "broken streetlight near the north gate": [1.0, 0.05, 0.0],
                "lamp not working by the north gate": [0.98, 0.08, 0.0],
            }
        )
    )

    signals = {
        "text": embedding.compare(new, candidate),
        "location": LocationComparator().compare(new, candidate),
        "category": CategoryComparator().compare(new, candidate),
        "time": TimeComparator().compare(new, candidate),
    }
    result = WeightedScoringEngine().score(signals)

    assert signals["text"].status is SignalStatus.AVAILABLE
    assert signals["text"].score is not None and signals["text"].score > 0.99
    assert result.score is not None
    assert 0.0 <= result.score <= 1.0
    assert result.configured_weights["text"] == pytest.approx(0.40)
    assert result.weights_used["text"] == pytest.approx(0.40)
    assert result.normalised is False
    assert result.signals["text"] is signals["text"]
    assert sum(result.contributions.values()) == pytest.approx(result.score)


def test_text_failure_is_not_treated_as_zero_by_the_engine() -> None:
    new, candidate = _complaints()
    embedding = EmbeddingTextComparator(model=RaisingEncoder())

    signals = {
        "text": embedding.compare(new, candidate),
        "location": LocationComparator().compare(new, candidate),
        "category": CategoryComparator().compare(new, candidate),
        "time": TimeComparator().compare(new, candidate),
    }
    result = WeightedScoringEngine().score(signals)

    assert signals["text"].status is SignalStatus.ERROR
    assert signals["text"].score is None
    assert result.score is not None
    assert result.normalised is True
    assert "text" not in result.weights_used
    assert sum(result.weights_used.values()) == pytest.approx(1.0)
    assert result.signals["text"] is signals["text"]


def test_embedding_result_survives_the_m3_to_m4_adapter() -> None:
    new, candidate = _complaints()
    embedding = EmbeddingTextComparator(
        model=FakeEncoder(
            {
                "broken streetlight near the north gate": [1.0, 0.0],
                "lamp not working by the north gate": [1.0, 0.02],
            }
        )
    )

    signals = {
        "text": embedding.compare(new, candidate),
        "location": LocationComparator().compare(new, candidate),
        "category": CategoryComparator().compare(new, candidate),
        "time": TimeComparator().compare(new, candidate),
    }
    result = WeightedScoringEngine().score(signals)
    candidate_score = result.to_candidate_score(candidate.complaint_id)

    assert candidate_score.incident_id == candidate.complaint_id
    assert candidate_score.score == result.score
    assert candidate_score.signals["text"].status is SignalStatus.AVAILABLE


def test_embedding_to_decision_end_to_end_is_duplicate() -> None:
    new, candidate = _complaints()
    embedding = EmbeddingTextComparator(
        model=FakeEncoder(
            {
                "broken streetlight near the north gate": [1.0, 0.0],
                "lamp not working by the north gate": [1.0, 0.02],
            }
        )
    )

    signals = {
        "text": embedding.compare(new, candidate),
        "location": LocationComparator().compare(new, candidate),
        "category": CategoryComparator().compare(new, candidate),
        "time": TimeComparator().compare(new, candidate),
    }
    result = WeightedScoringEngine().score(signals)
    outcome = DecisionPolicy().decide(
        [result.to_candidate_score(candidate.complaint_id)]
    )

    assert outcome.decision is Decision.DUPLICATE
    assert outcome.matched_incident_id == candidate.complaint_id
    assert outcome.score == result.score
    assert outcome.candidates[0].contradictions == ()
