"""Unit tests for :mod:`app.comparators.embedding_text_comparator`.

These tests inject a fake encoder, so they never download the model, import
PyTorch, or require network access. Real-model behaviour is exercised separately
by the illustrative evaluation script documented in
``docs/duplicate_detection/embedding_comparator.md``.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from app.comparators.embedding_text_comparator import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingTextComparator,
    clear_model_cache,
)
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalStatus


class FakeEncoder:
    """Deterministic encoder backed by an explicit text -> vector mapping."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = {key: np.asarray(value, dtype=float) for key, value in vectors.items()}
        self.requests: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, sentences, **kwargs):
        self.requests.append((list(sentences), dict(kwargs)))
        return np.asarray([self._vectors[text] for text in sentences], dtype=float)


class RaisingEncoder:
    def encode(self, sentences, **kwargs):
        raise RuntimeError("inference exploded")


class FixedOutputEncoder:
    def __init__(self, output: object) -> None:
        self._output = output

    def encode(self, sentences, **kwargs):
        return self._output


@pytest.fixture(autouse=True)
def _isolate_model_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def _comparator(vectors: dict[str, list[float]]) -> tuple[EmbeddingTextComparator, FakeEncoder]:
    encoder = FakeEncoder(vectors)
    return EmbeddingTextComparator(model=encoder), encoder


# --------------------------------------------------------------------------- #
# Cosine similarity behaviour
# --------------------------------------------------------------------------- #
def test_identical_descriptions_score_one() -> None:
    text = "Large pothole on the main road near the central market"
    comparator, encoder = _comparator({text: [0.3, -0.4, 0.5]})

    result = comparator.compare_texts(text, text)

    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(1.0)
    assert result.reason == "TEXT_EMBEDDING_SIMILARITY"
    assert result.details is not None
    assert result.details["basis"] == "sentence_embedding_cosine"
    assert result.details["model"] == DEFAULT_EMBEDDING_MODEL
    assert result.details["embedding_dim"] == 3
    assert result.details["raw_cosine"] == pytest.approx(1.0)
    assert result.details["negative_cosine_floored"] is False
    assert encoder.requests[0][0] == [text, text]


def test_semantic_paraphrase_scores_high() -> None:
    comparator, _ = _comparator(
        {
            "broken streetlight": [1.0, 0.02, 0.0],
            "lamp not working": [1.0, 0.08, 0.0],
        }
    )

    result = comparator.compare_texts("broken streetlight", "lamp not working")

    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None
    assert result.score > 0.99
    assert result.details is not None
    assert result.details["raw_cosine"] > 0.99


def test_unrelated_descriptions_score_near_zero() -> None:
    comparator, _ = _comparator(
        {
            "broken streetlight": [1.0, 0.0],
            "garbage overflowing behind market": [0.0, 1.0],
        }
    )

    result = comparator.compare_texts(
        "broken streetlight", "garbage overflowing behind market"
    )

    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(0.0)
    assert result.details is not None
    assert result.details["raw_cosine"] == pytest.approx(0.0)


def test_zero_magnitude_vectors_are_normalised_before_cosine() -> None:
    # Unnormalised vectors must still produce a unit cosine, not a dot product
    # of raw magnitudes.
    comparator, _ = _comparator(
        {
            "a": [3.0, 4.0],
            "b": [6.0, 8.0],
        }
    )

    result = comparator.compare_texts("a", "b")

    assert result.status is SignalStatus.AVAILABLE
    assert result.score == pytest.approx(1.0)


def test_negative_cosine_is_floored_to_zero_but_raw_value_is_retained() -> None:
    comparator, _ = _comparator(
        {
            "a": [1.0, 0.0],
            "b": [-1.0, 0.0],
        }
    )

    result = comparator.compare_texts("a", "b")

    assert result.status is SignalStatus.AVAILABLE
    assert result.score == 0.0
    assert result.details is not None
    assert result.details["raw_cosine"] == pytest.approx(-1.0)
    assert result.details["negative_cosine_floored"] is True


def test_whitespace_is_collapsed_before_encoding() -> None:
    comparator, encoder = _comparator({"broken streetlight": [1.0, 0.0]})

    result = comparator.compare_texts("  broken   streetlight ", "broken streetlight")

    assert result.status is SignalStatus.AVAILABLE
    assert result.details is not None
    assert result.details["text_a"] == "broken streetlight"
    assert encoder.requests[0][0] == ["broken streetlight", "broken streetlight"]


# --------------------------------------------------------------------------- #
# Input handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text_a", "text_b"),
    [
        (None, "broken streetlight"),
        ("broken streetlight", None),
        ("", "broken streetlight"),
        ("   ", "broken streetlight"),
        ("broken streetlight", "\t\n"),
    ],
)
def test_missing_or_blank_text_is_unavailable(text_a, text_b) -> None:
    comparator, encoder = _comparator({"broken streetlight": [1.0, 0.0]})

    result = comparator.compare_texts(text_a, text_b)

    assert result.status is SignalStatus.UNAVAILABLE
    assert result.score is None
    assert result.reason == "TEXT_UNAVAILABLE"
    assert encoder.requests == []


@pytest.mark.parametrize("invalid", [123, 4.5, ["text"], {"text": "value"}, object()])
def test_non_string_text_is_invalid(invalid) -> None:
    comparator, encoder = _comparator({"broken streetlight": [1.0, 0.0]})

    result = comparator.compare_texts(invalid, "broken streetlight")

    assert result.status is SignalStatus.INVALID
    assert result.score is None
    assert result.reason == "TEXT_INVALID"
    assert result.details is not None
    assert result.details["text_a"] == str(invalid)
    assert encoder.requests == []


# --------------------------------------------------------------------------- #
# Model lifecycle and failures
# --------------------------------------------------------------------------- #
def test_model_is_loaded_once_per_process_across_instances() -> None:
    calls: list[str] = []

    def loader(model_name: str):
        calls.append(model_name)
        return FakeEncoder({"broken streetlight": [1.0, 0.0]})

    first = EmbeddingTextComparator(loader=loader)
    second = EmbeddingTextComparator(loader=loader)

    for comparator in (first, second, first):
        result = comparator.compare_texts("broken streetlight", "broken streetlight")
        assert result.status is SignalStatus.AVAILABLE

    assert calls == [DEFAULT_EMBEDDING_MODEL]


def test_model_load_failure_is_error_and_is_not_zero_similarity() -> None:
    calls: list[str] = []

    def failing_loader(model_name: str):
        calls.append(model_name)
        raise OSError("model download unavailable")

    comparator = EmbeddingTextComparator(loader=failing_loader)

    first = comparator.compare_texts("broken streetlight", "lamp not working")
    second = comparator.compare_texts("broken streetlight", "lamp not working")

    for result in (first, second):
        assert result.status is SignalStatus.ERROR
        assert result.score is None
        assert result.reason == "TEXT_EMBEDDING_MODEL_LOAD_FAILED"
        assert result.details is not None
        assert result.details["error_type"] == "OSError"
        assert result.details["model"] == DEFAULT_EMBEDDING_MODEL

    # The failure is cached so a slow/failing download is not retried for every
    # candidate comparison.
    assert len(calls) == 1

    # Operators/tests can clear the cache to retry a transient failure.
    clear_model_cache()
    third = comparator.compare_texts("broken streetlight", "lamp not working")
    assert third.status is SignalStatus.ERROR
    assert len(calls) == 2


def test_inference_failure_is_error() -> None:
    comparator = EmbeddingTextComparator(model=RaisingEncoder())

    result = comparator.compare_texts("broken streetlight", "lamp not working")

    assert result.status is SignalStatus.ERROR
    assert result.score is None
    assert result.reason == "TEXT_EMBEDDING_INFERENCE_FAILED"
    assert result.details is not None
    assert result.details["error_type"] == "RuntimeError"


@pytest.mark.parametrize(
    "output",
    [
        [1.0, 0.0],  # 1-D, expected (2, dim)
        np.zeros((1, 3)),  # wrong batch size
        np.zeros((2, 0)),  # zero-width embeddings
        np.asarray([[1.0, np.nan], [0.0, 1.0]]),  # non-finite
        np.asarray([[0.0, 0.0], [1.0, 0.0]]),  # zero-norm first vector
        ["not", "numeric"],  # cannot cast to float
        [],  # empty output
    ],
)
def test_malformed_model_output_is_error(output) -> None:
    comparator = EmbeddingTextComparator(model=FixedOutputEncoder(output))

    result = comparator.compare_texts("broken streetlight", "lamp not working")

    assert result.status is SignalStatus.ERROR
    assert result.score is None
    assert result.reason == "TEXT_EMBEDDING_INVALID_OUTPUT"
    assert result.details is not None
    assert result.details["text_a"] == "broken streetlight"
    assert result.details["text_b"] == "lamp not working"


def test_concurrent_first_use_loads_model_once() -> None:
    calls: list[str] = []
    barrier = threading.Barrier(4)

    def loader(model_name: str):
        calls.append(model_name)
        time.sleep(0.05)  # widen the race window without slowing the suite much
        return FakeEncoder(
            {
                "broken streetlight": [1.0, 0.0],
                "lamp not working": [1.0, 0.05],
            }
        )

    comparator = EmbeddingTextComparator(loader=loader)

    def worker(_: int):
        barrier.wait()
        return comparator.compare_texts("broken streetlight", "lamp not working")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(4)))

    assert all(result.status is SignalStatus.AVAILABLE for result in results)
    assert calls == [DEFAULT_EMBEDDING_MODEL]


# --------------------------------------------------------------------------- #
# Constructor and record-level behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model_name", ["", "   ", None, 123])
def test_invalid_model_name_is_rejected(model_name) -> None:
    with pytest.raises(ValueError):
        EmbeddingTextComparator(model_name=model_name)


def test_invalid_injected_model_is_rejected() -> None:
    with pytest.raises(TypeError):
        EmbeddingTextComparator(model=object())


def test_invalid_loader_is_rejected() -> None:
    with pytest.raises(TypeError):
        EmbeddingTextComparator(loader="not callable")


def test_model_and_loader_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError):
        EmbeddingTextComparator(model=FakeEncoder({}), loader=lambda _: FakeEncoder({}))


def test_compare_uses_complaint_descriptions() -> None:
    comparator, _ = _comparator(
        {
            "broken streetlight": [1.0, 0.0],
            "lamp not working": [1.0, 0.02],
        }
    )
    new = Complaint(complaint_id="NEW-1", description="broken streetlight")
    candidate = Complaint(complaint_id="CMP-1", description="lamp not working")

    result = comparator.compare(new, candidate)

    assert result.status is SignalStatus.AVAILABLE
    assert result.score is not None
    assert 0.0 <= result.score <= 1.0
