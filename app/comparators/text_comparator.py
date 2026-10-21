"""Text comparator (lexical TF-IDF + cosine similarity).

Approach
--------
For each comparison a fresh :class:`sklearn.feature_extraction.text
.TfidfVectorizer` is fitted to **just the two descriptions**, producing two
L2-normalised TF-IDF vectors; their cosine similarity is the score. This is a
*lexical* measure: it rewards sharing of exact (lower-cased) tokens and their
1-2 word n-grams, and knows nothing about meaning.

Limitations (important)
-----------------------
* **No semantic understanding.** "Broken streetlight" vs "lamp not working"
  share no tokens and score ``0.0`` despite describing the same thing. Paraphrase
  and synonym handling would need embeddings, which are explicitly out of scope.
* **Pair-local fitting.** Fitting per pair means IDF weights are not comparable
  across different candidate comparisons, and it is O(pairs) vectorisations.
  A production system should fit a **shared corpus** (or use a retrieval index)
  for consistent weighting and efficient candidate search. This prototype keeps
  pair-local fitting because it is simple, deterministic and dependency-light.
* **Short text is noisy.** With only two documents, rare terms dominate.

Outcomes
--------
* both sides non-blank ....................... ``AVAILABLE`` (finite, 0-1)
* either side missing/blank .................. ``UNAVAILABLE`` (score ``None``)
* present but produces no tokens
  (e.g. punctuation-only) .................... ``UNAVAILABLE`` (score ``None``)
* non-string (malformed) description ......... ``INVALID`` (score ``None``)

A punctuation-only description is treated as ``UNAVAILABLE`` (no usable lexical
evidence) rather than a penalty, so it never inflates or deflates the composite
score; the weighted engine in Phase 4 handles renormalisation.

Note that common words (e.g. "the") are **not** removed by default, so two
otherwise-unrelated sentences may share a small nonzero score through such
tokens. This is an honest consequence of a purely lexical measure; a project may
opt into ``stop_words`` (see the ``TextComparator`` constructor) if its
population is predominantly English.

No external API, model download, or persistent vector store is used.
"""

from __future__ import annotations

import re
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.comparators.base import (
    Comparator,
    available_signal,
    invalid_signal,
    unavailable_signal,
)
from app.schemas.complaint import Complaint
from app.schemas.duplicate_response import SignalResult

_INVALID = object()

_WHITESPACE_RE = re.compile(r"\s+")

#: Deterministic, dependency-free tokenisation: 2+ word characters.
_DEFAULT_TOKEN_PATTERN = r"(?u)\b\w\w+\b"


def _normalise_text(value: object) -> str | None | object:
    """Collapse whitespace and trim.

    Returns ``None`` for missing/blank input, the cleaned string for usable
    input, or the ``_INVALID`` sentinel for a non-string value. Case is left
    intact (the vectorizer lower-cases internally).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return _INVALID
    collapsed = _WHITESPACE_RE.sub(" ", value).strip()
    return collapsed if collapsed else None


class TextComparator(Comparator):
    """Lexical similarity between two complaint descriptions.

    Parameters
    ----------
    token_pattern:
        Regex used to extract tokens. Defaults to words of 2+ characters.
    ngram_range:
        TF-IDF n-gram range. Defaults to unigrams; ``(1, 2)`` adds bigrams.
    stop_words:
        Optional stop-word policy forwarded to the vectorizer (e.g. the string
        ``"english"``). ``None`` (default) keeps every token, which is
        language-agnostic.
    """

    name = "text"

    def __init__(
        self,
        token_pattern: str = _DEFAULT_TOKEN_PATTERN,
        ngram_range: tuple[int, int] = (1, 1),
        stop_words: str | list[str] | None = None,
    ) -> None:
        self._token_pattern = token_pattern
        self._ngram_range = ngram_range
        self._stop_words = stop_words

    # -- record-level entry point ------------------------------------------ #
    def compare(self, complaint: Complaint, candidate: Complaint) -> SignalResult:
        """Compare ``complaint.description`` with ``candidate.description``."""
        return self.compare_texts(complaint.description, candidate.description)

    # -- field-level entry point ------------------------------------------- #
    def compare_texts(self, text_a: object, text_b: object) -> SignalResult:
        """Compare two raw description values."""
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

        vectorizer = TfidfVectorizer(
            lowercase=True,
            token_pattern=self._token_pattern,
            ngram_range=self._ngram_range,
            sublinear_tf=False,
            stop_words=self._stop_words,
        )

        # Detect present-but-token-less input *before* fitting: with two
        # documents the vectorizer would otherwise borrow the other side's
        # vocabulary and silently return a 0.0 score for punctuation-only text.
        analyzer = vectorizer.build_analyzer()
        token_count_a = len(analyzer(normalised_a))
        token_count_b = len(analyzer(normalised_b))
        if token_count_a == 0 or token_count_b == 0:
            return unavailable_signal(
                "TEXT_NO_TOKENS",
                {
                    "text_a": normalised_a,
                    "text_b": normalised_b,
                    "token_count_a": token_count_a,
                    "token_count_b": token_count_b,
                },
            )

        try:
            matrix = vectorizer.fit_transform([normalised_a, normalised_b])
        except ValueError:
            # Any remaining vectorizer edge case (e.g. empty vocabulary).
            return unavailable_signal(
                "TEXT_EMPTY_VOCABULARY",
                {"text_a": normalised_a, "text_b": normalised_b},
            )

        if matrix.shape[1] == 0:
            return unavailable_signal(
                "TEXT_EMPTY_VOCABULARY",
                {"text_a": normalised_a, "text_b": normalised_b},
            )

        score = float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])

        return available_signal(
            score,
            "TEXT_SIMILARITY",
            self._build_details(vectorizer, matrix, normalised_a, normalised_b),
        )

    @staticmethod
    def _build_details(
        vectorizer: TfidfVectorizer,
        matrix: Any,
        text_a: str,
        text_b: str,
    ) -> dict[str, Any]:
        features = vectorizer.get_feature_names_out()
        present_a = matrix[0].toarray()[0] > 0
        present_b = matrix[1].toarray()[0] > 0
        shared = sorted(features[present_a & present_b].tolist())
        return {
            "basis": "tfidf_cosine",
            "term_count_a": int(present_a.sum()),
            "term_count_b": int(present_b.sum()),
            "shared_terms": shared[:20],
            "shared_term_count": len(shared),
            "text_a": text_a,
            "text_b": text_b,
        }


def _display(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


__all__ = ["TextComparator"]
