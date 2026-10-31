"""Semantic text comparator (local sentence embeddings + cosine similarity).

Approach
--------
The comparator encodes both complaint descriptions with a local
:class:`sentence_transformers.SentenceTransformer` model (by default
``sentence-transformers/all-MiniLM-L6-v2``), L2-normalises the vectors and
computes their cosine similarity. This is a *semantic* measure: paraphrases such
as "broken streetlight" and "lamp not working" can still receive a positive
similarity score even when they share no tokens.

Architecture boundary
---------------------
This module is a drop-in alternative to
:class:`~app.comparators.text_comparator.TextComparator` for the **single**
``text`` signal. It does not add a second text signal, does not touch the
weighted scoring engine, and never decides ``DUPLICATE`` / ``NEW`` /
``REVIEW_REQUIRED``. Callers select exactly one text backend with
:func:`app.comparators.factory.build_text_comparator`.

Model lifecycle
---------------
The model is loaded lazily on first use and cached **per process** (keyed by
model name) behind a lock, so it is never reloaded for every comparison. A
failed load is cached as a failure as well: repeated comparisons return an
``ERROR`` signal immediately instead of retrying a slow download for every
candidate. Call :func:`clear_model_cache` to retry a failed load (for example
from an operational health-check task).

No network access happens at import time. Tests inject a fake encoder through
``model=`` or ``loader=`` and therefore never download the model.

Status mapping
--------------
* missing or whitespace-only description -> ``UNAVAILABLE`` (``TEXT_UNAVAILABLE``)
* non-string description -> ``INVALID`` (``TEXT_INVALID``)
* model load failure -> ``ERROR`` (``TEXT_EMBEDDING_MODEL_LOAD_FAILED``)
* inference failure -> ``ERROR`` (``TEXT_EMBEDDING_INFERENCE_FAILED``)
* malformed / non-finite / zero-norm embedding -> ``ERROR``
  (``TEXT_EMBEDDING_INVALID_OUTPUT``)
* success -> ``AVAILABLE`` (``TEXT_EMBEDDING_SIMILARITY``)

Failures never become a score of ``0.0``. On success, ordinary cosine values in
``[-1, 1]`` are mapped to the ``SignalResult`` range by flooring negative
similarity at ``0.0``; the pre-floor cosine value is retained in
``details["raw_cosine"]``. This is a score-range adaptation, not error handling.

Limitations
-----------
* ``all-MiniLM-L6-v2`` truncates inputs beyond its maximum sequence length
  (256 word pieces); very long descriptions are only partially compared.
* Embedding similarity distributions differ from TF-IDF distributions. The
  provisional scoring thresholds and decision floors were not calibrated
  against this comparator; see ``docs/duplicate_detection/embedding_comparator.md``.
* The model is a local encoder only. No generative LLM, external LLM API or
  hosted inference service is used.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from app.comparators.base import (
    Comparator,
    available_signal,
    error_signal,
    invalid_signal,
    unavailable_signal,
)
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalResult

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
"""Initial candidate model. Small, CPU-friendly and deterministic at inference."""

REASON_SIMILARITY = "TEXT_EMBEDDING_SIMILARITY"
REASON_MODEL_LOAD_FAILED = "TEXT_EMBEDDING_MODEL_LOAD_FAILED"
REASON_INFERENCE_FAILED = "TEXT_EMBEDDING_INFERENCE_FAILED"
REASON_INVALID_OUTPUT = "TEXT_EMBEDDING_INVALID_OUTPUT"

_INVALID = object()

_WHITESPACE_RE = re.compile(r"\s+")

#: Maximum number of characters of an exception message kept in signal details.
_MAX_ERROR_DETAIL_CHARS = 300


class EmbeddingModelLoadError(RuntimeError):
    """Raised internally when the sentence-embedding model cannot be loaded."""

    def __init__(self, message: str, *, model_name: str, error_type: str) -> None:
        super().__init__(message)
        self.model_name = model_name
        self.error_type = error_type


class _CachedLoadFailure:
    """Sentinel stored in the process cache after a failed model load."""

    __slots__ = ("error_type", "message")

    def __init__(self, error_type: str, message: str) -> None:
        self.error_type = error_type
        self.message = message


# Process-wide model cache. The value is either a loaded model object or a
# _CachedLoadFailure. Injected models bypass this cache (see __init__).
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def clear_model_cache() -> None:
    """Clear the process-wide model cache, including cached load failures.

    Intended for tests and for operational recovery after a transient download
    or filesystem failure. Existing comparator instances will lazily reload on
    their next comparison.
    """

    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


def _load_sentence_transformer(model_name: str) -> Any:
    """Import and construct the default local encoder.

    Imported lazily so the rest of the application (and the test suite) can run
    without ``sentence-transformers`` or PyTorch installed, and so no model or
    network access happens at module import time.
    """

    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    return SentenceTransformer(model_name)


def _short_error(exc: BaseException) -> str:
    message = _WHITESPACE_RE.sub(" ", str(exc)).strip()
    if not message:
        return exc.__class__.__name__
    if len(message) > _MAX_ERROR_DETAIL_CHARS:
        return message[: _MAX_ERROR_DETAIL_CHARS - 3] + "..."
    return message


def _normalise_text(value: object) -> str | None | object:
    """Collapse whitespace and trim.

    Returns ``None`` for missing/blank input, the cleaned string for usable
    input, or the ``_INVALID`` sentinel for a non-string value. Mirrors the
    text comparator's input handling so the two backends share semantics.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID
    collapsed = _WHITESPACE_RE.sub(" ", value).strip()
    return collapsed if collapsed else None


def _display(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


class EmbeddingTextComparator(Comparator):
    """Semantic similarity between two complaint descriptions.

    Parameters
    ----------
    model_name:
        Hugging Face / Sentence Transformers model identifier. Defaults to
        :data:`DEFAULT_EMBEDDING_MODEL`.
    model:
        Optional pre-constructed encoder used instead of the process cache.
        The object must expose ``encode(list[str], normalize_embeddings=True,
        convert_to_numpy=True, show_progress_bar=False)``. Intended for tests
        and dependency injection; injected models are not cached.
    loader:
        Optional callable ``loader(model_name) -> encoder`` used instead of the
        default Sentence Transformers constructor. The result is cached per
        process under ``model_name``. Intended for tests and controlled
        deployments.
    """

    name = "text"

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        model: Any | None = None,
        loader: Callable[[str], Any] | None = None,
    ) -> None:
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        self._model_name = model_name.strip()

        if model is not None and not callable(getattr(model, "encode", None)):
            raise TypeError("model must provide a callable encode() method")
        if loader is not None and not callable(loader):
            raise TypeError("loader must be callable")
        if model is not None and loader is not None:
            raise ValueError("provide either model or loader, not both")

        self._model = model
        self._loader = loader

    @property
    def model_name(self) -> str:
        """Identifier of the configured encoder."""

        return self._model_name

    # -- record-level entry point ------------------------------------------ #
    def compare(self, complaint: Complaint, candidate: Complaint) -> SignalResult:
        """Compare ``complaint.description`` with ``candidate.description``."""

        return self.compare_texts(complaint.description, candidate.description)

    # -- field-level entry point ------------------------------------------- #
    def compare_texts(self, text_a: object, text_b: object) -> SignalResult:
        """Compare two raw description values without raising on bad input."""

        normalised_a = _normalise_text(text_a)
        normalised_b = _normalise_text(text_b)

        if normalised_a is _INVALID or normalised_b is _INVALID:
            return invalid_signal(
                "TEXT_INVALID",
                {
                    "text_a": _display(text_a),
                    "text_b": _display(text_b),
                },
            )

        if normalised_a is None or normalised_b is None:
            return unavailable_signal(
                "TEXT_UNAVAILABLE",
                {"text_a": normalised_a, "text_b": normalised_b},
            )

        assert isinstance(normalised_a, str) and isinstance(normalised_b, str)

        try:
            model = self._get_model()
        except EmbeddingModelLoadError as exc:
            return error_signal(
                REASON_MODEL_LOAD_FAILED,
                {
                    "model": self._model_name,
                    "error_type": exc.error_type,
                    "error": _short_error(exc),
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                },
            )

        try:
            embeddings = model.encode(
                [normalised_a, normalised_b],
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001 - converted to an ERROR signal
            return error_signal(
                REASON_INFERENCE_FAILED,
                {
                    "model": self._model_name,
                    "error_type": exc.__class__.__name__,
                    "error": _short_error(exc),
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                },
            )

        try:
            vectors = np.asarray(embeddings, dtype=np.float64)
        except Exception as exc:  # noqa: BLE001 - converted to an ERROR signal
            return error_signal(
                REASON_INVALID_OUTPUT,
                {
                    "model": self._model_name,
                    "error_type": exc.__class__.__name__,
                    "error": _short_error(exc),
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                },
            )

        if vectors.ndim != 2 or vectors.shape[0] != 2 or vectors.shape[1] == 0:
            return error_signal(
                REASON_INVALID_OUTPUT,
                {
                    "model": self._model_name,
                    "error_type": "ShapeError",
                    "error": f"expected a (2, dim) array, got shape {vectors.shape}",
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                },
            )

        if not np.all(np.isfinite(vectors)):
            return error_signal(
                REASON_INVALID_OUTPUT,
                {
                    "model": self._model_name,
                    "error_type": "NonFiniteEmbedding",
                    "error": "embedding contains NaN or infinite values",
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                },
            )

        norms = np.linalg.norm(vectors, axis=1)
        if bool(np.any(norms <= 0.0)):
            return error_signal(
                REASON_INVALID_OUTPUT,
                {
                    "model": self._model_name,
                    "error_type": "ZeroNormEmbedding",
                    "error": "embedding vector has zero magnitude",
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                },
            )

        normalised_vectors = vectors / norms[:, np.newaxis]
        raw_cosine = float(np.dot(normalised_vectors[0], normalised_vectors[1]))
        # Guard against tiny floating-point excursions outside the cosine range.
        raw_cosine = max(-1.0, min(1.0, raw_cosine))

        return available_signal(
            raw_cosine,
            REASON_SIMILARITY,
            {
                "basis": "sentence_embedding_cosine",
                "model": self._model_name,
                "embedding_dim": int(vectors.shape[1]),
                "raw_cosine": raw_cosine,
                "negative_cosine_floored": raw_cosine < 0.0,
                "normalised_embeddings": True,
                "text_a": normalised_a,
                "text_b": normalised_b,
            },
        )

    # -- model lifecycle ---------------------------------------------------- #
    def _get_model(self) -> Any:
        """Return the injected model or the cached process-wide model."""

        if self._model is not None:
            return self._model

        with _MODEL_CACHE_LOCK:
            if self._model_name in _MODEL_CACHE:
                cached = _MODEL_CACHE[self._model_name]
                if isinstance(cached, _CachedLoadFailure):
                    # Re-raise the recorded failure without retrying a slow
                    # download for every candidate comparison.
                    raise EmbeddingModelLoadError(
                        cached.message,
                        model_name=self._model_name,
                        error_type=cached.error_type,
                    )
                return cached

            loader = self._loader or _load_sentence_transformer
            try:
                model = loader(self._model_name)
            except Exception as exc:  # noqa: BLE001 - reported as an ERROR signal
                failure = _CachedLoadFailure(
                    exc.__class__.__name__,
                    _short_error(exc),
                )
                _MODEL_CACHE[self._model_name] = failure
                raise EmbeddingModelLoadError(
                    failure.message,
                    model_name=self._model_name,
                    error_type=failure.error_type,
                ) from exc

            if not callable(getattr(model, "encode", None)):
                message = "loaded model does not provide a callable encode() method"
                failure = _CachedLoadFailure("InvalidModel", message)
                _MODEL_CACHE[self._model_name] = failure
                raise EmbeddingModelLoadError(
                    message,
                    model_name=self._model_name,
                    error_type=failure.error_type,
                )

            _MODEL_CACHE[self._model_name] = model
            return model


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingModelLoadError",
    "EmbeddingTextComparator",
    "clear_model_cache",
]
